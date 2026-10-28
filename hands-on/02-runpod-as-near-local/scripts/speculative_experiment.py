"""Run four real Pod retention policies against a fixed open-loop synthetic trace."""
import base64
import hashlib
import json
import random
import shlex
import subprocess
import sys
import time
from pathlib import Path

import followup as core
from experiment import exec_ssh
from runpod_api import ROOT,Runpod,save_json,utc_now
from speculative_policy import Policy,ARRIVALS,HORIZON

OUT=ROOT/'records/speculative'
core.OUT=OUT;core.LEDGER=ROOT/'private/speculative-ledger.json';core.POD_TTL=480;core.BUDGET=3.

def start_worker(ssh,label):
    sftp=ssh.open_sftp();sftp.put(str(ROOT/'scripts/speculative_worker.py'),'/workspace/followup/speculative_worker.py');sftp.close()
    remote='/workspace/followup/runs/'+label
    exec_ssh(ssh,'mkdir -p '+remote+'; mkdir -p /tmp/speculative; tar -C /tmp/speculative -xf /workspace/followup/deps.tar',timeout=120)
    launch=('import subprocess,os;env=dict(os.environ,PYTHONPATH="/tmp/speculative/deps",'
        'HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",CUBLAS_WORKSPACE_CONFIG=":4096:8",OMP_NUM_THREADS="2");'
        f'log=open({(remote+"/worker.log")!r},"ab");'
        f'subprocess.Popen(["python","-u","/workspace/followup/speculative_worker.py","--run",{label!r}],'
        'env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)')
    encoded=base64.b64encode(launch.encode()).decode()
    exec_ssh(ssh,'python -c '+shlex.quote(f'import base64;exec(base64.b64decode("{encoded}"))'))
    before=time.monotonic()
    while time.monotonic()-before<180:
        content=exec_ssh(ssh,f'cat {remote}/ready.json 2>/dev/null || true')
        if content:
            ready=json.loads(content);save_json(OUT/(label+'-worker.json'),ready)
            expected=json.loads((ROOT/'records/story/cold/measurement.json').read_text())['hashes']
            assert ready['hashes']==expected,'Model file hashes changed'
            return ready
        time.sleep(.5)
    raise RuntimeError('Worker did not become ready: '+label)

def infer(ssh):
    command='import urllib.request; print(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8879/",data=b"{}"),timeout=60).read().decode())'
    return json.loads(exec_ssh(ssh,'python -c '+shlex.quote(command),timeout=70))

def run_policy(api,name):
    ssh,pod=core.create_pod(api,name+'-initial')
    start_worker(ssh,name+'-initial')
    policy=Policy(name);events=[];responses=[];queue=[];index=0;last_completion=None
    start=time.monotonic();allocated_at=0.;allocated=0.;boots=[];generation=0
    rates=[]
    initial=next(r for r in core.state()['resources'] if r.get('id')==pod)
    rate=initial['total_hourly_usd'];rates.append(rate)
    expected=json.loads((ROOT/'records/story/cold/measurement.json').read_text())['tokens']
    def now():return time.monotonic()-start
    def arrivals():
        nonlocal index
        current=now()
        while index<len(ARRIVALS) and ARRIVALS[index]<=current:
            policy.arrival(ARRIVALS[index]);queue.append(index)
            events.append({'t':ARRIVALS[index],'type':'arrival','request':index,'ewma':policy.ewma,'ttl':policy.ttl() if name!='keep' else None})
            index+=1
    try:
        while True:
            arrivals()
            if queue:
                if ssh is None:
                    generation+=1;before=now();label=f'{name}-restart-{generation}'
                    ssh,pod=core.create_pod(api,label);start_worker(ssh,label)
                    ready=now();allocated_at=before
                    rate=next(r for r in core.state()['resources'] if r.get('id')==pod)['total_hourly_usd'];rates.append(rate)
                    boots.append({'start':before,'ready':ready,'seconds':ready-before,'pod_id':pod})
                    events.append({'t':ready,'type':'ready','pod_id':pod});arrivals()
                req=queue.pop(0);begin=now();r=infer(ssh);end=now()
                assert r['tokens']==expected,'Output changed'
                responses.append({'request':req,'arrival':ARRIVALS[req],'start':begin,'complete':end,
                    'latency_seconds':end-ARRIVALS[req],'inference_seconds':r['inference_seconds'],'pod_id':pod})
                last_completion=end
                events.append({'t':end,'type':'response','request':req})
                continue
            if index==len(ARRIVALS) and now()>=HORIZON:break
            if ssh is not None and last_completion is not None and now()-last_completion>=policy.ttl():
                deletion=now();ssh.close();ssh=None;core.cleanup(api,'pod');done=now()
                allocated+=done-allocated_at;events.append({'t':deletion,'type':'delete_intent','confirmed':done,'ttl':policy.ttl()})
            time.sleep(.15)
        if ssh is not None:
            deletion=now();ssh.close();ssh=None;core.cleanup(api,'pod');done=now()
            allocated+=done-allocated_at;events.append({'t':deletion,'type':'horizon_delete','confirmed':done})
        assert len(responses)==len(ARRIVALS)
        # All creates in this run must retain the same rate for this integral.
        assert len(set(rates))==1
        result={'policy':name,'trace':ARRIVALS,'horizon':HORIZON,'initial_state':'model-ready',
            'policy_seconds':now(),'allocated_seconds':allocated,'hourly_usd':rate,
            'gpu_estimate_usd':allocated*rate/3600,'restarts':boots,'responses':responses,'events':events,
            'all_tokens_match':True,'initial_preparation_excluded_from_policy_metrics':True}
        save_json(OUT/(name+'.json'),result)
        print(name+': complete; restarts='+str(len(boots))+' allocated='+str(round(allocated,1))+'s',flush=True)
        return result
    finally:
        if ssh: ssh.close()
        core.cleanup(api,'pod')

def main():
    api=Runpod();assert not core.LEDGER.exists();assert not api.request('GET','pods');assert not api.request('GET','networkvolumes')
    pre=json.loads((ROOT/'records/story/preflight.json').read_text());save_json(OUT/'preflight-reference.json',pre)
    save_json(OUT/'frozen-config.json',json.loads((ROOT/'experiment.json').read_text(encoding='utf-8')))
    order=['keep','delete','fixed20','predict'];random.Random(20261024).shuffle(order)
    files=['docs/speculative-gpu-experiment.md','scripts/speculative_policy.py','scripts/speculative_worker.py','scripts/speculative_experiment.py','scripts/followup.py']
    save_json(OUT/'preregistered.json',{'at_utc':utc_now(),'source_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},'order':order,'trace':ARRIVALS,'horizon':HORIZON,'budget_usd':3.})
    now=time.time();name='rpspec-'+time.strftime('%Y%m%d-%H%M%S',time.gmtime())
    state={'experiment_id':name,'finished':False,'started_at_utc':utc_now(),'expires_at':now+7200,
        'selected':pre['selected'],'reference_5090':pre['reference_5090'],
        'resources':[{'kind':'volume','name':name+'-data','id':None,'created_at_epoch':now,'expires_at':now+7200}]}
    core.record(state)
    log=(ROOT/'private/speculative-watchdog.log').open('a')
    watchdog=subprocess.Popen([sys.executable,str(ROOT/'scripts/watchdog.py'),'--ledger','private/speculative-ledger.json'],cwd=ROOT,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    state['watchdog_pid']=watchdog.pid;core.record(state)
    error=None;ssh=None
    try:
        try:vol=api.request('POST','networkvolumes',{'name':name+'-data','size':20,'dataCenterId':pre['selected']['data_center']})
        except Exception:
            matches=[v for v in api.request('GET','networkvolumes') if v['name']==name+'-data'];assert len(matches)==1;vol=matches[0]
        state=core.state();state['volume_id']=vol['id'];state['resources'][0]['id']=vol['id'];core.record(state)
        ssh,_=core.create_pod(api,'prepare');before=time.monotonic()
        exec_ssh(ssh,'python -m pip install --no-compile --target /workspace/followup/deps transformers==4.57.1 huggingface-hub==0.36.0 safetensors==0.6.2 --quiet > /workspace/followup/install.log 2>&1',timeout=300)
        core.job(ssh,'prepare',['prepare'],timeout=300)
        exec_ssh(ssh,'tar -C /workspace/followup -cf /workspace/followup/deps.tar deps',timeout=120)
        save_json(OUT/'preparation.json',{'seconds_after_ssh':time.monotonic()-before})
        ssh.close();ssh=None;core.cleanup(api,'pod')
        for policy in order:run_policy(api,policy)
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc);save_json(OUT/'error.json',{'at_utc':utc_now(),'error':error});print(error,flush=True)
    finally:
        if ssh:ssh.close()
        core.cleanup(api);state=core.state();state.update(finished=True,finished_at_utc=utc_now());core.record(state)
        account=api.graphql('{myself{currentSpendPerHr}}')['myself']
        total=sum((r['deleted_at_epoch']-r['created_at_epoch'])*r.get('total_hourly_usd',0)/3600 for r in state['resources'] if r['kind']=='pod')
        save_json(OUT/'final-cleanup.json',{'at_utc':utc_now(),'error':error,'account_pod_count':len(api.request('GET','pods')),
            'account_network_volume_count':len(api.request('GET','networkvolumes')),'current_spend_per_hour':account['currentSpendPerHr'],
            'gpu_lifetime_estimate_usd':total,'all_owned_deleted':all(r.get('deleted') for r in state['resources']),'billing_finalized':False})
        watchdog.wait(timeout=30)
    if error:raise RuntimeError(error)

if __name__=='__main__':main()
