"""Summarize measured artifacts; never substitute estimates for confirmed billing."""
import json
import math
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path

from runpod_api import ROOT, save_json, utc_now


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    runs = [load(p) for p in sorted((ROOT / 'records').glob('*/metrics.json'))]
    baseline = [r for r in runs if r['run_id'] in ('b01', 'b02', 'b03')]
    good = [r for r in baseline if r['result'] == 'success']
    ready = [r['timing_seconds']['ready'] for r in good]
    first = [r['timing_seconds']['first_result'] for r in good]
    h1 = {'status': 'passed_exploratory' if len(good) == 3 and max(ready) <= 300
          and statistics.median(ready) <= 180 else 'incomplete_or_failed',
          'hardware': 'NVIDIA GeForce RTX 3090 / EU-CZ-1', 'successes': len(good),
          'attempts': len(baseline), 'ready_seconds': ready, 'first_result_seconds': first,
          'ready_timing': 'approximate local timing derived from remote elapsed duration',
          'note': 'A later same-GPU allocation request failed; this does not establish capacity availability.'}
    h4 = {'status': 'incomplete'}
    if len(good) == 3:
        remote = [r['remote'] for r in good]
        ref = remote[0]
        token_match = all(r['generated_token_ids'] == ref['generated_token_ids'] for r in remote)
        manifest_match = all(r['model_manifest'] == ref['model_manifest'] for r in remote)
        difference = max(abs(a - b) for r in remote
            for a, b in zip(r['first_logits_sample'], ref['first_logits_sample']))
        h4 = {'status': 'passed_inference_only' if token_match and manifest_match
              and difference <= .01 else 'failed', 'generated_tokens_identical': token_match,
              'model_manifests_identical': manifest_match, 'max_sample_logit_abs_error': difference,
              'sampled_logits': 64, 'training_resume': 'not_tested'}
    pairs = []
    for i in range(1, 4):
        k, e = ROOT / f'records/c{i}-keep.json', ROOT / f'records/c{i}-ephemeral.json'
        if k.exists() and e.exists():
            keep, ephemeral = load(k), load(e)
            pairs.append({'pair': i, 'keep': keep, 'ephemeral': ephemeral,
                'cost_savings_fraction': 1 - ephemeral['estimated_cost_usd'] / keep['estimated_cost_usd'],
                'completion_increase_fraction': ephemeral['complete_seconds'] / keep['complete_seconds'] - 1})
    h2 = {'status': 'incomplete', 'completed_pairs': len(pairs),
          'representative_user_pattern': 'not_tested', 'pattern': 'synthetic_300s', 'pairs': pairs,
          'second_call_scope_note': 'Keep second-call seconds measure remote inference only; ephemeral seconds measure local request-to-result. Use complete_seconds for the policy time comparison.'}
    if len(pairs) == 3:
        kcost = sum(p['keep']['estimated_cost_usd'] for p in pairs)
        ecost = sum(p['ephemeral']['estimated_cost_usd'] for p in pairs)
        savings = 1 - ecost / kcost
        increase = (sum(p['ephemeral']['complete_seconds'] for p in pairs)
                    / sum(p['keep']['complete_seconds'] for p in pairs) - 1)
        h2.update({'status': 'passed_synthetic_only' if savings >= .30 and increase <= .20
                   else 'failed_synthetic', 'cost_savings_fraction': savings,
                   'completion_increase_fraction': increase, 'keep_cost_usd': kcost,
                   'ephemeral_cost_usd': ecost,
                   'keep_second_call_seconds': [p['keep']['second_call_seconds'] for p in pairs],
                   'ephemeral_second_call_seconds': [p['ephemeral']['second_call_seconds'] for p in pairs]})
    l4 = [r['remote'] for r in runs if r['result'] == 'success'
          and r['gpu']['gpu_type'] == 'NVIDIA L4']
    if l4:
        h2['l4_inference_runs_checked'] = len(l4)
        h2['l4_generated_tokens_identical'] = all(r['generated_token_ids'] == l4[0]['generated_token_ids'] for r in l4)
        h2['l4_model_manifests_identical'] = all(r['model_manifest'] == l4[0]['model_manifest'] for r in l4)
        h2['resident_repeat_tokens_identical'] = all(
            r['second']['generated_token_ids'] == r['remote']['generated_token_ids']
            for r in runs if r['result'] == 'success' and r.get('second'))
        if not h2['l4_generated_tokens_identical'] or not h2['l4_model_manifests_identical'] or not h2['resident_repeat_tokens_identical']:
            h2['status'] = 'output_validation_failed'
    fault_path = ROOT / 'records/d02/fault.json'
    fault = load(fault_path) if fault_path.exists() else None
    ssh_test = next((r.get('ssh_disconnect_test') for r in baseline
                     if r.get('ssh_disconnect_test')), None)
    h5 = {'status': 'passed_tested_cases' if fault and ssh_test
          and fault['status'] == 'passed' and ssh_test['status'] == 'passed' else 'incomplete',
          'ssh_disconnect': ssh_test, 'controller_termination': fault,
          'not_tested': ['lost create response', 'interrupted upload', 'API outage', 'whole-PC failure']}
    state = load(ROOT / 'private/ledger.json')
    estimate = sum(r.get('estimated_cost_usd', 0) for r in runs)
    if fault:
        estimate += fault['estimated_cost_usd']
    volume_estimate = 0
    for resource in state['resources']:
        if resource['kind'] != 'volume':
            continue
        begin = resource['expires_at'] - 7200
        end = (datetime.fromisoformat(resource['deleted_at_utc']).timestamp()
               if resource.get('deleted_at_utc') else datetime.now(timezone.utc).timestamp())
        volume_estimate += 10 * .07 / 720 * max(1, math.ceil((end - begin) / 3600))
    container_estimate = sum(r['timing_seconds']['total_including_delete'] / 3600
        * 20 * .10 / 720 for r in runs if r.get('resource_created', True))
    if fault:
        container_estimate += fault['total_seconds'] / 3600 * 20 * .10 / 720
    initial_l4 = next((r for r in runs if r['run_id'] == 'a04'), None)
    range_path = ROOT / 'records/s3-model-range.json'
    summary = {'generated_at_utc': utc_now(), 'H1': h1, 'H2': h2,
        'H3': {'status': 'not_tested', 'reason': 'optional storage-path comparison deferred'},
        'H4': h4, 'H5': h5,
        'gpu_cost_estimate_usd': estimate, 'billed_gpu_cost_usd': None,
        'container_disk_estimate_usd': container_estimate,
        'network_volume_estimate_usd': volume_estimate,
        'provider_total_estimate_before_tax_usd': estimate + container_estimate + volume_estimate,
        'storage_estimate_basis': '10GB volumes rounded up to an hour; 20GB container disks; 720h/month estimate',
        'initial_l4_preparation': {'ready_seconds': initial_l4['timing_seconds']['ready'],
            'first_result_seconds': initial_l4['timing_seconds']['first_result']} if initial_l4 else None,
        's3_model_range': load(range_path) if range_path.exists() else None,
        'run_attempts_excluding_controller_fault': len(runs),
        'successes': sum(r['result'] == 'success' for r in runs),
        'failures': [{'run_id': r['run_id'], 'error': r.get('error'),
                      'estimated_cost_usd': r.get('estimated_cost_usd')}
                     for r in runs if r['result'] != 'success'],
        'remaining_owned_resources': [{'kind': r['kind'], 'name': r['name']}
                         for r in state['resources'] if not r.get('deleted')],
        'hardware_changes': state.get('hardware_changes', [])}
    final_path = ROOT / 'records/final-cleanup.json'
    billing_path = ROOT / 'records/billing-partial.json'
    if final_path.exists():
        summary['final_cleanup'] = load(final_path)
    if billing_path.exists():
        summary['billing_partial'] = load(billing_path)
    save_json(ROOT / 'reports/results.json', summary)
    kst = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S KST')
    text = ['# RunPod GPU 실험 결과', '', f'갱신: {kst} ({utc_now()})', '',
        'RTX 3090 재현성 시험과 L4 후속 시험은 별도 조건이다. 아래 비용은 API 견적과 로컬 관측 수명으로 계산한 추정값이며 청구 확정액이 아니다.', '',
        '| 항목 | 결과 |', '|---|---|',
        f'| H1 준비시간 | {h1["status"]}: ' + ', '.join(f'{v:.1f}초' for v in ready) + ' |',
        '| 첫 결과 수신 | ' + ', '.join(f'{v:.1f}초' for v in first) + ' |',
        f'| H2 비용 비교 | {h2["status"]}, 5분 합성 패턴 {len(pairs)}/3쌍 |',
        '| H3 저장소 경로 비교 | 선택 실험으로 미실시 |',
        f'| H4 추론 재현성 | {h4["status"]} |', f'| H5 기본 장애 시험 | {h5["status"]} |', '',
        f'GPU 추정 비용 합계: **${estimate:.4f}**. 초기 실패 시도와 제어기 중단 시험도 포함했다. Container disk·network volume·세금 등은 별도이며 최종 정리 기록과 함께 확인한다.', '',
        f'Container disk 추정 ${container_estimate:.4f}, network volume 추정 ${volume_estimate:.4f}. 저장소는 공식 단가와 월 720시간 환산을 사용한 추정이다. 에이전트 비용·세금은 포함하지 않았다.', '',
        '## 확인한 내용', '',
        '- Pod가 없는 상태에서 S3 작은 파일 업로드·다운로드와 SHA-256 검증에 성공했다.',
        '- 새 Pod에서 영속 파일 hash를 확인했고, 임시 경로의 표식은 남아 있지 않았다.',
        '- 3090 고정 추론 3회의 모델 파일 hash·생성 토큰·표본 logit을 비교했다. 학습 복구는 시험하지 않았다.',
        '- 최초 이미지 준비 시 FP16에서 비정상 logit이 나와 BF16으로 전환한 뒤 반복 조건을 고정했다. 모델 파일 hash는 원본 Hugging Face 메타데이터와 일치했다.',
        '- 3090을 삭제한 후 재고가 없어 다음 생성 요청이 실패했다. 재할당 실패를 피할 수 있다는 결론은 내릴 수 없다.',
        '- 이미지 태그는 2.8.0이지만 실제 Torch 버전은 `2.8.0.dev20250319+cu128`이었다. 실행은 동일 image digest로 고정했다.', '',
        '## 실패 시도', '',
        '| 시도 | 원인 | GPU 추정 비용 |', '|---|---|---:|']
    for r in summary['failures']:
        reason = (r['error'] or '').replace('\n', ' ').replace('|', '/')
        if r['run_id'] == 'a01':
            reason = '백그라운드 실행 후 SSH 명령 반환 대기 중 타임아웃. 분리된 subprocess 실행으로 수정했다.'
        text.append(f'| {r["run_id"]} | {reason} | ${r["estimated_cost_usd"]:.5f} |')
    if initial_l4:
        text += ['', f'L4 최초 준비는 {initial_l4["timing_seconds"]["ready"]:.1f}초, 첫 결과 수신은 {initial_l4["timing_seconds"]["first_result"]:.1f}초였다. 캐시가 없는 최초 실행은 5분을 초과했다. 이후 정책 비교는 준비된 캐시를 사용한다.']
    if range_path.exists():
        text += ['', '3.09GB 모델 객체의 S3 조회와 64KB Range 읽기 hash 일치를 확인했다. 대용량 파일 전체의 S3 왕복·multipart·중단 재개는 시험하지 않았다.']
    if len(pairs) == 3:
        text += ['', '## 5분 합성 패턴의 정책 비교', '',
                 f'GPU 추정 비용 절감률 {100*h2["cost_savings_fraction"]:.1f}%, 전체 완료시간 증가율 {100*h2["completion_increase_fraction"]:.1f}%. 에이전트 비용을 포함한 총비용 비교는 아니다.',
                 '', '| 쌍 | 유지 GPU 비용 | 삭제 GPU 비용 | 유지 완료시간 | 삭제 완료시간 |', '|---|---:|---:|---:|---:|']
        for p in pairs:
            k,e=p['keep'],p['ephemeral']
            text.append(f'| {p["pair"]} | ${k["estimated_cost_usd"]:.4f} | ${e["estimated_cost_usd"]:.4f} | {k["complete_seconds"]:.1f}초 | {e["complete_seconds"]:.1f}초 |')
        text += ['', '유지형은 모델을 GPU 메모리에 둔 채 두 번째 추론을 수행했다. 삭제형은 두 번째 요청 때 Pod·모델을 다시 준비했다. 실제 사용자 호출 간격을 측정하지 않았으므로 이 결과는 5분 합성 패턴에 한정한다.']
        text += ['', '유지형의 두 번째 호출 수치는 원격 추론 연산시간이고 삭제형은 로컬 요청부터 결과 수신까지의 시간이다. 이 둘을 같은 범위의 지연 지표로 직접 비교하지 않는다. 정책 판정에는 두 작업의 결과 회수가 끝날 때까지의 전체 시간을 사용했다. 모델 작업은 약 38토큰의 짧은 추론이며, 장시간 학습이나 다른 모델로 일반화하지 않는다.']
        text += ['', '이 프로토타입은 Python 의존성을 network volume에 두고 설치 확인과 실제 작업에서 import를 반복한다. 따라서 준비시간에는 이 구현의 파일 접근·import 비용도 포함된다. 의존성을 컨테이너 이미지에 포함한 구성과의 비교는 하지 않았다. 다음 개선 후보는 이 준비 비용을 줄인 뒤 같은 패턴을 다시 측정하는 것이다.']
    text += ['', '## 증거와 정리', '',
        '- 상세 수치: `reports/results.json`, 시도별 원본: `records/<run_id>/`.',
        '- 공개 API 명세: `cache/runpod-api/`, GPU 가격 캐시: `cache/gpu-prices.json`.',
        '- 자격증명과 자원 소유권 원장은 Git에서 제외한 `.env`와 `private/`에 보관한다.',
        '- 현재 원장상 남은 자원: ' + (', '.join(r['kind'] for r in summary['remaining_owned_resources']) or '없음') + '.', '']
    if final_path.exists():
        final = load(final_path)
        text += [f'최종 API 조회: Pod {final["account_pod_count"]}개, network volume {final["account_network_volume_count"]}개, 시간당 사용액 ${final["account_current_spend_per_hour"]}.', '',
            f'계정 잔액은 최초 조회 대비 ${final["observed_account_balance_decrease_usd"]:.4f} 감소했다. 계정 전체 관측값이며 실행별 청구 확정액은 아니다. 일부 Pod 청구 내역만 반영됐고 저장소 청구는 아직 확인되지 않았다. `records/billing-partial.json`과 `records/final-cleanup.json`에 확인 상태를 남겼다.', '']
    (ROOT / 'reports/results.md').write_text('\n'.join(text), encoding='utf-8')
    print(json.dumps({'H1': h1['status'], 'H2': h2['status'], 'H4': h4['status'],
                      'H5': h5['status'], 'gpu_cost_estimate_usd': estimate}))


if __name__ == '__main__':
    main()
