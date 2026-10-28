"""Summarize measured cached RTX5090 starts and explicitly hypothetical economics."""
import hashlib
import json
import statistics
from pathlib import Path

from runpod_api import ROOT, save_json


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    r = ROOT / 'records/story'
    cold = read(r / 'cold/measurement.json')
    cached = [read(r / f'cached-{i}/measurement.json') for i in (1,2,3)]
    previous = read(ROOT / 'manifests/model.json')
    assert cold['hashes']['model.safetensors'] == previous['weights']['sha256']
    assert len({row['pod_id'] for row in [cold] + cached}) == 4
    for row in cached:
        assert row['tokens'] == cold['tokens'] and row['hashes'] == cold['hashes']
        assert row['download_and_hf_lookup_seconds'] == 0
        assert row['environment']['gpu'] == 'NVIDIA GeForce RTX 5090'
    ledger = read(ROOT / 'private/story-ledger.json')
    pod_hours = sum((x['deleted_at_epoch'] - x['created_at_epoch']) / 3600 for x in ledger['resources'] if x['kind'] == 'pod')
    volume_hours = sum((x['deleted_at_epoch'] - x['created_at_epoch']) / 3600 for x in ledger['resources'] if x['kind'] == 'volume')
    cleanup = read(r / 'final-cleanup.json')
    assert cleanup['all_owned_deleted'] and cleanup['account_pod_count'] == 0 and cleanup['account_network_volume_count'] == 0
    reservation = read(r / 'preregistered.json')
    for name, sha in reservation['source_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha
    result = {'gpu': cold['environment']['gpu'], 'data_center': 'EU-RO-1', 'gpu_hourly_usd': 1.19,
        'cold_end_to_end_seconds': cold['intent_to_collected_result_seconds'],
        'cold_install_seconds': cold['install_seconds'], 'cold_archive_build_seconds': cold['archive_build_seconds'],
        'cold_download_and_lookup_seconds': cold['download_and_hf_lookup_seconds'],
        'cached_end_to_end_seconds': [v['intent_to_collected_result_seconds'] for v in cached],
        'cached_median_seconds': statistics.median(v['intent_to_collected_result_seconds'] for v in cached),
        'cached_extract_median_seconds': statistics.median(v['archive_read_and_extract_seconds'] for v in cached),
        'cached_model_load_median_seconds': statistics.median(v['load_seconds'] for v in cached),
        'all_output_tokens_and_hashes_match': True, 'four_distinct_pod_ids': True,
        'pod_estimate_usd': cleanup['pod_estimate_usd'],
        'container_disk_estimate_usd': pod_hours * 20 * .1 / 720,
        'network_volume_estimate_usd': volume_hours * 20 * .07 / 720,
        'cleanup': cleanup,
        'scenario': {'purchase_budget_krw': 12000000, 'personal_expected_idle_fraction': .99,
            'month_hours': 720, 'allocated_gpu_hours': 7.2, 'gpu_usd': 7.2 * 1.19,
            'volume_gb': 20, 'storage_usd_month': 20 * .07,
            'gpu_plus_storage_usd_month': 7.2 * 1.19 + 20 * .07,
            'note': 'Hypothetical billed allocation hours including setup, not observed compute utilization or total ownership cost.'}}
    result['total_resource_estimate_usd'] = sum(result[k] for k in ('pod_estimate_usd','container_disk_estimate_usd','network_volume_estimate_usd'))
    save_json(ROOT / 'reports/story-results.json', result)
    rows = '\n'.join(f"| {i} | {read(r/f'pod-cached-{i}.json')['ssh_seconds']:.2f} | {v['intent_to_collected_result_seconds']:.2f} | {v['archive_read_and_extract_seconds']:.3f} | {v['load_seconds']:.3f} |" for i,v in enumerate(cached,1))
    report = f'''# RTX5090 임대와 준비물 재사용 추가 결과

2026-10-24, RTX5090 / EU-RO-1 / On-demand $1.19/h. 모델 약3.09GB Qwen2.5-1.5B-Instruct 고정revision, BF16, batch1, greedy. 이미지digest와Torch버전은기존고정설정과같다.

최초 준비부터 첫 결과 회수까지 **{result['cold_end_to_end_seconds']:.2f}초**. 의존성 설치 {result['cold_install_seconds']:.2f}초, 의존성tar 패키징 {result['cold_archive_build_seconds']:.2f}초, 모델다운로드·조회 {result['cold_download_and_lookup_seconds']:.2f}초였다. 새 환경을 준비하는 사례1회이며, 이 수치가보편적인cold-start상한은아니다.

GPU를 삭제하고 준비물을 volume에 남긴 뒤 새5090 Pod3개에서 재실행했다. 요청에서 결과회수까지 중앙값 **{result['cached_median_seconds']:.2f}초**. 모델 재다운로드는3회모두0이며파일SHA-256과생성토큰은최초결과와같았다.

| 재생성 | 요청→SSH 초 | 요청→결과회수 초 | archive읽기·전개 초 | 모델로드 초 |
|---|---:|---:|---:|---:|
{rows}

요청→결과회수에는제어API조회·Pod생성·SSH연결·코드전송·의존성전개·import·모델hash·로드·추론·폴링·회수가포함된다. 하위계측값들은원격worker clock이며전체와동일한범주로단순합산하지않는다.

Pod0개일때S3로표식파일을쓰기·읽기했고,모델객체의HEAD크기와64KB Range hash를검증했다. 이후각Pod의마운트에서같은파일과표식을읽었다. S3는RunPod network volume에접근하는호환API경로이며AWS S3별도버킷이아니다. 모델전체를로컬로S3다운로드한시험은아니다.

기존L4에서의의존성디렉터리복사73.6초와이번아카이브전개약{result['cached_extract_median_seconds']:.3f}초는하드웨어·환경·파일전달방식이달라단일요인의인과효과로비교하지않는다. 이번에는 --no-compile설치후tar로준비물을묶고각Pod의/tmp에전개했다. 패키징비용도최초준비와전체비용에포함했다. provider·OS캐시는통제하지않았고새Pod가다른물리호스트라는보장도없다.

추가자원비용은GPU ${result['pod_estimate_usd']:.4f}, containerdisk ${result['container_disk_estimate_usd']:.4f}, volume연속시간환산 ${result['network_volume_estimate_usd']:.4f}, 합계약 **${result['total_resource_estimate_usd']:.4f} 추정**. 세금·에이전트비용제외, 청구미확정, volume시간단위과금차이가능. 최종Pod0개·volume0개·현재시간당사용액0을확인했다.

## 글의 계산 예와 경계

- 1,200만원은구매예산가정,99%유휴는개인적예상이다. 시장가격이나다른사람의실측유휴율이아니다.
- 월720시간중Pod할당7.2시간과20GB volume한달보존을가정하면GPU $8.568 + 저장소 $1.40 = 약$9.97다. 기동·설치시간도7.2시간안에포함한가정이며세금·containerdisk·환율·에이전트비용은별도다. 실제GPU연산사용률1%를바로임대시간1%로바꾸지않는다.
- 로컬GPU와동일작업성능비교,실제사용자세션유휴율,Codex/Claude모델·effort별시간차이는미측정이다. 가정용가벼운실험에서기다림을허용한다는글쓴이의판단과구분한다.
- 재고실패는이전3090실험에서관측했다. volume지역에서원하는GPU가항상다시할당된다고보장하지않는다.

공식단가: https://docs.runpod.io/pods/pricing . S3경로: https://docs.runpod.io/storage/s3-api . 원본: records/story/ . 사전설계: docs/story-experiment.md .
'''
    (ROOT / 'reports/story-results.md').write_text(report,encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
