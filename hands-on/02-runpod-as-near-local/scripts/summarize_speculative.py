"""Summarize actual policies and a separately labelled calibrated event replay."""
import hashlib
import json
import random
import statistics
from pathlib import Path

from runpod_api import ROOT,save_json,utc_now
from speculative_policy import Policy

OUT=ROOT/'records/speculative'
NAMES={'keep':'상시 보존','delete':'즉시 반납','fixed20':'고정 20초','predict':'예측 TTL'}

def replay(arrivals,horizon,name,boot,service,deletion):
    """One FIFO worker. Arrival updates precede same-time idle eviction."""
    policy=Policy(name);t=0.;idx=0;state='idle';allocated=0.;queue=[];active=None
    deadline=float('inf');completion=float('inf');transition=float('inf');latencies=[];restarts=0
    while True:
        arrival=arrivals[idx] if idx<len(arrivals) else float('inf')
        event=min(arrival,completion,deadline if state=='idle' else float('inf'),transition,
                  horizon if t<horizon else float('inf'))
        if event==float('inf'):break
        assert event>=t-1e-8
        if state!='off':allocated+=event-t
        t=event
        if arrival==t:
            policy.arrival(t);queue.append(t);idx+=1
        if completion==t:
            latencies.append(t-active);active=None;completion=float('inf');state='idle';deadline=t+policy.ttl()
        if transition==t:
            transition=float('inf')
            if state=='deleting':state='off'
            elif state=='boot':state='idle';deadline=float('inf')
            else:raise AssertionError(state)
        if state=='off' and queue:
            state='boot';transition=t+boot;restarts+=1
        if state=='idle' and queue:
            active=queue.pop(0);state='busy';completion=t+service;deadline=float('inf')
        if state=='idle' and not queue and deadline<=t:
            state='deleting';transition=t+deletion;deadline=float('inf')
        if idx==len(arrivals) and not queue and active is None and t>=horizon:
            if state in ('idle','busy'):
                allocated+=deletion
            elif state=='deleting':allocated+=max(0,transition-t)
            break
    assert len(latencies)==len(arrivals)
    return {'allocated_seconds':allocated,'mean_latency_seconds':statistics.mean(latencies),
            'max_latency_seconds':max(latencies),'restarts':restarts}

def validate_engine():
    a=replay([0.,100.],120.,'keep',30.,1.,2.)
    b=replay([0.,100.],120.,'delete',30.,1.,2.)
    assert a['restarts']==0 and a['mean_latency_seconds']==1.
    assert b['restarts']==1 and b['max_latency_seconds']==31.
    assert a['allocated_seconds']==122. and b['allocated_seconds']==36.

def main():
    validate_engine()
    raw={name:json.loads((OUT/(name+'.json')).read_text()) for name in NAMES}
    pre=json.loads((OUT/'preregistered.json').read_text())
    assert all(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h for f,h in pre['source_sha256'].items())
    boot=[b['seconds'] for r in raw.values() for b in r['restarts']]
    deletion=[e['confirmed']-e['t'] for r in raw.values() for e in r['events'] if e['type'] in ('delete_intent','horizon_delete')]
    service=[r['complete']-r['start'] for r in raw['keep']['responses']]
    params={'boot_median_seconds':statistics.median(boot),'service_median_seconds':statistics.median(service),
        'delete_confirmation_median_seconds':statistics.median(deletion),'boot_samples':boot}
    actual={name:{'label':NAMES[name],'allocated_seconds':r['allocated_seconds'],'gpu_estimate_usd':r['gpu_estimate_usd'],
        'mean_latency_seconds':statistics.mean(x['latency_seconds'] for x in r['responses']),
        'max_latency_seconds':max(x['latency_seconds'] for x in r['responses']),
        'restarts':len(r['restarts']),'requests':len(r['responses']),'all_tokens_match':r['all_tokens_match']}
        for name,r in raw.items()}
    rng=random.Random(9182026);replayed={};traces={}
    for regime in ('bursty','sparse','alternating','irregular'):
        results={name:[] for name in NAMES};traces[regime]=[]
        for sample in range(100):
            gaps=[]
            for i in range(23):
                if regime=='bursty':gap=rng.uniform(5,12) if rng.random()<.8 else rng.uniform(60,100)
                elif regime=='sparse':gap=rng.uniform(70,110)
                elif regime=='alternating':gap=rng.uniform(5,10) if i%2==0 else rng.uniform(65,90)
                else:gap=rng.uniform(2,100)
                gaps.append(gap)
            arrivals=[0.]
            for gap in gaps:arrivals.append(arrivals[-1]+gap)
            horizon=arrivals[-1]+30;traces[regime].append(arrivals)
            # Same deterministic calibrated timings for each policy in a paired trace.
            for name in NAMES:
                results[name].append(replay(arrivals,horizon,name,params['boot_median_seconds'],
                    params['service_median_seconds'],params['delete_confirmation_median_seconds']))
        replayed[regime]={name:{key:statistics.mean(r[key] for r in values)
            for key in ('allocated_seconds','mean_latency_seconds','max_latency_seconds','restarts')}
            for name,values in results.items()}
    save_json(OUT/'replay-traces.json',{'seed':9182026,'synthetic_traces_per_regime':100,'arrivals':traces})
    calibration={name:replay(pre['trace'],pre['horizon'],name,params['boot_median_seconds'],
        params['service_median_seconds'],params['delete_confirmation_median_seconds']) for name in NAMES}
    cleanup=json.loads((OUT/'final-cleanup.json').read_text())
    ledger=json.loads((ROOT/'private/speculative-ledger.json').read_text())
    container=sum((r['deleted_at_epoch']-r['created_at_epoch'])*20*.10/(30*24*3600)
        for r in ledger['resources'] if r['kind']=='pod')
    volume=sum((r['deleted_at_epoch']-r['created_at_epoch'])*20*.07/(30*24*3600)
        for r in ledger['resources'] if r['kind']=='volume')
    result={'at_utc':utc_now(),'actual':actual,'order':pre['order'],'actual_trace':pre['trace'],'horizon':pre['horizon'],
        'calibration':params,'same_trace_replay':calibration,'synthetic_replay':replayed,
        'replay_is_not_additional_gpu_runs':True,'replay_analysis':'Exploratory post-design analysis, not a preregistered population test.','cleanup':cleanup,
        'container_disk_estimate_usd':container,'network_volume_continuous_estimate_usd':volume,
        'total_resource_estimate_usd':cleanup['gpu_lifetime_estimate_usd']+container+volume,
        'metric_note':'Policy allocation proxy integrates create intent to deletion confirmation, excluding common initial preparation. API/quote time can overestimate provider billing. Total costs use resource ledger lifetimes. One run per policy; no population tail or statistical superiority claim.'}
    save_json(ROOT/'reports/speculative-results.json',result)
    lines=['# GPU의 투기적 보존과 반납 — 결과','',
        '실제 RTX5090 정책 실행 4회와, 실측 시간으로 보정한 이산사건 재생을 구분한다. 사용자 트래픽은 아닌 고정 합성 trace다. 정책별 1회이며 통계적 우월성이나 일반적인 p95를 주장하지 않는다.','',
        '처음 모델이 준비된 상태에서 시작하고, 만료 뒤에는 실제 Pod를 삭제·재생성했다. 처음 준비한 비용은 정책 비교에서 공통 제외하되 전체 실험비에는 넣었다.','',
        '| 정책 | 생성 요청~삭제 확인 합계, 초 | 추정 비용, $ | 평균 응답, 초 | 최대 응답, 초 | 재기동 |',
        '|---|---:|---:|---:|---:|---:|']
    for name,r in actual.items():lines.append(f'| {r["label"]} | {r["allocated_seconds"]:.1f} | {r["gpu_estimate_usd"]:.5f} | {r["mean_latency_seconds"]:.2f} | {r["max_latency_seconds"]:.2f} | {r["restarts"]} |')
    lines+=['','과금 시간은 생성 요청부터 삭제 확인까지의 제어기 구간을 적분한 근사이며 API 지연을 포함해 공급자 청구보다 클 수 있다. 요청별 값과 삭제 확인 시간은 records/speculative/{policy}.json에 남겼다. 각 정책의 9개 출력 토큰 및 모델 전체 hash를 기존 고정 결과와 대조했다.','',
        '## 별도 재생','',
        f'보정값 중앙값: 재기동 {params["boot_median_seconds"]:.2f}초, 상주 요청 {params["service_median_seconds"]:.2f}초, 삭제 확인 {params["delete_confirmation_median_seconds"]:.2f}초. 이 값을 고정한 결정론 모델이다. 실제 네트워크 변동이나 재고 실패를 생성하지 않으므로 실제 서비스의 분포를 뜻하지 않는다.','',
        '각 24요청인 합성 trace를 네 분포에서 100개씩 생성했다. 같은 trace를 네 정책에 재생했다. 400개 요청 패턴, 1,600회 정책 재생이며 실제 GPU 1,600회 시험이 아니다. 재생 trace와 seed를 공개 원자료에 보존했다. 실제 정책과 도착열은 사전에 고정했으며, 이 재생은 결과 해석을 위한 탐색적 추가 분석이다.','',
        '| 분포 | 정책 | 평균 할당 근사시간, 초 | 평균 응답, 초 | trace별 최대 응답의 평균, 초 |',
        '|---|---|---:|---:|---:|']
    for regime,policies in replayed.items():
        for name,r in policies.items():lines.append(f'| {regime} | {NAMES[name]} | {r["allocated_seconds"]:.1f} | {r["mean_latency_seconds"]:.2f} | {r["max_latency_seconds"]:.2f} |')
    lines+=['','## 동일 trace의 재생과 실측 차이','',
        '모든 정책에 같은 재기동 중앙값을 적용한 재생이다. 실측을 보정해 대체한 값이 아니며 모형의 설명용 비교다. 실제 고정 20초의 재기동 두 번은 약 49.2초와 48.2초였고, 재생에서는 약 36.0초로 같게 두었다. 실측에서 예측 정책의 보유시간이 고정 정책보다 짧았던 관계가 이 모델에서는 반대로 나타난다.','',
        '| 정책 | 재생 보유 근사시간, 초 | 재생 평균 응답, 초 | 실제 평균 응답, 초 |',
        '|---|---:|---:|---:|---:|']
    for name,r in calibration.items():lines.append(f'| {NAMES[name]} | {r["allocated_seconds"]:.1f} | {r["mean_latency_seconds"]:.2f} | {actual[name]["mean_latency_seconds"]:.2f} |')
    lines+=['','## 비용과 정리','',
        f'전체 자원비용은 약 ${result["total_resource_estimate_usd"]:.4f} 추정. 초기 설치, 모델 준비, 첫 worker 기동 등 비교에서 제외한 공통 준비도 포함한다. 세금·에이전트 비용 제외, 확정 청구 아님. 볼륨의 연속시간 환산과 실제 시간 단위 과금 차이가 가능하다.',
        f'최종 Pod {cleanup["account_pod_count"]}개, network volume {cleanup["account_network_volume_count"]}개, 현재 시간당 사용액 {cleanup["current_spend_per_hour"]}.',
        '', '설계: docs/speculative-gpu-experiment.md. 정책은 미래 도착시각을 입력받지 않으며, 사전 소스 hash가 현재와 일치하는지 검증했다. CPU·Redis·LLM 캐시와의 연결은 재사용 예측의 비유이며, 동일한 구현·일관성·eviction 조건이라는 뜻은 아니다.']
    (ROOT/'reports/speculative-results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'actual':actual,'calibration':params,'total_resource_estimate_usd':result['total_resource_estimate_usd']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
