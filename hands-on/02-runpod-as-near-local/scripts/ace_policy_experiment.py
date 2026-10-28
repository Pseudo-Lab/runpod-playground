"""Real ACE-Step policies for an interactive generate/listen/try-again session."""
import hashlib
import json
import random
import shlex
import time

import ace_control as cloud
from runpod_api import ROOT,save_json,utc_now

GAPS=[5.,25.,180.]
TAIL=35.

class ThinkTimePolicy:
    def __init__(self,name):self.name=name;self.ewma=10.
    def observe(self,gap):self.ewma=.5*gap+.5*self.ewma
    def ttl(self):
        return {'keep':float('inf'),'delete':0.,'fixed20':20.,
                'predict':min(60.,max(5.,4*self.ewma))}[self.name]

def run_policy(api,name):
    label='policy-'+name;ssh,pod,ready=cloud.start_worker(api,label+'-initial')
    check=cloud.remote_file(ssh,'/workspace/ace/runs/cold/ready.json')
    assert check and check['hashes']==ready['hashes']
    command='import hashlib; print(hashlib.sha256(open("/workspace/ace/source/checkpoints/acestep-v15-turbo/model.safetensors","rb").read(65536)).hexdigest())'
    prefix=cloud.exec_ssh(ssh,'python -c '+shlex.quote(command)).strip()
    s3= json.loads((cloud.OUT/'s3-without-pod.json').read_text())
    assert prefix==s3['range_sha256']
    save_json(cloud.OUT/'s3-range-crosscheck.json',{'at_utc':utc_now(),'matches_new_pod_file_prefix':True,'sha256':prefix})
    policy=ThinkTimePolicy(name);start=time.monotonic();allocated_at=0.;allocated=0.;events=[];responses=[];boots=[];generation=0
    hourly=next(r['total_hourly_usd'] for r in cloud.core.state()['resources'] if r.get('id')==pod)
    def now():return time.monotonic()-start
    def delete(reason):
        nonlocal ssh,allocated
        before=now();ssh.close();ssh=None;cloud.core.cleanup(api,'pod');end=now()
        allocated+=end-allocated_at
        events.append({'type':reason,'t':before,'confirmed':end,'ttl':None if name=='keep' else policy.ttl()})
    try:
        last_completion=0.
        for i in range(4):
            target=0. if i==0 else last_completion+GAPS[i-1]
            if i:
                while now()<target:
                    if ssh is not None and now()-last_completion>=policy.ttl():delete('idle_delete')
                    time.sleep(.2)
                policy.observe(GAPS[i-1])
            events.append({'type':'request','t':target,'request':i,'ewma':policy.ewma,
                'ttl':None if name=='keep' else policy.ttl()})
            if ssh is None:
                generation+=1;before=now();allocated_at=before
                ssh,pod,ready=cloud.start_worker(api,label+f'-restart-{generation}')
                end=now();boots.append({'start':before,'ready':end,'seconds':end-before,'pod_id':pod})
                rate=next(r['total_hourly_usd'] for r in cloud.core.state()['resources'] if r.get('id')==pod)
                assert rate==hourly,'Rate changed within session'
                events.append({'type':'ready','t':end,'pod_id':pod})
            begin=now();music=cloud.request_music(ssh,label+f'-request-{i}')
            end=now();last_completion=end
            responses.append({'request':i,'arrival':target,'start':begin,'complete':end,'latency_seconds':end-target,
                'generation_seconds':music['generation_seconds'],'pod_id':pod,'music_record':label+f'-request-{i}'})
            events.append({'type':'response','t':end,'request':i})
            save_json(cloud.OUT/'policy'/name/'progress.json',{'responses':responses,'events':events,'boots':boots})
        finish_at=last_completion+TAIL
        while now()<finish_at:
            if ssh is not None and now()-last_completion>=policy.ttl():delete('idle_delete')
            time.sleep(.2)
        if ssh is not None:delete('session_end_delete')
        result={'policy':name,'initial_state':'model-ready','gaps_after_response_seconds':GAPS,'tail_seconds':TAIL,
            'session_seconds':now(),'allocated_seconds':allocated,'hourly_usd':hourly,'gpu_estimate_usd':allocated*hourly/3600,
            'responses':responses,'events':events,'restarts':boots,'request_count':4,
            'common_initial_setup_excluded_from_policy_metrics':True,'arrival_model':'closed-loop after response'}
        save_json(cloud.OUT/'policy'/name/'result.json',result)
        print(name+': session complete, '+str(len(boots))+' restarts',flush=True)
        return result
    finally:
        if ssh:ssh.close()
        cloud.core.cleanup(api,'pod')

def main():
    api=cloud.Runpod();assert not api.request('GET','pods')
    order=['keep','delete','fixed20','predict'];random.Random(20261025).shuffle(order)
    files=['scripts/ace_policy_experiment.py','scripts/ace_control.py','scripts/ace_worker.py']
    save_json(cloud.OUT/'policy-preregistered.json',{'at_utc':utc_now(),'order':order,'gaps':GAPS,'tail':TAIL,
        'source_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}})
    error=None
    try:
        for name in order:run_policy(api,name)
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc);save_json(cloud.OUT/'policy-error.json',{'at_utc':utc_now(),'error':error});raise
    finally:
        # Preserve every worker log before deleting the persistent volume.
        state=cloud.core.state();client=cloud.s3_client(state['selected']['data_center'])
        try:
            for page in client.get_paginator('list_objects_v2').paginate(Bucket=state['volume_id'],Prefix='ace/runs/'):
                for item in page.get('Contents',[]):
                    key=item['Key']
                    if key.endswith(('/job.log','/ready.json','/exit.json')):
                        target=cloud.OUT/'remote-logs'/key.removeprefix('ace/runs/')
                        target.parent.mkdir(parents=True,exist_ok=True)
                        client.download_file(state['volume_id'],key,str(target))
        finally:cloud.finish(api,error)

if __name__=='__main__':main()
