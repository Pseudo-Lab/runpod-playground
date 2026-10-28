"""Supplement the purchase-vs-rental story with bounded real GPU observations."""
import base64
import hashlib
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

import followup as core
from experiment import exec_ssh, s3_client
from runpod_api import ROOT, Runpod, save_json, utc_now

OUT = ROOT / 'records/story'
core.OUT = OUT
core.LEDGER = ROOT / 'private/story-ledger.json'
core.POD_TTL = 1800
core.BUDGET = 6.


def run_job(ssh, mode, run_id):
    remote = '/workspace/followup/runs/' + run_id
    exec_ssh(ssh, 'mkdir -p ' + remote)
    wrapper = ('import subprocess,json,pathlib,time; '
        f'p=pathlib.Path({remote!r});t=time.monotonic();'
        f'r=subprocess.run(["python","-u","/workspace/followup/story_gpu.py","--mode",{mode!r},"--run-id",{run_id!r}]);'
        '(p/"exit.tmp").write_text(json.dumps({"returncode":r.returncode,"wall_seconds":time.monotonic()-t}));'
        '(p/"exit.tmp").replace(p/"exit.json")')
    launch = ('import subprocess,os;env=dict(os.environ,PYTHONPATH="/workspace/followup",'
        'HF_HOME="/workspace/followup/hf",HF_HUB_DISABLE_XET="1",CUBLAS_WORKSPACE_CONFIG=":4096:8",OMP_NUM_THREADS="2");'
        f'log=open({(remote+"/job.log")!r},"ab");'
        f'subprocess.Popen(["python","-c",{wrapper!r}],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)')
    encoded = base64.b64encode(launch.encode()).decode()
    before = time.monotonic()
    exec_ssh(ssh, 'python -c ' + shlex.quote(f'import base64;exec(base64.b64decode("{encoded}"))'))
    ended = None
    while time.monotonic() - before < 600:
        text = exec_ssh(ssh, f'cat {remote}/exit.json 2>/dev/null || true')
        if text:
            ended = json.loads(text)
            break
        time.sleep(2)
    local = OUT / run_id
    local.mkdir(parents=True, exist_ok=True)
    sftp = ssh.open_sftp()
    for name in ('result.json', 'exit.json', 'job.log'):
        try:
            sftp.get(remote + '/' + name, str(local / name))
        except FileNotFoundError:
            (local / name).unlink(missing_ok=True)
    sftp.close()
    assert ended and ended['returncode'] == 0, 'Remote job failed: ' + run_id
    result = json.loads((local / 'result.json').read_text(encoding='utf-8'))
    print(run_id + ': complete, remote ' + str(round(result['remote_total_seconds'], 2)) + 's', flush=True)
    return result


def no_pod_storage_check(api, model=False):
    assert not api.request('GET', 'pods')
    state = core.state()
    client = s3_client(state['selected']['data_center'])
    payload = (state['experiment_id'] + ': persisted without a GPU').encode()
    client.put_object(Bucket=state['volume_id'], Key='followup/story-marker.txt', Body=payload)
    got = client.get_object(Bucket=state['volume_id'], Key='followup/story-marker.txt')['Body'].read()
    assert got == payload
    result = {'at_utc': utc_now(), 'pod_count': 0, 'marker': payload.decode(),
              'marker_sha256': hashlib.sha256(got).hexdigest()}
    if model:
        metadata = json.loads((OUT / 'model.json').read_text())
        head = client.head_object(Bucket=state['volume_id'], Key=metadata['s3_key'])
        part = client.get_object(Bucket=state['volume_id'], Key=metadata['s3_key'], Range='bytes=0-65535')['Body'].read()
        assert head['ContentLength'] == metadata['bytes']
        assert hashlib.sha256(part).hexdigest() == metadata['first64k_sha256']
        result.update(model_bytes=head['ContentLength'], range_bytes=len(part), model_range_hash_matches=True)
    save_json(OUT / ('s3-without-pod-' + ('model' if model else 'initial') + '.json'), result)
    return payload.decode()


def main():
    api = Runpod()
    assert not core.LEDGER.exists(), 'Preserve existing story ledger'
    pre = json.loads((OUT / 'preflight.json').read_text())
    cfg = json.loads((ROOT / 'experiment.json').read_text(encoding='utf-8'))
    save_json(OUT / 'frozen-config.json', cfg)
    files = ['scripts/story_experiment.py', 'scripts/story_gpu.py', 'scripts/followup.py',
             'scripts/followup_gpu.py', 'docs/story-experiment.md']
    save_json(OUT / 'preregistered.json', {'at_utc': utc_now(), 'source_sha256': {
        f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in files},
        'budget_usd': 6, 'cold_samples': 1, 'cached_fresh_pods': 3})
    now = time.time()
    name = 'rpstory-' + time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    state = {'experiment_id': name, 'finished': False, 'started_at_utc': utc_now(),
        'expires_at': now + 14400, 'selected': pre['selected'], 'reference_5090': pre['reference_5090'],
        'resources': [{'kind': 'volume', 'name': name + '-data', 'id': None,
                       'created_at_epoch': now, 'expires_at': now + 14400}]}
    core.record(state)
    log = (ROOT / 'private/story-watchdog.log').open('a')
    watchdog = subprocess.Popen([sys.executable, str(ROOT / 'scripts/watchdog.py'), '--ledger',
        'private/story-ledger.json'], cwd=ROOT, stdout=log, stderr=log,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    state['watchdog_pid'] = watchdog.pid
    core.record(state)
    ssh, error = None, None
    measurements = []
    try:
        try:
            volume = api.request('POST', 'networkvolumes', {'name': name + '-data', 'size': 20,
                                                          'dataCenterId': pre['selected']['data_center']})
        except Exception:
            matches = [v for v in api.request('GET', 'networkvolumes') if v['name'] == name + '-data']
            assert len(matches) == 1
            volume = matches[0]
        state = core.state();state['volume_id'] = volume['id'];state['resources'][0]['id'] = volume['id'];core.record(state)
        marker = no_pod_storage_check(api)
        for i, mode in enumerate(('cold', 'cached', 'cached', 'cached')):
            label = 'cold' if i == 0 else 'cached-' + str(i)
            started = time.monotonic()
            ssh, pod_id = core.create_pod(api, label)
            sftp = ssh.open_sftp();sftp.put(str(ROOT / 'scripts/story_gpu.py'), '/workspace/followup/story_gpu.py');sftp.close()
            install, package = 0., 0.
            if i == 0:
                before = time.monotonic()
                exec_ssh(ssh, 'python -m pip install --no-compile --target /workspace/followup/deps '
                    'transformers==4.57.1 huggingface-hub==0.36.0 safetensors==0.6.2 '
                    '--quiet > /workspace/followup/install.log 2>&1', timeout=480)
                install = time.monotonic() - before
                before = time.monotonic()
                exec_ssh(ssh, 'tar -C /workspace/followup -cf /workspace/followup/deps.tar deps', timeout=360)
                package = time.monotonic() - before
            result = run_job(ssh, mode, label)
            elapsed = time.monotonic() - started
            assert result['persisted_marker'] == marker
            result.update(run_id=label, intent_to_collected_result_seconds=elapsed,
                          install_seconds=install, archive_build_seconds=package, pod_id=pod_id)
            save_json(OUT / label / 'measurement.json', result)
            if measurements:
                assert result['tokens'] == measurements[0]['tokens']
                assert result['hashes'] == measurements[0]['hashes']
            measurements.append(result)
            if i == 0:
                sftp = ssh.open_sftp();sftp.get('/workspace/followup/story-model.json', str(OUT / 'model.json'));sftp.close()
            ssh.close();ssh = None
            core.cleanup(api, 'pod')
            if i == 0:
                marker = no_pod_storage_check(api, model=True)
            print(label + ': request to result ' + str(round(elapsed, 2)) + 's, Pod deleted', flush=True)
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
        save_json(OUT / 'error.json', {'at_utc': utc_now(), 'error': error})
        print(error, flush=True)
    finally:
        if ssh: ssh.close()
        core.cleanup(api)
        state = core.state();state.update(finished=True, finished_at_utc=utc_now());core.record(state)
        pods, volumes = api.request('GET', 'pods'), api.request('GET', 'networkvolumes')
        account = api.graphql('{myself{clientBalance currentSpendPerHr}}')['myself']
        save_json(ROOT / 'private/story-account-after.json', account)
        cost = sum((r['deleted_at_epoch'] - r['created_at_epoch']) / 3600 * r.get('total_hourly_usd', 0)
                   for r in state['resources'] if r['kind'] == 'pod')
        save_json(OUT / 'final-cleanup.json', {'at_utc': utc_now(), 'error': error,
            'account_pod_count': len(pods), 'account_network_volume_count': len(volumes),
            'current_spend_per_hour': account['currentSpendPerHr'], 'pod_estimate_usd': cost,
            'all_owned_deleted': all(r.get('deleted') for r in state['resources']), 'billing_finalized': False})
        watchdog.wait(timeout=30)
    if error: raise RuntimeError(error)


if __name__ == '__main__': main()
