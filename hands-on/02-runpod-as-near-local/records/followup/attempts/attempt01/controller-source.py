"""Run bounded follow-up experiments; preserve old ledgers and all failed attempts."""
import base64
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import paramiko

from experiment import connect_pod, exec_ssh, s3_client
from runpod_api import ROOT, Runpod, save_json, utc_now

LEDGER = ROOT / 'private/followup-ledger.json'
OUT = ROOT / 'records/followup'
REMOTE = '/workspace/followup'
POD_TTL = 2100
BUDGET = 8.0


def state():
    return json.loads(LEDGER.read_text(encoding='utf-8'))


def record(value):
    save_json(LEDGER, value)


def cleanup(api, kind=None):
    current = state()
    for k in (('pod', 'volume') if kind is None else (kind,)):
        endpoint = 'pods' if k == 'pod' else 'networkvolumes'
        for r in current['resources']:
            if r['kind'] != k or r.get('deleted'):
                continue
            actual = api.request('GET', endpoint)
            matches = [a for a in actual if a['name'] == r['name'] and
                       (not r.get('id') or r['id'] == a['id'])]
            for a in matches:
                r['id'] = a['id']
                api.request('DELETE', endpoint + '/' + a['id'])
            for _ in range(12):
                if not any(a['name'] == r['name'] for a in api.request('GET', endpoint)):
                    r.update(deleted=True, deleted_at_epoch=time.time(), deleted_at_utc=utc_now())
                    break
                time.sleep(2)
            else:
                raise RuntimeError('Deletion not confirmed: ' + r['name'])
            record(current)


def create_pod(api, label):
    current = state()
    assert not api.request('GET', 'pods'), 'An account Pod already exists'
    selected = current['selected']
    # Live quote and stock at each create; frozen price catalog remains cached.
    query = '''{gpuTypes {id lowestPrice(input:{gpuCount:1,secureCloud:true,
      dataCenterId:%s,minMemoryInGb:16,minVcpuCount:2,supportPublicIp:true})
      {uninterruptablePrice stockStatus}}}''' % json.dumps(selected['data_center'])
    quote = next(g['lowestPrice'] for g in api.graphql(query)['gpuTypes']
                 if g['id'] == selected['gpu_type'])
    ceiling = current['reference_5090']['usd_per_gpu_hour']
    assert quote and quote['uninterruptablePrice'] <= ceiling, 'Live price exceeds ceiling'
    used = sum(max(0, r.get('deleted_at_epoch', time.time()) - r['created_at_epoch']) / 3600
        * r.get('total_hourly_usd', ceiling + .01)
        for r in current['resources'] if r['kind'] == 'pod')
    assert used + (ceiling + .02) * POD_TTL / 3600 + .15 <= BUDGET, 'Budget reservation exceeded'
    assert time.time() + POD_TTL < current['expires_at'], 'Global deadline reservation exceeded'
    name = current['experiment_id'] + '-' + label
    now = time.time()
    owned = {'kind': 'pod', 'name': name, 'id': None, 'created_at_epoch': now,
             'expires_at': now + POD_TTL, 'live_quote': quote}
    current['resources'].append(owned)
    record(current)
    key = paramiko.RSAKey.from_private_key_file(str(ROOT / 'private/id_rsa'))
    startup = ('mkdir -p /root/.ssh /run/sshd; chmod 700 /root/.ssh; '
        'printf "%s\\n" "$PUBLIC_KEY" > /root/.ssh/authorized_keys; '
        'chmod 600 /root/.ssh/authorized_keys; ssh-keygen -A; /usr/sbin/sshd; sleep infinity')
    cfg = json.loads((OUT / 'frozen-config.json').read_text(encoding='utf-8'))
    request = {'name': name, 'cloudType': 'SECURE', 'computeType': 'GPU',
        'gpuTypeIds': [selected['gpu_type']], 'gpuCount': 1,
        'dataCenterIds': [selected['data_center']], 'interruptible': False,
        'imageName': cfg['image'], 'containerDiskInGb': 20, 'volumeInGb': 0,
        'networkVolumeId': current['volume_id'], 'volumeMountPath': '/workspace',
        'ports': ['22/tcp'], 'supportPublicIp': True, 'minRAMPerGPU': 16, 'minVCPUPerGPU': 2,
        'dockerEntrypoint': ['/bin/bash', '-c'], 'dockerStartCmd': [startup],
        'env': {'PUBLIC_KEY': key.get_name() + ' ' + key.get_base64()}}
    start = time.monotonic()
    try:
        try:
            pod = api.request('POST', 'pods', request)
        except Exception:
            matches = [p for p in api.request('GET', 'pods') if p['name'] == name]
            if len(matches) != 1:
                raise
            pod = matches[0]
        current = state()
        r = next(r for r in current['resources'] if r['name'] == name)
        r['id'] = pod['id']
        r['total_hourly_usd'] = pod.get('costPerHr') or quote['uninterruptablePrice'] + .01
        record(current)
        assert r['total_hourly_usd'] <= ceiling + .01, 'Deployed quote exceeds ceiling'
        ssh, details = connect_pod(api, pod['id'], start + 480)
        save_json(ROOT / 'private' / (name + '-pod.json'), details)
        save_json(OUT / ('pod-' + label + '.json'), {'label': label, 'at_utc': utc_now(),
            'pod_id': pod['id'], 'ssh_seconds': time.monotonic() - start,
            'selected': selected, 'live_quote': quote, 'hourly_usd': r['total_hourly_usd']})
        exec_ssh(ssh, 'mkdir -p ' + REMOTE + '/runs')
        sftp = ssh.open_sftp()
        sftp.put(str(ROOT / 'scripts/followup_gpu.py'), REMOTE + '/followup_gpu.py')
        sftp.put(str(OUT / 'frozen-config.json'), REMOTE + '/config.json')
        sftp.close()
        print(label + ': SSH ready', flush=True)
        return ssh, pod['id']
    except Exception as exc:
        save_json(OUT / ('pod-' + label + '-failure.json'),
                  {'at_utc': utc_now(), 'error': type(exc).__name__ + ': ' + str(exc)})
        cleanup(api, 'pod')
        raise


def job(ssh, run_id, argv, expected=0, timeout=600):
    local = OUT / run_id
    if (local / 'result.json').exists():
        raise RuntimeError('Would overwrite results: ' + run_id)
    remote = REMOTE + '/runs/' + run_id
    exec_ssh(ssh, 'mkdir -p ' + shlex.quote(remote))
    # A wrapper records even os._exit(86), while remaining detached from SSH.
    command = ['python', '-u', REMOTE + '/followup_gpu.py'] + argv + ['--run-id', run_id]
    wrapper = ('import subprocess,json,pathlib,time; '
        f'p=pathlib.Path({remote!r}); t=time.monotonic(); '
        f'r=subprocess.run({command!r}); '
        '(p/"exit.json").write_text(json.dumps({"returncode":r.returncode,'
        '"wall_seconds":time.monotonic()-t}))')
    launch = ('import subprocess,os; '
        'env=dict(os.environ, PYTHONPATH="/workspace/followup/deps", '
        'HF_HOME="/workspace/followup/hf", HF_HUB_DISABLE_XET="1", '
        'CUBLAS_WORKSPACE_CONFIG=":4096:8", OMP_NUM_THREADS="2"); '
        f'log=open({(remote + "/job.log")!r},"ab"); '
        f'p=subprocess.Popen(["python","-c",{wrapper!r}],env=env,stdin=subprocess.DEVNULL,'
        'stdout=log,stderr=log,start_new_session=True); print(p.pid)')
    encoded = base64.b64encode(launch.encode()).decode()
    start = time.monotonic()
    pid = int(exec_ssh(ssh, 'python -c ' + shlex.quote(
        f'import base64;exec(base64.b64decode("{encoded}"))')).strip())
    exit_data = None
    while time.monotonic() - start < timeout:
        data = exec_ssh(ssh, f'cat {remote}/exit.json 2>/dev/null || true', timeout=30)
        if data:
            exit_data = json.loads(data)
            break
        time.sleep(2)
    local.mkdir(parents=True, exist_ok=True)
    sftp = ssh.open_sftp()
    for filename in ('exit.json', 'result.json', 'job.log'):
        try:
            sftp.get(remote + '/' + filename, str(local / filename))
        except FileNotFoundError:
            pass
    sftp.close()
    save_json(local / 'controller.json', {'run_id': run_id, 'at_utc': utc_now(), 'pid': pid,
        'expected_exit': expected, 'exit': exit_data,
        'local_roundtrip_seconds': time.monotonic() - start})
    if not exit_data or exit_data['returncode'] != expected:
        raise RuntimeError(f'{run_id}: unexpected exit; inspect local job.log')
    result = json.loads((local / 'result.json').read_text()) if (local / 'result.json').exists() else {}
    print(run_id + ': ' + str(exit_data['returncode']) + ' in ' +
          str(round(exit_data['wall_seconds'], 2)) + 's', flush=True)
    return result


def backup(ssh):
    """Back up baseline final states and the latest complete checkpoints via S3."""
    current = state()
    client = s3_client(current['selected']['data_center'])
    target = ROOT / 'private/followup-backups'
    manifests = []
    for seed in (11, 22, 33):
        for rel in (f'checkpoints/{seed}/step060.pt', f'checkpoints/{seed}/step060.json',
                    f'runs/train-baseline-{seed}/final.pt'):
            raw = client.get_object(Bucket=current['volume_id'], Key='followup/' + rel)['Body'].read()
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            manifests.append({'path': rel, 'bytes': len(raw),
                              'sha256': hashlib.sha256(raw).hexdigest(), 'source': 's3_full_object'})
        manifest = json.loads((target / f'checkpoints/{seed}/step060.json').read_text())
        raw = (target / f'checkpoints/{seed}/step060.pt').read_bytes()
        assert len(raw) == manifest['bytes'] and hashlib.sha256(raw).hexdigest() == manifest['sha256']
    save_json(OUT / 'backup-manifest.json', manifests)


def main():
    api = Runpod()
    if LEDGER.exists():
        raise RuntimeError('A follow-up ledger exists; use explicit recovery rather than overwrite it')
    assert not api.request('GET', 'pods'), 'Existing account Pods'
    pre = json.loads((OUT / 'preflight.json').read_text())
    selected = next(q for q in pre['candidates'] if q['gpu_type'] == 'NVIDIA L4'
                    and q['data_center'] == 'EU-RO-1')
    cfg = json.loads((ROOT / 'experiment.json').read_text(encoding='utf-8'))
    save_json(OUT / 'frozen-config.json', cfg)
    sources = ['scripts/followup.py', 'scripts/followup_gpu.py', '추가실험-아이디어선정.md']
    sources += [str(p.relative_to(ROOT)).replace('\\', '/') for p in (ROOT / 'docs/followup').glob('*.md')]
    save_json(OUT / 'preregistered.json', {'at_utc': utc_now(), 'source_sha256': {
        p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources},
        'budget_usd': BUDGET, 'pod_ttl_seconds': POD_TTL, 'global_ttl_seconds': 14400,
        'storage_order': ['ABC', 'BCA', 'CAB'], 'training_seeds': [11, 22, 33]})
    now = time.time()
    name = 'rpfollow-' + time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    current = {'experiment_id': name, 'finished': False, 'expires_at': now + 14400,
        'started_at_utc': utc_now(), 'selected': selected,
        'reference_5090': pre['reference_5090'], 'resources': [
            {'kind': 'volume', 'name': name + '-data', 'id': None,
             'created_at_epoch': now, 'expires_at': now + 14400}]}
    record(current)
    log = (ROOT / 'private/followup-watchdog.log').open('a')
    watchdog = subprocess.Popen([sys.executable, str(ROOT / 'scripts/watchdog.py'),
        '--ledger', 'private/followup-ledger.json'], cwd=ROOT, stdout=log, stderr=log,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    current['watchdog_pid'] = watchdog.pid
    record(current)
    ssh = None
    error = None
    try:
        try:
            volume = api.request('POST', 'networkvolumes', {'name': name + '-data',
                'size': 20, 'dataCenterId': selected['data_center']})
        except Exception:
            matches = [v for v in api.request('GET', 'networkvolumes') if v['name'] == name + '-data']
            if len(matches) != 1:
                raise
            volume = matches[0]
        current = state()
        current['volume_id'] = volume['id']
        current['resources'][0]['id'] = volume['id']
        record(current)
        ssh, _ = create_pod(api, 'prepare')
        before = time.monotonic()
        exec_ssh(ssh, 'python -m pip install --target /workspace/followup/deps '
            'transformers==4.57.1 huggingface-hub==0.36.0 safetensors==0.6.2 '
            '--quiet > /workspace/followup/install.log 2>&1', timeout=480)
        save_json(OUT / 'dependency-install.json', {'seconds': time.monotonic() - before})
        job(ssh, 'prepare', ['prepare'], timeout=600)
        sftp = ssh.open_sftp()
        sftp.get(REMOTE + '/prepared.json', str(OUT / 'prepared.json'))
        sftp.close()
        prepared = json.loads((OUT / 'prepared.json').read_text())
        known = json.loads((ROOT / 'manifests/model.json').read_text(encoding='utf-8'))
        # Compare pinned model weights against the previous experiment's manifest.
        previous = json.loads((ROOT / 'records/b01/result.json').read_text())['model_manifest']
        assert {p['path']: p['sha256'] for p in prepared['files']} == {
            p['path']: p['sha256'] for p in previous}
        ssh.close(); ssh = None
        cleanup(api, 'pod')
        for block, order in enumerate(('ABC', 'BCA', 'CAB'), 1):
            ssh, _ = create_pod(api, 'storage-' + str(block))
            for arm in order:
                job(ssh, f'storage-{block}-{arm}', ['storage', '--arm', arm], timeout=600)
            ssh.close(); ssh = None
            cleanup(api, 'pod')
        ssh, first = create_pod(api, 'train-before')
        for seed in (11, 22, 33):
            job(ssh, f'train-baseline-{seed}', ['train', '--mode', 'baseline', '--seed', str(seed)])
            job(ssh, f'train-fault-{seed}', ['train', '--mode', 'fault', '--seed', str(seed)], expected=86)
        backup(ssh)
        ssh.close(); ssh = None
        cleanup(api, 'pod')
        ssh, second = create_pod(api, 'train-after')
        assert first != second, 'Training did not move to a new Pod'
        save_json(OUT / 'training-pod-transition.json', {'before': first, 'after': second,
                                                       'different_pod_ids': True})
        for seed in (11, 22, 33):
            for mode in ('full', 'weights'):
                job(ssh, f'train-{mode}-{seed}', ['train', '--mode', mode, '--seed', str(seed)])
        print('All scheduled workloads completed', flush=True)
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
        save_json(OUT / 'execution-error.json', {'at_utc': utc_now(), 'error': error})
        print(error, flush=True)
    finally:
        if ssh:
            ssh.close()
        cleanup(api)
        current = state()
        current.update(finished=True, finished_at_utc=utc_now())
        record(current)
        pods, volumes = api.request('GET', 'pods'), api.request('GET', 'networkvolumes')
        account = api.graphql('{myself {clientBalance currentSpendPerHr}}')['myself']
        save_json(ROOT / 'private/followup-account-after.json', account)
        before = json.loads((ROOT / 'private/followup-account-before.json').read_text())
        gpu = sum(max(0, r['deleted_at_epoch'] - r['created_at_epoch']) / 3600 *
            r.get('total_hourly_usd', 0) for r in current['resources'] if r['kind'] == 'pod')
        volume_hours = sum((r['deleted_at_epoch'] - r['created_at_epoch']) / 3600
                          for r in current['resources'] if r['kind'] == 'volume')
        save_json(OUT / 'final-cleanup.json', {'at_utc': utc_now(), 'error': error,
            'account_pod_count': len(pods), 'account_network_volume_count': len(volumes),
            'account_current_spend_per_hour': account['currentSpendPerHr'],
            'pod_runtime_cost_estimate_usd': gpu,
            'network_volume_estimate_usd': volume_hours * 20 * .07 / 720,
            'observed_account_balance_decrease_usd': before['clientBalance'] - account['clientBalance'],
            'billing_finalized': False, 'all_owned_deleted': all(r.get('deleted') for r in current['resources'])})
        watchdog.wait(timeout=30)
    if error:
        raise RuntimeError(error)


if __name__ == '__main__':
    main()
