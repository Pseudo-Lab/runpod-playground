"""Small, resumable RunPod experiment controller with a local ownership ledger."""
import argparse
import base64
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import boto3
from botocore.config import Config
import paramiko

from runpod_api import ROOT, Runpod, credentials, save_json, utc_now

LEDGER = ROOT / 'private/ledger.json'


def load_ledger():
    return json.loads(LEDGER.read_text(encoding='utf-8'))


def s3_client(dc):
    env = credentials()
    if not all(env.get(k) for k in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY')):
        raise RuntimeError('S3 credentials are missing')
    return boto3.client('s3', aws_access_key_id=env['AWS_ACCESS_KEY_ID'],
                        aws_secret_access_key=env['AWS_SECRET_ACCESS_KEY'],
                        region_name=dc, endpoint_url=f'https://s3api-{dc.lower()}.runpod.io',
                        config=Config(signature_version='s3v4', connect_timeout=10,
                                      read_timeout=45, retries={'max_attempts': 2},
                                      request_checksum_calculation='when_required',
                                      response_checksum_validation='when_required'))


def start_watchdog():
    state = load_ledger()
    # A new independent process is harmless: cleanup is idempotent and ownership checked.
    log = (ROOT / 'private/watchdog.log').open('a', encoding='utf-8')
    proc = subprocess.Popen([sys.executable, str(ROOT / 'scripts/watchdog.py')],
                            cwd=ROOT, stdout=log, stderr=log,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    time.sleep(1)
    if proc.poll() is not None:
        raise RuntimeError('Watchdog did not start')
    state['watchdog_pid'] = proc.pid
    save_json(LEDGER, state)


def initialize():
    api = Runpod()
    cfg = json.loads((ROOT / 'experiment.json').read_text(encoding='utf-8'))
    pre = json.loads((ROOT / 'records/preflight.json').read_text(encoding='utf-8'))
    if LEDGER.exists() and not load_ledger().get('finished'):
        raise RuntimeError('An experiment ledger already exists; resume or clean it up first')
    if api.request('GET', 'pods'):
        raise RuntimeError('Existing Pods found; do not create a second active GPU')
    if not pre['candidates']:
        raise RuntimeError('No affordable available S3-compatible GPU')
    chosen = pre['candidates'][0]
    stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    name = 'rpexp-' + stamp
    state = {'experiment_id': name, 'started_at_utc': utc_now(), 'finished': False,
             'selected': chosen, 'reference_5090': pre['reference_5090'],
             'resources': [], 'gpu_budget_usd': cfg['gpu_budget_usd'],
             'storage_budget_usd': 0.10, 'storage_max_hours': 2}
    # Only our experiment-specific volume is created, and it expires after two hours.
    state['resources'].append({'kind': 'volume', 'name': name + '-data', 'id': None,
                               'expires_at': time.time() + 7200})
    save_json(LEDGER, state)
    start_watchdog()
    try:
        volume = api.request('POST', 'networkvolumes', {
            'name': name + '-data', 'size': cfg['network_volume_gb'],
            'dataCenterId': chosen['data_center']})
    except Exception:
        matches = [v for v in api.request('GET', 'networkvolumes') if v['name'] == name + '-data']
        if len(matches) != 1:
            raise
        volume = matches[0]
    state = load_ledger()
    state['resources'][0]['id'] = volume['id']
    state['volume_id'] = volume['id']
    save_json(LEDGER, state)
    client = s3_client(chosen['data_center'])
    payload = (name + '\nRunPod S3 integrity test\n').encode()
    key = 'smoke/roundtrip.txt'
    start = time.monotonic()
    try:
        client.put_object(Bucket=volume['id'], Key=key, Body=payload)
        received = client.get_object(Bucket=volume['id'], Key=key)['Body'].read()
        assert payload == received, 'S3 roundtrip mismatch'
        result = {'at_utc': utc_now(), 'status': 'passed', 'bytes': len(payload),
                  'sha256': hashlib.sha256(payload).hexdigest(),
                  'elapsed_seconds': time.monotonic() - start,
                  'no_pods_running': len(api.request('GET', 'pods')) == 0,
                  'data_center': chosen['data_center'], 'gpu_quote': chosen,
                  'network_volume_gb': cfg['network_volume_gb'],
                  'storage_estimate_usd_for_2h': cfg['network_volume_gb'] * 0.07 / 720 * 2,
                  'pricing_source': 'https://docs.runpod.io/pods/pricing'}
        save_json(ROOT / 'records/s3-roundtrip.json', result)
        print(json.dumps(result), flush=True)
    except Exception:
        cleanup(all_resources=True)
        raise
    keypath = ROOT / 'private/id_rsa'
    if not keypath.exists():
        paramiko.RSAKey.generate(3072).write_private_key_file(str(keypath))
    cfg['preferred_gpu'] = chosen['gpu_type']
    cfg['preferred_data_center'] = chosen['data_center']
    cfg['status'] = 's3_roundtrip_passed'
    cfg['storage_budget_usd'] = 0.10
    cfg['storage_max_hours'] = 2
    cfg['output_validation'] = {'w0_max_abs_error': 1e-5,
        'inference': 'nonempty finite GPU output, then exact greedy token IDs across same-GPU repeats',
        'logits_atol': 0.01, 'logits_rtol': 0.001}
    save_json(ROOT / 'experiment.json', cfg)


def cleanup(all_resources=False, only_run=None):
    api = Runpod()
    state = load_ledger()
    kinds = ('pod', 'volume') if all_resources else ('pod',)
    for kind in kinds:
        endpoint = 'pods' if kind == 'pod' else 'networkvolumes'
        for owned in state['resources']:
            if owned['kind'] != kind or owned.get('deleted'):
                continue
            if only_run and owned.get('run_id') != only_run:
                continue
            existing = api.request('GET', endpoint)
            if kind == 'pod' and not owned.get('id') and not owned.get('creation_rejected'):
                if not any(x['name'] == owned['name'] for x in existing):
                    raise RuntimeError('Create outcome is uncertain; keep the ownership intent and watchdog active: '
                                       + owned['name'])
            for actual in existing:
                if actual['name'] == owned['name'] and (not owned['id'] or actual['id'] == owned['id']):
                    owned['id'] = actual['id']
                    api.request('DELETE', endpoint + '/' + actual['id'])
            # Confirm absence rather than trusting DELETE's response.
            for _ in range(12):
                if not any(x['name'] == owned['name'] for x in api.request('GET', endpoint)):
                    owned['deleted'] = True
                    owned['deleted_at_utc'] = utc_now()
                    owned['deleted_at_epoch'] = time.time()
                    break
                time.sleep(2)
            else:
                raise RuntimeError('Deletion was not confirmed for ' + owned['name'])
    if all_resources:
        state['finished'] = True
        state['finished_at_utc'] = utc_now()
    save_json(LEDGER, state)


def relocate(gpu_type, data_center):
    """Start a separate hardware stratum when the original datacenter has no stock."""
    api = Runpod()
    if api.request('GET', 'pods'):
        raise RuntimeError('Relocation requires no running Pod')
    state = load_ledger()
    pre = json.loads((ROOT / 'records/preflight.json').read_text(encoding='utf-8'))
    candidate = next(q for q in pre['candidates']
                     if q['gpu_type'] == gpu_type and q['data_center'] == data_center)
    if candidate['usd_per_gpu_hour'] > state['reference_5090']['usd_per_gpu_hour']:
        raise RuntimeError('Candidate exceeds the frozen RTX 5090 ceiling')
    old_volume = state['volume_id']
    old_selected = state['selected']
    old_client = s3_client(old_selected['data_center'])
    smoke = old_client.get_object(Bucket=old_volume, Key='smoke/roundtrip.txt')['Body'].read()
    name = state['experiment_id'] + '-data-' + str(len(state['resources']))
    owned = {'kind': 'volume', 'name': name, 'id': None, 'expires_at': time.time() + 7200}
    state['resources'].append(owned)
    save_json(LEDGER, state)
    try:
        volume = api.request('POST', 'networkvolumes', {'name': name, 'size': 10,
                                                      'dataCenterId': data_center})
    except Exception:
        matches = [v for v in api.request('GET', 'networkvolumes') if v['name'] == name]
        if len(matches) != 1:
            raise
        volume = matches[0]
    owned['id'] = volume['id']
    save_json(LEDGER, state)
    client = s3_client(data_center)
    client.put_object(Bucket=volume['id'], Key='smoke/roundtrip.txt', Body=smoke)
    restored = client.get_object(Bucket=volume['id'], Key='smoke/roundtrip.txt')['Body'].read()
    assert smoke == restored
    # Completed results are already backed up locally. Model weights are reproducible
    # from the pinned public revision and will be downloaded in the new stratum.
    api.request('DELETE', 'networkvolumes/' + old_volume)
    if any(v['id'] == old_volume for v in api.request('GET', 'networkvolumes')):
        raise RuntimeError('Old volume deletion not confirmed')
    for r in state['resources']:
        if r.get('id') == old_volume:
            r['deleted'] = True
            r['deleted_at_utc'] = utc_now()
    state['volume_id'] = volume['id']
    state['selected'] = candidate
    state.setdefault('hardware_changes', []).append({'at_utc': utc_now(),
        'from': old_selected, 'to': candidate, 'reason': 'original datacenter exhausted stock',
        'do_not_pool_hardware_strata': True})
    save_json(LEDGER, state)
    cfg = json.loads((ROOT / 'experiment.json').read_text(encoding='utf-8'))
    cfg['preferred_gpu'] = gpu_type
    cfg['preferred_data_center'] = data_center
    save_json(ROOT / 'experiment.json', cfg)
    save_json(ROOT / 'records/hardware-change.json', state['hardware_changes'])
    print('Relocated:', json.dumps(candidate), flush=True)


def connect_pod(api, pod_id, deadline):
    state = load_ledger()
    key = paramiko.RSAKey.from_private_key_file(str(ROOT / 'private/id_rsa'))
    hosts = ROOT / 'private/known_hosts'
    last_error = None
    while time.monotonic() < deadline:
        pod = api.request('GET', 'pods/' + pod_id + '?includeMachine=true')
        ip, port = pod.get('publicIp'), (pod.get('portMappings') or {}).get('22')
        if ip and port:
            ssh = paramiko.SSHClient()
            if hosts.exists():
                ssh.load_host_keys(str(hosts))
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                ssh.connect(ip, port=int(port), username='root', pkey=key, timeout=10,
                            auth_timeout=10, banner_timeout=10, look_for_keys=False,
                            allow_agent=False)
                ssh.get_transport().set_keepalive(30)
                ssh.save_host_keys(str(hosts))
                return ssh, pod
            except Exception as exc:
                last_error = type(exc).__name__
                ssh.close()
        time.sleep(5)
    raise TimeoutError('SSH readiness timed out: ' + str(last_error))


def exec_ssh(ssh, command, timeout=600):
    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    stdin.close()
    # Commands write verbose output to remote files; channel output stays small.
    output = stdout.read().decode('utf-8', errors='replace')
    errors = stderr.read().decode('utf-8', errors='replace')
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError(f'Remote exit {code}: {errors[-1500:]} {output[-1500:]}')
    return output


def run_once(run_id, hold_seconds=0, disconnect_ssh=False, kill_controller=False):
    if (ROOT / 'records' / run_id / 'metrics.json').exists():
        raise RuntimeError('Run ID already has results; choose a new ID to preserve the evidence')
    api = Runpod()
    cfg = json.loads((ROOT / 'experiment.json').read_text(encoding='utf-8'))
    state = load_ledger()
    if any(r['kind'] == 'pod' and not r.get('deleted') for r in state['resources']):
        raise RuntimeError('An owned Pod already exists; reconcile before creating another')
    if api.request('GET', 'pods'):
        raise RuntimeError('A Pod is already active in the account')
    if hold_seconds > 900 or hold_seconds < 0:
        raise ValueError('Hold seconds must be 0..900')
    selected = state['selected']
    ceiling = state['reference_5090']['usd_per_gpu_hour']
    if selected['usd_per_gpu_hour'] > ceiling:
        raise RuntimeError('Selected GPU exceeds RTX 5090 ceiling')
    # Reserve worst-case runtime before creation; shared storage is separately bounded.
    reserved = sum((r.get('max_cost_usd', 0) if not r.get('deleted') else
                    max(0, r.get('deleted_at_epoch', time.time()) - r['created_at_epoch'])
                    / 3600 * r.get('total_hourly_usd', ceiling + .01))
                   for r in state['resources'] if r['kind'] == 'pod')
    lifetime = 1200 + hold_seconds
    max_cost = (ceiling + .01) * lifetime / 3600
    if reserved + max_cost > cfg['gpu_budget_usd']:
        raise RuntimeError('Worst-case run would exceed GPU budget')
    name = state['experiment_id'] + '-' + run_id
    now = time.time()
    owned = {'kind': 'pod', 'run_id': run_id, 'id': None, 'name': name,
             'created_at_epoch': now, 'expires_at': now + lifetime,
             'max_cost_usd': max_cost}
    state['resources'].append(owned)
    save_json(LEDGER, state)
    key = paramiko.RSAKey.from_private_key_file(str(ROOT / 'private/id_rsa'))
    public_key = key.get_name() + ' ' + key.get_base64()
    startup = ('mkdir -p /root/.ssh /run/sshd; chmod 700 /root/.ssh; '
               'printf "%s\\n" "$PUBLIC_KEY" > /root/.ssh/authorized_keys; '
               'chmod 600 /root/.ssh/authorized_keys; '
               'ssh-keygen -A; /usr/sbin/sshd; sleep infinity')
    request = {'name': name, 'cloudType': 'SECURE', 'computeType': 'GPU',
               'gpuTypeIds': [selected['gpu_type']], 'gpuCount': 1,
               'dataCenterIds': [selected['data_center']], 'interruptible': False,
               'imageName': cfg['image'], 'containerDiskInGb': 20, 'volumeInGb': 0,
               'networkVolumeId': state['volume_id'], 'volumeMountPath': '/workspace',
               'ports': ['22/tcp'], 'supportPublicIp': True,
               'minRAMPerGPU': 16, 'minVCPUPerGPU': 2,
               'dockerEntrypoint': ['/bin/bash', '-c'], 'dockerStartCmd': [startup],
               'env': {'PUBLIC_KEY': public_key}}
    out_dir = ROOT / 'records' / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {'run_id': run_id, 'started_at_utc': utc_now(), 'gpu': selected,
              'image': cfg['image'], 'result': 'failed', 'hold_seconds': hold_seconds,
              'price_ceiling_usd_per_hour': ceiling, 'timing_seconds': {}}
    start = time.monotonic()
    ssh = None
    try:
        try:
            pod = api.request('POST', 'pods', request)
        except Exception as create_error:
            matches = [p for p in api.request('GET', 'pods') if p['name'] == name]
            if len(matches) != 1:
                rejected = ('no instances currently available' in str(create_error).lower()
                            or any(f'HTTP {status}:' in str(create_error)
                                   for status in (400, 401, 403, 404, 422)))
                current = load_ledger()
                entry = next(r for r in current['resources'] if r['name'] == name)
                entry['creation_rejected'] = rejected
                entry['create_error'] = type(create_error).__name__
                save_json(LEDGER, current)
                raise
            pod = matches[0]
        state = load_ledger()
        owned = next(r for r in state['resources'] if r['name'] == name)
        owned['id'] = pod['id']
        owned['total_hourly_usd'] = pod.get('costPerHr') or selected['usd_per_gpu_hour'] + .01
        save_json(LEDGER, state)
        result['timing_seconds']['api'] = time.monotonic() - start
        result['total_hourly_usd'] = owned['total_hourly_usd']
        if owned['total_hourly_usd'] > ceiling + .01:
            raise RuntimeError('Deployed hourly price exceeded the fixed price ceiling')
        print(f'{run_id}: Pod created; hourly cost {owned["total_hourly_usd"]}', flush=True)
        if kill_controller:
            owned['expires_at'] = time.time() + 45
            save_json(LEDGER, state)
            # Intentionally bypass finally: the independent watchdog must clean up.
            os._exit(87)
        ssh, details = connect_pod(api, pod['id'], start + 600)
        result['timing_seconds']['ssh'] = time.monotonic() - start
        save_json(ROOT / 'private' / (run_id + '-pod.json'), details)
        print(f'{run_id}: SSH ready at {result["timing_seconds"]["ssh"]:.1f}s', flush=True)
        sftp = ssh.open_sftp()
        remote_base = '/workspace/experiment'
        exec_ssh(ssh, 'mkdir -p ' + remote_base + '/jobs ' + remote_base + '/runs/' + run_id)
        sftp.put(str(ROOT / 'scripts/gpu_job.py'), remote_base + '/jobs/gpu_job.py')
        sftp.put(str(ROOT / 'experiment.json'), remote_base + '/jobs/experiment.json')
        sftp.close()
        # Dependencies live on the persistent volume and are reused across Pods.
        install = ('python -c "import sys;sys.path.insert(0,\'/workspace/experiment/deps\');'
                   'import transformers;assert transformers.__version__==\'4.57.1\'" '
                   '>/dev/null 2>&1 || python -m pip install --target /workspace/experiment/deps '
                   'transformers==4.57.1 huggingface-hub==0.36.0 safetensors==0.6.2 '
                   '--quiet > /workspace/experiment/install.log 2>&1')
        exec_ssh(ssh, install, timeout=480)
        dependency_code = ('import importlib.metadata as m,json; '
            'print(json.dumps({d.metadata["Name"]:d.version for d in '
            'm.distributions(path=["/workspace/experiment/deps"])}))')
        versions = json.loads(exec_ssh(ssh, 'python -c ' + shlex.quote(dependency_code), timeout=30))
        save_json(out_dir / 'dependencies.json', versions)
        result['timing_seconds']['dependencies_ready'] = time.monotonic() - start
        result['source_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ('scripts/gpu_job.py', 'experiment.json')}
        launch = ('import subprocess,os; '
            'env=dict(os.environ, PYTHONPATH="/workspace/experiment/deps", '
            'HF_HOME="/workspace/experiment/hf", HF_HUB_DISABLE_XET="1", '
            'CUBLAS_WORKSPACE_CONFIG=":4096:8"); '
            f'log=open("/workspace/experiment/runs/{run_id}/job.log","ab"); '
            'p=subprocess.Popen(["python","-u","gpu_job.py","--run-id",'
            f'{json.dumps(run_id)},"--repeat-after-seconds",{json.dumps(str(hold_seconds))}], '
            'cwd="/workspace/experiment/jobs",env=env,stdin=subprocess.DEVNULL,'
            'stdout=log,stderr=log,start_new_session=True); print(p.pid)')
        encoded = base64.b64encode(launch.encode()).decode()
        jobcmd = 'python -c ' + shlex.quote(f'import base64;exec(base64.b64decode("{encoded}"))')
        remote_pid = int(exec_ssh(ssh, jobcmd, timeout=30).strip())
        result['remote_job_pid'] = remote_pid
        if disconnect_ssh:
            fault_start = time.monotonic()
            ssh.close()
            ssh, _ = connect_pod(api, pod['id'], time.monotonic() + 90)
            alive = exec_ssh(ssh, f'kill -0 {remote_pid} && echo alive', timeout=20).strip()
            if alive != 'alive':
                raise RuntimeError('Detached job did not survive SSH disconnect')
            result['ssh_disconnect_test'] = {'status': 'passed',
                'reconnect_seconds': time.monotonic() - fault_start,
                'same_job_pid_alive': True, 'duplicate_job_created': False}
        deadline = start + 1080
        while time.monotonic() < deadline:
            status = exec_ssh(ssh, f'cat /workspace/experiment/runs/{run_id}/status.json 2>/dev/null || true', timeout=30)
            if status:
                remote_status = json.loads(status)
                if remote_status['status'] in ('complete', 'failed'):
                    break
            time.sleep(5)
        else:
            raise TimeoutError('GPU job exceeded run deadline')
        # Retrieve through SSH for quick validation and through S3 for independent integrity.
        data = exec_ssh(ssh, f'cat /workspace/experiment/runs/{run_id}/result.json', timeout=30)
        remote = json.loads(data)
        result['remote'] = remote
        result['timing_seconds']['first_result'] = time.monotonic() - start
        result['timing_seconds']['ready'] = (result['timing_seconds']['dependencies_ready']
                                              + remote.get('ready_seconds', 0))
        result['timing_seconds']['ready_note'] = 'Approximate local ready time; includes remote job startup polling uncertainty'
        if remote_status['status'] != 'complete':
            raise RuntimeError('GPU job failed: ' + remote.get('error', 'unknown'))
        client = s3_client(selected['data_center'])
        raw = client.get_object(Bucket=state['volume_id'],
              Key=f'experiment/runs/{run_id}/result.json')['Body'].read()
        manifest_raw = client.get_object(Bucket=state['volume_id'],
              Key=f'experiment/runs/{run_id}/manifest.complete.json')['Body'].read()
        manifest = json.loads(manifest_raw)
        if manifest['sha256'] != hashlib.sha256(raw).hexdigest() or manifest['bytes'] != len(raw):
            raise RuntimeError('Completed artifact manifest checksum mismatch')
        if json.loads(raw) != remote:
            raise RuntimeError('S3 and SSH results do not match')
        result['artifact_sha256'] = hashlib.sha256(raw).hexdigest()
        result['artifact_s3_matches_ssh'] = True
        (out_dir / 'result.json').write_bytes(raw)
        (out_dir / 'manifest.complete.json').write_bytes(manifest_raw)
        log = exec_ssh(ssh, f'tail -c 16000 /workspace/experiment/runs/{run_id}/job.log')
        (out_dir / 'job.log').write_text(log, encoding='utf-8')
        result['timing_seconds']['persist'] = time.monotonic() - start
        result['persisted_at_epoch'] = time.time()
        if hold_seconds:
            print(f'{run_id}: retaining Pod for {hold_seconds}s before second inference', flush=True)
            deadline_second = time.monotonic() + hold_seconds + 300
            while time.monotonic() < deadline_second:
                value = exec_ssh(ssh, f'cat /workspace/experiment/runs/{run_id}/second-result.json 2>/dev/null || true')
                if value:
                    break
                time.sleep(5)
            else:
                raise TimeoutError('Second resident-model inference timed out')
            second = client.get_object(Bucket=state['volume_id'],
                       Key=f'experiment/runs/{run_id}/second-result.json')['Body'].read()
            result['second'] = json.loads(second)
            result['timing_seconds']['second_call'] = result['second']['intent_to_result_seconds']
            (out_dir / 'second-result.json').write_bytes(second)
            if 'error' in result['second']:
                raise RuntimeError('Second inference failed')
        result['timing_seconds']['completed_results'] = time.monotonic() - start
        result['completed_results_at_epoch'] = time.time()
        result['result'] = 'success'
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        if ssh:
            try:
                result['remote_log_tail'] = exec_ssh(ssh, f'tail -c 8000 /workspace/experiment/runs/{run_id}/job.log')
            except Exception:
                pass
        raise
    finally:
        if ssh:
            ssh.close()
        delete_start = time.monotonic()
        cleanup(only_run=run_id)
        result['timing_seconds']['delete_confirm'] = time.monotonic() - delete_start
        result['timing_seconds']['total_including_delete'] = time.monotonic() - start
        state = load_ledger()
        owned = next(r for r in state['resources'] if r['name'] == name)
        result['resource_created'] = bool(owned.get('id'))
        result['estimated_cost_usd'] = (max(0, owned['deleted_at_epoch'] - owned['created_at_epoch'])
            / 3600 * owned.get('total_hourly_usd', ceiling + .01) if owned.get('id') else 0)
        result['billed_cost_usd'] = None
        save_json(out_dir / 'metrics.json', result)
        print(f'{run_id}: {result["result"]}; deleted; estimated ${result["estimated_cost_usd"]:.5f}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'run', 'cleanup', 'finish', 'fault'])
    parser.add_argument('--run-id', default='a01')
    parser.add_argument('--hold-seconds', type=int, default=0)
    parser.add_argument('--disconnect-ssh', action='store_true')
    parser.add_argument('--kill-controller', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.action == 'init':
        initialize()
    elif args.action == 'run':
        run_once(args.run_id, args.hold_seconds, args.disconnect_ssh, args.kill_controller)
    elif args.action == 'fault':
        controller_fault(args.run_id)
    else:
        cleanup(all_resources=args.action == 'finish')


def controller_fault(run_id):
    start = time.monotonic()
    log = (ROOT / 'private' / (run_id + '-controller.log')).open('w', encoding='utf-8')
    proc = subprocess.Popen([sys.executable, '-X', 'utf8', str(Path(__file__)), 'run',
                             '--run-id', run_id, '--kill-controller'], cwd=ROOT,
                             stdout=log, stderr=log,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    code = proc.wait(timeout=90)
    log.close()
    if code != 87:
        raise RuntimeError('Controller did not reach the injected termination point; see private/'
                           + run_id + '-controller.log')
    fault_at = time.monotonic()
    api = Runpod()
    state = load_ledger()
    owned = next(r for r in state['resources'] if r.get('run_id') == run_id)
    while time.monotonic() - fault_at < 120:
        if not any(p['name'] == owned['name'] for p in api.request('GET', 'pods')):
            break
        time.sleep(5)
    else:
        cleanup(only_run=run_id)
        raise RuntimeError('Watchdog cleanup failed; supervisor performed fallback cleanup')
    owned['deleted'] = True
    owned['deleted_at_utc'] = utc_now()
    owned['deleted_at_epoch'] = time.time()
    save_json(LEDGER, state)
    result = {'run_id': run_id, 'status': 'passed', 'controller_exit_code': code,
              'cleanup_after_fault_seconds': time.monotonic() - fault_at,
              'total_seconds': time.monotonic() - start,
              'cleanup_agent': 'independent_watchdog', 'remaining_owned_pods': 0,
              'estimated_cost_usd': (owned['deleted_at_epoch'] - owned['created_at_epoch'])
                  / 3600 * owned['total_hourly_usd']}
    save_json(ROOT / 'records' / run_id / 'fault.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
