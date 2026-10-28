"""Bounded ACE-Step resource ownership, remote jobs, and verified audio retrieval."""
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

import followup as core
from experiment import exec_ssh,s3_client
from runpod_api import ROOT,Runpod,save_json,utc_now

OUT=ROOT/'records/ace-step';BASE='/workspace/ace'
core.OUT=OUT;core.LEDGER=ROOT/'private/ace-ledger.json';core.POD_TTL=2400;core.BUDGET=6.

def remote_file(ssh,path):
    raw=exec_ssh(ssh,'cat '+shlex.quote(path)+' 2>/dev/null || true')
    return json.loads(raw) if raw else None

def collect(ssh,remote,local):
    local=Path(local);local.parent.mkdir(parents=True,exist_ok=True)
    sftp=ssh.open_sftp()
    try:sftp.get(remote,str(local))
    finally:sftp.close()

def upload_code(ssh):
    exec_ssh(ssh,'mkdir -p '+BASE+'/runs')
    sftp=ssh.open_sftp()
    for name in ('ace_worker.py','ace_bootstrap.py'):
        sftp.put(str(ROOT/'scripts'/name),BASE+'/'+name)
    sftp.close()

def detached(ssh,argv,label,env=None):
    remote=BASE+'/runs/'+label;exec_ssh(ssh,'mkdir -p '+shlex.quote(remote))
    environment=dict(ACESTEP_PROJECT_ROOT=BASE+'/source',ACESTEP_CHECKPOINTS_DIR=BASE+'/source/checkpoints',
        HF_HOME=BASE+'/hf',HF_HUB_DISABLE_XET='1',UV_CACHE_DIR=BASE+'/uv-cache',
        PYTHONPATH=BASE+'/source',OMP_NUM_THREADS='4',TOKENIZERS_PARALLELISM='false')
    if env:environment.update(env)
    wrapper=('import subprocess,json,pathlib,os,time;'
        f'p=pathlib.Path({remote!r});env=dict(os.environ);env.update({environment!r});t=time.monotonic();'
        f'r=subprocess.run({argv!r},env=env,cwd={BASE+"/source"!r});'
        '(p/"exit.json").write_text(json.dumps({"returncode":r.returncode,"seconds":time.monotonic()-t}))')
    launch=('import subprocess;'
        f'log=open({remote+"/job.log"!r},"ab");'
        f'p=subprocess.Popen(["python","-u","-c",{wrapper!r}],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True);print(p.pid)')
    encoded=base64.b64encode(launch.encode()).decode()
    return int(exec_ssh(ssh,'python -c '+shlex.quote(f'import base64;exec(base64.b64decode("{encoded}"))')).strip())

def wait_job(ssh,label,timeout):
    start=time.monotonic();remote=BASE+'/runs/'+label
    while time.monotonic()-start<timeout:
        value=remote_file(ssh,remote+'/exit.json')
        if value:
            collect(ssh,remote+'/job.log',OUT/label/'job.log');save_json(OUT/label/'exit.json',value)
            assert value['returncode']==0,'Remote job failed: '+label
            return value
        time.sleep(2)
    collect(ssh,remote+'/job.log',OUT/label/'job.log')
    raise TimeoutError(label)

def start_worker(api,label,once=False):
    before=time.monotonic();ssh,pod=core.create_pod(api,label);upload_code(ssh)
    argv=[BASE+'/source/.venv/bin/python','-u',BASE+'/ace_worker.py','--run',label]+(['--once'] if once else [])
    detached(ssh,argv,label,{'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
    if once:
        wait_job(ssh,label,1000)
    else:
        start=time.monotonic()
        while time.monotonic()-start<900:
            ready=remote_file(ssh,BASE+'/runs/'+label+'/ready.json')
            if ready:break
            ended=remote_file(ssh,BASE+'/runs/'+label+'/exit.json')
            if ended:
                collect(ssh,BASE+'/runs/'+label+'/job.log',OUT/label/'job.log')
                raise RuntimeError('Worker exited: '+label)
            time.sleep(1)
        else:raise TimeoutError('Worker ready: '+label)
    ready=remote_file(ssh,BASE+'/runs/'+label+'/ready.json');assert ready
    baseline=OUT/'weight-hashes.json'
    if baseline.exists():assert ready['hashes']==json.loads(baseline.read_text()),'Weight mismatch'
    else:save_json(baseline,ready['hashes'])
    ready.update(request_to_ready_seconds=time.monotonic()-before,pod_id=pod)
    save_json(OUT/label/'ready.json',ready)
    print(label+': worker ready',flush=True)
    return ssh,pod,ready

def fetch_music(ssh,result,label):
    target=ROOT/'private/ace-audio'/label/Path(result['path']).name
    collect(ssh,result['path'],target)
    assert target.stat().st_size==result['bytes']
    assert hashlib.sha256(target.read_bytes()).hexdigest()==result['sha256']
    result=dict(result,local_audio_path=str(target.relative_to(ROOT)).replace('\\','/'),local_file_hash_verified=True)
    save_json(OUT/label/'music.json',result)
    return result

def request_music(ssh,label):
    before=time.monotonic()
    command=('import urllib.request,json;req=urllib.request.Request("http://127.0.0.1:8881/",'
        f'data=json.dumps({{"label":{label!r}}}).encode());print(urllib.request.urlopen(req,timeout=600).read().decode())')
    result=json.loads(exec_ssh(ssh,'python -c '+shlex.quote(command),timeout=630))
    result=fetch_music(ssh,result,label);result['request_to_collected_seconds']=time.monotonic()-before
    save_json(OUT/label/'music.json',result)
    print(label+': music recovered, '+str(round(result['request_to_collected_seconds'],1))+'s',flush=True)
    return result

def storage_check(api):
    assert not api.request('GET','pods')
    state=core.state();s3=s3_client(state['selected']['data_center']);payload=b'ACE-Step models persist without a GPU'
    key='ace/marker.txt';s3.put_object(Bucket=state['volume_id'],Key=key,Body=payload)
    assert s3.get_object(Bucket=state['volume_id'],Key=key)['Body'].read()==payload
    weights='ace/source/checkpoints/acestep-v15-turbo/model.safetensors'
    head=s3.head_object(Bucket=state['volume_id'],Key=weights)
    part=s3.get_object(Bucket=state['volume_id'],Key=weights,Range='bytes=0-65535')['Body'].read()
    save_json(OUT/'s3-without-pod.json',{'at_utc':utc_now(),'pod_count':0,'marker_roundtrip':True,
        'model_bytes':head['ContentLength'],'range_bytes':len(part),'range_sha256':hashlib.sha256(part).hexdigest()})

def finish(api,error=None):
    core.cleanup(api);state=core.state();state.update(finished=True,finished_at_utc=utc_now());core.record(state)
    total=sum((r['deleted_at_epoch']-r['created_at_epoch'])*r.get('total_hourly_usd',0)/3600 for r in state['resources'] if r['kind']=='pod')
    account=api.graphql('{myself{currentSpendPerHr}}')['myself']
    save_json(OUT/'final-cleanup.json',{'at_utc':utc_now(),'error':error,'account_pod_count':len(api.request('GET','pods')),
        'account_network_volume_count':len(api.request('GET','networkvolumes')),'current_spend_per_hour':account['currentSpendPerHr'],
        'gpu_lifetime_estimate_usd':total,'all_owned_deleted':all(r.get('deleted') for r in state['resources']),'billing_finalized':False})

def prepare():
    api=Runpod();assert not core.LEDGER.exists();pre=json.loads((OUT/'preflight.json').read_text())
    assert not api.request('GET','pods');assert not api.request('GET','networkvolumes')
    cfg=json.loads((ROOT/'experiment.json').read_text(encoding='utf-8'));save_json(OUT/'frozen-config.json',cfg)
    files=['docs/ace-step-experiment.md','scripts/ace_worker.py','scripts/ace_bootstrap.py','scripts/ace_control.py']
    save_json(OUT/'preregistered.json',{'at_utc':utc_now(),'source_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},'budget_usd':6,'source_commit':'ca1e85fe9430179831e6bc6be790c332190a3866'})
    now=time.time();name='rpace-'+time.strftime('%Y%m%d-%H%M%S',time.gmtime())
    state={'experiment_id':name,'finished':False,'started_at_utc':utc_now(),'expires_at':now+14400,
        'selected':pre['selected'],'reference_5090':pre['reference_5090'],'resources':[
            {'kind':'volume','name':name+'-data','id':None,'created_at_epoch':now,'expires_at':now+14400,'size_gb':60}]}
    core.record(state)
    log=(ROOT/'private/ace-watchdog.log').open('a')
    wd=subprocess.Popen([sys.executable,str(ROOT/'scripts/watchdog.py'),'--ledger','private/ace-ledger.json'],cwd=ROOT,
        stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    state['watchdog_pid']=wd.pid;core.record(state);ssh=None
    try:
        try:vol=api.request('POST','networkvolumes',{'name':name+'-data','size':60,'dataCenterId':pre['selected']['data_center']})
        except Exception:
            matches=[v for v in api.request('GET','networkvolumes') if v['name']==name+'-data'];assert len(matches)==1;vol=matches[0]
        state=core.state();state['volume_id']=vol['id'];state['resources'][0]['id']=vol['id'];core.record(state)
        start=time.monotonic();ssh,pod=core.create_pod(api,'cold');upload_code(ssh)
        sftp=ssh.open_sftp();sftp.put(str(ROOT/'private/ace-source.tar'),BASE+'/source.tar');sftp.close()
        exec_ssh(ssh,'mkdir -p '+BASE+'/source; tar -C '+BASE+'/source -xf '+BASE+'/source.tar',timeout=120)
        detached(ssh,['python','-u',BASE+'/ace_bootstrap.py'],'bootstrap');wait_job(ssh,'bootstrap',1600)
        collect(ssh,BASE+'/bootstrap.json',OUT/'bootstrap.json');collect(ssh,BASE+'/environment.txt',OUT/'environment.txt')
        # Keep the initial Pod to include all first preparation in one continuous clock.
        label='cold';detached(ssh,[BASE+'/source/.venv/bin/python','-u',BASE+'/ace_worker.py','--run',label,'--once'],label,
            {'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
        wait_job(ssh,label,1000)
        ready=remote_file(ssh,BASE+'/runs/cold/ready.json');save_json(OUT/'cold/ready.json',ready);save_json(OUT/'weight-hashes.json',ready['hashes'])
        result=fetch_music(ssh,remote_file(ssh,BASE+'/runs/cold/music.json'),'cold')
        result.update(intent_to_collected_seconds=time.monotonic()-start,pod_id=pod)
        save_json(OUT/'cold/measurement.json',result)
        print('cold: first music recovered after '+str(round(result['intent_to_collected_seconds'],1))+'s',flush=True)
        ssh.close();ssh=None;core.cleanup(api,'pod');storage_check(api)
    except Exception as exc:
        save_json(OUT/'prepare-error.json',{'at_utc':utc_now(),'error':type(exc).__name__+': '+str(exc)})
        raise
    finally:
        if ssh:ssh.close()
        core.cleanup(api,'pod')

def repeats():
    api=Runpod()
    try:
        for i in range(1,4):
            label=f'cached-{i}';started=time.monotonic();ssh,pod,ready=start_worker(api,label)
            try:
                result=request_music(ssh,label);result.update(intent_to_collected_seconds=time.monotonic()-started,pod_id=pod)
                save_json(OUT/label/'measurement.json',result)
                if i==1:
                    for j in range(1,4):request_music(ssh,f'resident-{j}')
            finally:ssh.close();core.cleanup(api,'pod')
        storage_check(api)
    except Exception as exc:
        save_json(OUT/'repeat-error.json',{'at_utc':utc_now(),'error':type(exc).__name__+': '+str(exc)})
        core.cleanup(api,'pod');raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','repeat','finish']);a=p.parse_args()
    if a.phase=='prepare':prepare()
    elif a.phase=='repeat':repeats()
    else:finish(Runpod())
