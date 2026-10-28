"""Validate ACE-Step observations, retain listenable evidence, and report costs."""
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

from runpod_api import ROOT,save_json,utc_now

sys.path.insert(0,str(ROOT/'private/ace-tools'))
OUT=ROOT/'records/ace-step'
NAMES={'keep':'상시 보존','delete':'즉시 반납','fixed20':'고정 20초','predict':'예측 TTL'}

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    import numpy as np
    import soundfile as sf
    import imageio_ffmpeg
    pre=read(OUT/'preregistered.json');policy_pre=read(OUT/'policy-preregistered.json')
    for manifest in (pre,policy_pre):
        assert all(sha(ROOT/f)==h for f,h in manifest['source_sha256'].items()),'Preregistered source changed'
    cold=read(OUT/'cold/measurement.json')
    cached=[read(OUT/f'cached-{i}/measurement.json') for i in (1,2,3)]
    resident=[read(OUT/f'resident-{i}/music.json') for i in (1,2,3)]
    ready=[read(OUT/f'{label}/ready.json') for label in ('cold','cached-1','cached-2','cached-3')]
    weights=read(OUT/'weight-hashes.json');catalogs=[read(OUT/'Ace-Step1.5-catalog.json'),read(OUT/'acestep-5Hz-lm-4B-catalog.json')]
    expected={}
    for i,catalog in enumerate(catalogs):
        for f in catalog['siblings']:
            key=f['rfilename'] if i==0 else 'acestep-5Hz-lm-4B/'+f['rfilename']
            if key in weights:
                expected[key]=f['lfs']['sha256']
    assert weights==expected,'Weights do not match pinned Hugging Face blobs'
    assert all(x['hashes']==weights for x in ready)
    def validate_audio(record):
        path=ROOT/record['local_audio_path']
        assert sha(path)==record['sha256']
        samples,sr=sf.read(path,always_2d=True,dtype='float32')
        assert np.isfinite(samples).all() and 58<=len(samples)/sr<=62 and samples.shape[1]==2
        assert hashlib.sha256(samples.tobytes()).hexdigest()==record['pcm_sha256']
        assert float(np.sqrt(np.mean(samples.astype('float64')**2)))>1e-5
        return samples,sr
    for record in resident:validate_audio(record)
    weight_bytes=sum(f['size'] for i,c in enumerate(catalogs) for f in c['siblings']
        if (f['rfilename'] if i==0 else 'acestep-5Hz-lm-4B/'+f['rfilename']) in weights)
    comparisons=[];baseline,_=sf.read(ROOT/cold['local_audio_path'],always_2d=True,dtype='float32')
    for label,r in zip(('cold','cached-1','cached-2','cached-3'),[cold]+cached):
        data,sr=validate_audio(r)
        comparisons.append({'label':label,'file_sha256':r['sha256'],'pcm_sha256':r['pcm_sha256'],
            'same_pcm_as_cold':r['pcm_sha256']==cold['pcm_sha256'],
            'pcm_rmse_vs_cold':float(np.sqrt(np.mean((data.astype('float64')-baseline.astype('float64'))**2))) if data.shape==baseline.shape else None,
            'duration_seconds':len(data)/sr,'sample_rate':sr,'channels':data.shape[1],'rms':r['rms'],'peak':r['peak']})
    audio_dir=ROOT/'reports/audio/ace-step';audio_dir.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/cached[0]['local_audio_path'],audio_dir/'ace-step-60s.flac')
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg,'-y','-i',str(audio_dir/'ace-step-60s.flac'),'-codec:a','libmp3lame','-b:a','160k',str(audio_dir/'ace-step-60s.mp3')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run([ffmpeg,'-y','-i',str(ROOT/cached[2]['local_audio_path']),'-codec:a','libmp3lame','-b:a','160k',str(audio_dir/'ace-step-cached3.mp3')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    wave,_=sf.read(audio_dir/'ace-step-60s.flac',always_2d=True,dtype='float32')
    bins=np.array_split(np.max(np.abs(wave),axis=1),900)
    peaks=[float(np.max(x)) for x in bins]
    points=' '.join(f'{20+i*1160/899:.2f},{110-v*85:.2f}' for i,v in enumerate(peaks))
    points+=' '+' '.join(f'{20+i*1160/899:.2f},{110+peaks[i]*85:.2f}' for i in range(899,-1,-1))
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 260" role="img" aria-label="실제로 생성한 60초 음악의 진폭 파형"><line x1="20" y1="110" x2="1180" y2="110" stroke="#d9dbcf"/><polygon points="{points}" fill="#294db4" opacity=".8"/><g font-family="Malgun Gothic,sans-serif" font-size="22" fill="#73776d"><text x="20" y="245">0:00</text><text x="600" y="245" text-anchor="middle">0:30</text><text x="1180" y="245" text-anchor="end">1:00</text></g></svg>'
    (ROOT/'reports/figures/ace-waveform.svg').write_text(svg,encoding='utf-8')
    policies={};policy_music=[]
    raw_policies={}
    for name in NAMES:
        r=read(OUT/f'policy/{name}/result.json');raw_policies[name]=r
        for response in r['responses']:
            music=read(OUT/response['music_record']/'music.json')
            validate_audio(music)
            policy_music.append(music)
        policies[name]={'label':NAMES[name],'requests':r['request_count'],'allocated_seconds':r['allocated_seconds'],
            'gpu_estimate_usd':r['gpu_estimate_usd'],'session_seconds':r['session_seconds'],
            'mean_latency_seconds':statistics.mean(x['latency_seconds'] for x in r['responses']),
            'max_latency_seconds':max(x['latency_seconds'] for x in r['responses']),'restarts':len(r['restarts'])}
    cleanup=read(OUT/'final-cleanup.json')
    assert cleanup['error'] is None and cleanup['all_owned_deleted']
    assert cleanup['account_pod_count']==cleanup['account_network_volume_count']==0
    assert float(cleanup['current_spend_per_hour'])==0
    public_ledger=OUT/'resource-lifetimes.json'
    if public_ledger.exists():
        ledger=read(public_ledger)
    else:
        private=read(ROOT/'private/ace-ledger.json')
        fields=('kind','name','id','created_at_epoch','deleted_at_epoch','total_hourly_usd','size_gb','deleted')
        ledger={'resources':[{k:v for k,v in item.items() if k in fields} for item in private['resources']]}
        save_json(public_ledger,ledger)
    disk=sum((r['deleted_at_epoch']-r['created_at_epoch'])*20*.10/(30*24*3600) for r in ledger['resources'] if r['kind']=='pod')
    volume=sum((r['deleted_at_epoch']-r['created_at_epoch'])*60*.07/(30*24*3600) for r in ledger['resources'] if r['kind']=='volume')
    boot=read(OUT/'bootstrap.json')
    result={'at_utc':utc_now(),'gpu':'NVIDIA GeForce RTX 5090','data_center':'EU-RO-1','gpu_hourly_usd':1.19,
        'source_commit':pre['source_commit'],'main_model_revision':catalogs[0]['sha'],'lm4b_revision':catalogs[1]['sha'],
        'model':'ACE-Step 1.5 turbo 2B DiT + 4B 5Hz LM','duration_seconds':60,'batch_size':1,'seed':42,
        'used_weight_bytes':weight_bytes,'downloaded_checkpoint_artifact_bytes':boot['checkpoint_bytes'],
        'unused_default_lm_17b_was_downloaded':True,'network_volume_allocated_gb':60,
        'cold_intent_to_collected_seconds':cold['intent_to_collected_seconds'],'cold_bootstrap':boot,
        'cached_intent_to_collected_seconds':[x['intent_to_collected_seconds'] for x in cached],
        'cached_median_seconds':statistics.median(x['intent_to_collected_seconds'] for x in cached),
        'cached_worker_ready_median_seconds':statistics.median(x['request_to_ready_seconds'] for x in ready[1:]),
        'cached_generation_seconds':[x['generation_seconds'] for x in cached],
        'cached_generation_median_seconds':statistics.median(x['generation_seconds'] for x in cached),
        'resident_generation_seconds':[x['generation_seconds'] for x in resident],
        'resident_generation_median_seconds':statistics.median(x['generation_seconds'] for x in resident),
        'resident_roundtrip_median_seconds':statistics.median(x['request_to_collected_seconds'] for x in resident),
        'backend_by_load':[x['backend'] for x in ready],'torch_by_load':[x['torch'] for x in ready],
        'peak_cuda_allocated_bytes':max(x['peak_cuda_memory_allocated_bytes'] for x in [cold]+cached+resident+policy_music),
        'weight_hashes_match_hf_revisions':True,'audio_comparisons':comparisons,
        'cached_pod_ids':[x['pod_id'] for x in cached],'four_distinct_pod_ids':len(set([cold['pod_id']]+[x['pod_id'] for x in cached]))==4,
        'policies':policies,'policy_order':policy_pre['order'],'think_time_gaps_seconds':policy_pre['gaps'],
        'policy_arrival_model':'closed-loop, after previous response','policy_requests_per_session':4,
        'policy_audio_files_locally_decoded_and_verified':len(policy_music),'total_music_generations':7+len(policy_music),
        'all_music_files_locally_decoded_and_pcm_hash_verified':7+len(policy_music),
        'allocator_snapshot_note':'frozen-config.json is the legacy allocator input; only image is used by that helper. Actual ACE inference is fixed by preregistered ace_worker.py.',
        'cleanup':cleanup,'container_disk_estimate_usd':disk,'network_volume_continuous_estimate_usd':volume,
        'total_resource_estimate_usd':cleanup['gpu_lifetime_estimate_usd']+disk+volume,
        'storage_month_scenario_usd':60*.07,'gpu_and_storage_month_scenario_usd':7.2*1.19+60*.07,
        'audio_demo':{'flac':'reports/audio/ace-step/ace-step-60s.flac','mp3':'reports/audio/ace-step/ace-step-60s.mp3',
            'original_flac_sha256':sha(audio_dir/'ace-step-60s.flac'),'mp3_sha256':sha(audio_dir/'ace-step-60s.mp3'),
            'alternate_mp3':'reports/audio/ace-step/ace-step-cached3.mp3','alternate_original_flac_sha256':cached[2]['sha256'],
            'alternate_mp3_sha256':sha(audio_dir/'ace-step-cached3.mp3')},
        'limitations':['One cold preparation and three fresh cached Pods.','One run per policy; not a population tail benchmark.',
            'Closed-loop ACE sessions differ from old open-loop Qwen trace.','No flash-attn, no torch.compile; actual backend captured.',
            'Provider/OS caches and physical host assignment uncontrolled.','PCM equality observed separately; audio validity is not a blind quality rating.',
            'Allocation proxy includes API and deletion confirmation; not exact invoice billing.']}
    save_json(ROOT/'reports/ace-step-results.json',result)
    lines=['# ACE-Step 1.5 실제 음악 생성 실험 결과','',
        '60초 instrumental 음악 생성의 실제 결과다. 기존 Qwen의 짧은 텍스트 추론과 다른 모델·실행환경·부하다. 속도 차이를 모델 크기 하나의 인과효과로 해석하지 않는다.','',
        f'사용 가중치 {weight_bytes/1e9:.3f}GB. 다운로드한 체크포인트 아티팩트 {boot["checkpoint_bytes"]/1e9:.3f}GB에는 기본 저장소의 사용하지 않는 1.7B LM도 포함한다. 실제 생성에는 4B LM을 썼다.',
        f'처음 준비부터 음원 회수까지 {cold["intent_to_collected_seconds"]:.1f}초. 설치 {boot["install_seconds"]:.1f}초, 모델 다운로드 {boot["download_seconds"]:.1f}초.','',
        '| 새 Pod | 요청~모델 준비, 초 | 요청~음원 회수, 초 | 생성 자체, 초 |', '|---|---:|---:|---:|']
    for i,(r,rd) in enumerate(zip(cached,ready[1:]),1):lines.append(f'| {i} | {rd["request_to_ready_seconds"]:.1f} | {r["intent_to_collected_seconds"]:.1f} | {r["generation_seconds"]:.1f} |')
    lines+=['',f'새 Pod 재사용의 중앙값 {result["cached_median_seconds"]:.1f}초. 상주 상태의 추가 3회 생성 중앙값 {result["resident_generation_median_seconds"]:.1f}초, 파일 회수까지의 중앙값 {result["resident_roundtrip_median_seconds"]:.1f}초.',
        '사용한 모든 가중치의 SHA-256을 고정 Hugging Face blob과 대조했다. 음원별 파일·PCM hash, 유효성, RMS와 차이는 JSON에 보존했다. 동일 seed의 bitwise 재현을 사전 가정하지 않았다.','',
        '## 실제 보존 정책','',
        '네 번의 음악 생성을 하고 응답 후 5·25·180초를 쉬며, 마지막 응답 뒤 35초를 관측했다. 같은 생성 횟수와 생각할 시간을 비교한다. 정책별 도착시각은 다르다. 초기 모델 준비는 공통 제외하되 전체 비용에 포함했다.','',
        '| 정책 | 보유 근사시간, 초 | 비용 추정, $ | 평균 응답, 초 | 최대 응답, 초 | 재기동 | 세션 전체, 초 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for r in policies.values():lines.append(f'| {r["label"]} | {r["allocated_seconds"]:.1f} | {r["gpu_estimate_usd"]:.5f} | {r["mean_latency_seconds"]:.1f} | {r["max_latency_seconds"]:.1f} | {r["restarts"]} | {r["session_seconds"]:.1f} |')
    lines+=['','정책은 과거의 think time만 관측한다. 미래 공백은 정답지로 주지 않았다.',
        '생성 요청부터 삭제 확인까지의 제어기 구간을 보유 근사시간으로 집계했다. 정확한 공급자 과금시간은 아니며 실제 청구보다 클 수 있다. 정책당 1회라 통계적 우월성을 주장하지 않는다.','',
        '## 비용과 한계','',
        f'전체 자원비용 약 ${result["total_resource_estimate_usd"]:.4f} 추정. 공통 설치·실패·초기 모델 준비를 포함한다. 세금·에이전트 비용 제외, 청구 미확정, 볼륨의 시간 단위 과금과 연속시간 환산 차이 가능.',
        f'최종 Pod {cleanup["account_pod_count"]}개, network volume {cleanup["account_network_volume_count"]}개, 현재 시간당 사용액 {cleanup["current_spend_per_hour"]}.','',
        '설계: docs/ace-step-experiment.md. 공식 실행 API: https://ace-step.github.io/ACE-Step-1.5/en/INFERENCE . 소스와 모델 revision, 런타임 패키지 freeze, 실패 로그와 원자료는 records/ace-step/에 보존했다.','',
        '이전의 작은 합성 Transformer 복구는 ACE-Step 학습 복구 실험이 아니다. 음원 재생은 생성 결과의 증거이며 상용 모델과의 품질 우열을 증명하지 않는다.']
    (ROOT/'reports/ace-step-results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'cached_median_seconds':result['cached_median_seconds'],'resident_generation_seconds':result['resident_generation_median_seconds'],
        'total_resource_estimate_usd':result['total_resource_estimate_usd'],'policies':policies},ensure_ascii=True,indent=2))

if __name__=='__main__':main()
