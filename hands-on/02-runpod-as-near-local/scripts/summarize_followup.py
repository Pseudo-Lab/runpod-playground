"""Analyze measured follow-up artifacts and render standalone scientific figures."""
import hashlib
import json
import math
import re
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'private/analysis-deps'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

R = ROOT / 'records/followup'
REPORT = ROOT / 'reports'
FIG = REPORT / 'figures/followup'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def savefig(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / (name + '.png'), dpi=180, bbox_inches='tight')
    fig.savefig(FIG / (name + '.svg'), bbox_inches='tight')
    plt.close(fig)


def main():
    storage = [read(R / f'storage-{b}-{a}/result.json') for b in (1, 2, 3) for a in 'ABC']
    tokens = [r['tokens'] for r in storage]
    matching_tokens = sum(t == tokens[0] for t in tokens)
    matching_hashes = sum(r['hashes'] == storage[0]['hashes'] for r in storage)
    outputs_match = matching_tokens == 9 and matching_hashes == 9
    by = {a: [r for r in storage if r['arm'] == a] for a in 'ABC'}
    ratios = {a: [by[a][i]['total_seconds'] / by['A'][i]['total_seconds'] for i in range(3)]
              for a in 'BC'}
    medians = {a: st.median(r['total_seconds'] for r in by[a]) for a in 'ABC'}
    predicted_break_even = {}
    for a in 'BC':
        predicted_break_even[a] = []
        for baseline, alternative in zip(by['A'], by[a]):
            copy = alternative['dependency_copy_seconds'] + alternative['model_copy_seconds']
            saved_per_fresh_process = baseline['total_seconds'] - (alternative['total_seconds'] - copy)
            predicted_break_even[a].append(math.ceil(copy / saved_per_fresh_process)
                if saved_per_fresh_process > 0 else None)
    trials = {seed: {mode: read(R / f'train-{mode}-{seed}/result.json')
                    for mode in ('baseline', 'fault', 'full', 'weights')}
              for seed in (11, 22, 33)}
    full_ok = {seed: t['full']['parameter_max_abs_error'] <= 1e-5 and
        t['full']['eval_loss_abs_error'] <= 1e-5 and t['full']['batch_sequence_matches']
        for seed, t in trials.items()}
    cleanup = read(R / 'final-cleanup.json')
    assert cleanup['all_owned_deleted'], 'Cloud resources remain'
    ledger = read(ROOT / 'private/followup-ledger.json')
    pod_hours = sum((r['deleted_at_epoch'] - r['created_at_epoch']) / 3600
                    for r in ledger['resources'] if r['kind'] == 'pod' and r.get('id'))
    previous_attempts = [read(p) for p in (R / 'attempts').glob('*/final-cleanup.json')]
    for p in (ROOT / 'private').glob('followup-attempt*-ledger.json'):
        prior_ledger = read(p)
        pod_hours += sum((r['deleted_at_epoch'] - r['created_at_epoch']) / 3600
                        for r in prior_ledger['resources'] if r['kind'] == 'pod' and r.get('id'))
    cleanup = dict(cleanup)
    cleanup['pod_runtime_cost_estimate_usd'] += sum(p['pod_runtime_cost_estimate_usd'] for p in previous_attempts)
    cleanup['network_volume_estimate_usd'] += sum(p['network_volume_estimate_usd'] for p in previous_attempts)
    cleanup['previous_failed_attempt_count'] = len(previous_attempts)
    container_est = pod_hours * 20 * .1 / 720
    first_restore = read(R / 'train-full-11/controller.json')
    after_pod = next(r for r in ledger['resources'] if r['name'].endswith('-train-after'))
    first_restore_seconds = datetime.fromisoformat(first_restore['at_utc']).timestamp() - after_pod['created_at_epoch']
    summary = {'storage_median_total_seconds': medians,
        'paired_median_improvement_fraction': {a: 1 - st.median(ratios[a]) for a in 'BC'},
        'storage_threshold_met': {a: st.median(ratios[a]) <= .8 and outputs_match for a in 'BC'},
        'modeled_break_even_process_count': predicted_break_even,
        'all_tokens_and_hashes_match': outputs_match, 'full_recovery_pass_by_seed': full_ok,
        'first_restore_request_to_collected_result_seconds': first_restore_seconds,
        'container_disk_estimate_usd': container_est, 'cleanup': cleanup}
    REPORT.mkdir(exist_ok=True)
    (REPORT / 'followup-results.json').write_text(json.dumps(summary, indent=2) + '\n')

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False,
                         'axes.spines.right': False, 'svg.fonttype': 'none'})
    fig, ax = plt.subplots(figsize=(11, 5))
    fields = ['dependency_copy_seconds', 'model_copy_seconds', 'import_seconds',
              'hash_seconds', 'load_seconds', 'inference_seconds']
    colors = ['#9db4c0', '#f0bc79', '#756bb1', '#a1d99b', '#2c7f8f', '#e8795c']
    bottom = [0.] * len(storage)
    for field, color in zip(fields, colors):
        values = [r[field] for r in storage]
        ax.bar(range(9), values, bottom=bottom, label=field.replace('_seconds', '').replace('_', ' '), color=color)
        bottom = [a + b for a, b in zip(bottom, values)]
    other = [max(0, r['total_seconds'] - b) for r, b in zip(storage, bottom)]
    ax.bar(range(9), other, bottom=bottom, color='#ddd', label='other process overhead')
    ax.set_xticks(range(9), [r['run_id'].replace('storage-', '') for r in storage])
    ax.set(ylabel='Seconds (copy included)', xlabel='Pod block - storage arm',
           title='Storage placement: nine fresh-process measurements in three Pod blocks')
    ax.legend(ncol=4, fontsize=8, loc='upper center', bbox_to_anchor=(.5, -.18))
    fig.tight_layout()
    savefig(fig, 'storage-breakdown')

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8), sharey=True)
    for ax, (seed, t) in zip(axes, trials.items()):
        for mode, color, style in [('baseline', '#243e46', '-'), ('full', '#278b65', '--'),
                                    ('weights', '#d5782c', ':')]:
            rows = t[mode]['rows']
            ax.plot([r['step'] for r in rows], [r['loss'] for r in rows],
                    color=color, linestyle=style, label=mode, linewidth=1.4)
        ax.axvline(60, color='#999', linewidth=.8, label='checkpoint' if seed == 11 else None)
        ax.axvline(73, color='#d5782c', linewidth=.8, alpha=.5,
                   label='fault at 73' if seed == 11 else None)
        ax.set(title=f'Seed {seed}', xlabel='Global optimizer step')
    axes[0].set_ylabel('Training cross-entropy loss')
    axes[0].legend(fontsize=8)
    fig.suptitle('Resume on a different Pod: full state vs weights only')
    fig.tight_layout()
    savefig(fig, 'training-loss')

    fig, ax = plt.subplots(figsize=(8, 4))
    for i, mode in enumerate(('full', 'weights')):
        values = [trials[s][mode]['parameter_max_abs_error'] for s in trials]
        x = [j + (i - .5) * .32 for j in range(3)]
        ax.bar(x, [max(v, 1e-12) for v in values], width=.3,
               color=['#278b65', '#d5782c'][i], label=mode)
        for xx, v in zip(x, values):
            ax.text(xx, max(v, 1e-12) * 1.8, '0 (exact)' if v == 0 else f'{v:.2g}',
                    ha='center', fontsize=8)
    ax.axhline(1e-5, color='#777', linestyle='--', label='predefined tolerance 1e-5')
    ax.set_yscale('log')
    ax.set_xticks(range(3), ['11', '22', '33'])
    ax.set(ylabel='Max absolute parameter error vs uninterrupted', xlabel='Seed',
           title='Final parameter reproducibility (zero drawn at 1e-12 for visibility)')
    ax.legend(fontsize=8, ncol=3, loc='upper center', bbox_to_anchor=(.5, -.19))
    fig.tight_layout()
    savefig(fig, 'recovery-error')

    lines = ['# 추가 실험 결과', '', '실행일: 2026-10-24. 발표 예정: 2026-10-27(화).', '',
        '## 결론', '',
        f"- 준비시간 중앙값: A {medians['A']:.2f}초 / B {medians['B']:.2f}초 / C {medians['C']:.2f}초. 복사시간을 포함한다.",
        '- 블록별 비율의 중앙값으로 본 개선율: ' + ', '.join(
            f"{a} {100*(1-st.median(ratios[a])):.1f}%" for a in 'BC') + '.',
        f"- 전체 상태 학습 복구: 사전 허용오차와 batch 순서 기준 {sum(full_ok.values())}/3 seed 통과.",
        '- 아래 결과는 각각 작은 고정 추론과 합성 데이터의 작은 Transformer에 한정한다.', '',
        '## 공통 실행 조건', '',
        'NVIDIA L4 1개, EU-RO-1, On-demand 견적 $0.59/h. 생성 직전에도 가격을 확인했으며 '
        '고정 RTX5090 상한 $1.19/h 이내다. 실제 Torch는 `' + storage[0]['environment']['torch'] +
        '`, CUDA `' + str(storage[0]['environment']['cuda']) + '`, 저장소 측정 드라이버는 `' +
        ', '.join(sorted({r['environment']['driver'] for r in storage})) + '`. '
        '추론은 기존 Qwen2.5-1.5B-Instruct의 고정 revision·이미지 digest·BF16·greedy 설정을 사용했다. '
        '학습은 별도 작은 모델의 FP32 작업이다. 세부 설정과 소스 hash는 '
        '`records/followup/frozen-config.json`, `preregistered.json`에 있다.', '',
        '## 1. 준비 지연의 원인: 저장 위치별 비교', '',
        'A=의존성·모델 모두 network volume, B=의존성만 `/tmp`, C=의존성·모델 모두 `/tmp`. '
        '3개 새 Pod 안에서 각 군을 새 프로세스로 한 번씩 실행했다. 순서는 ABC/BCA/CAB다. '
        '각 군마다 새 Pod를 생성한 비교는 아니며 provider·OS 캐시를 비우지 않았다.', '',
        '표의 전체시간은 원격 worker가 staging을 시작하기 직전부터 결과를 산출할 때까지다. '
        '복사와 자식 프로세스의 전체 import를 포함하지만 부모 Python의 초기 표준 라이브러리 '
        'import·인자 파싱은 제외한다. wrapper가 측정한 프로세스 전체 수명과 로컬 왕복시간도 '
        '각 실행의 `exit.json`, `controller.json`에 별도로 보관했다.', '',
        '| 블록 | A 전체 초 | B 전체 초 | C 전체 초 | B/A | C/A |',
        '|---|---:|---:|---:|---:|---:|']
    for i in range(3):
        lines.append(f"| {i+1} | {by['A'][i]['total_seconds']:.2f} | {by['B'][i]['total_seconds']:.2f} | "
            f"{by['C'][i]['total_seconds']:.2f} | {ratios['B'][i]:.3f} | {ratios['C'][i]:.3f} |")
    lines += ['', '![측정별 시간 분해](figures/followup/storage-breakdown.png)', '',
        f'각 막대는 평균이 아닌 실제 한 측정이다. 모델 SHA-256은 {matching_hashes}/9, 생성 토큰은 {matching_tokens}/9 기준 출력과 일치했다. '
        '상대 개선율의 음수는 악화다. 각 대안의 사전20% 개선 기준: ' +
        ', '.join(f"{a} {'충족' if st.median(ratios[a]) <= .8 and outputs_match else '미충족'}" for a in 'BC') + '.', '',
        '| 군 | 복사 중앙값 초 | import 중앙값 초 | hash 중앙값 초 | 로드 중앙값 초 | 추론 중앙값 초 |',
        '|---|---:|---:|---:|---:|---:|']
    for a, rows in by.items():
        vals = [st.median(r['dependency_copy_seconds'] + r['model_copy_seconds'] for r in rows)]
        vals += [st.median(r[k] for r in rows) for k in ('import_seconds', 'hash_seconds', 'load_seconds', 'inference_seconds')]
        lines.append('| ' + a + ' | ' + ' | '.join(f'{v:.2f}' for v in vals) + ' |')
    lines += ['', '이 열별 중앙값의 합은 전체 중앙값과 반드시 같지 않다. 부트·최초 설치·다운로드는 '
        '공통 준비비이며 위 표에서 제외했다. Pod별 SSH 시간은 `records/followup/pod-*.json`, '
        '공통 설치·다운로드는 `dependency-install.json`과 `prepared.json`에 있다.', '',
        '이번 A도 사전 준비한 snapshot 경로를 직접 읽고 offline 모드로 로드한다. '
        '기존 프로토타입의 매회 snapshot 조회·설치 확인과 동일한 전체 제어 흐름은 아니다. '
        '따라서 이전 실험과 이번 시간 차이를 저장 위치의 인과 효과로 주장하지 않으며, '
        '기존5분 유지/삭제 정책을 다시 측정한 결과도 아니다.', '',
        '### 같은 Pod에서 복사한 파일을 여러 번 재사용한다면? (계산 예측)', '',
        '같은 Pod에서 매회 새 Python 프로세스로 모델을 로드하되 최초 복사 파일을 재사용한다고 '
        '가정하면, `복사시간 + N × (측정 전체시간−복사시간)`과 `N × A 전체시간`을 비교할 수 있다. '
        '각 블록으로 계산한 손익분기 호출 수는 다음과 같다. None은 양의 절감이 없어 유한 값을 '
        '제시하지 못한다는 뜻이다.', '',
        '| 대안 | 블록1 | 블록2 | 블록3 |', '|---|---:|---:|---:|',
        *['| ' + a + ' | ' + ' | '.join(str(v) for v in predicted_break_even[a]) + ' |' for a in 'BC'], '',
        '**이 표는 반복 재사용 실측이 아니다.** 캐시·입출력 부하가 일정하다는 가정이 필요하며 '
        'GPU에 모델을 계속 상주시킨 유지형이나 요청 묶음 정책의 결과로 해석하면 안 된다.', '',
        '## 2. Pod 삭제 후 학습 복구', '',
        '작은 자체 causal Transformer(2층, hidden128, 4 heads, vocabulary128, sequence64, batch8), '
        'FP32 AdamW,120 step을 실행했다. 학습 파라미터 수는 ' +
        str(trials[11]['baseline']['parameters']) + '개다. '
        '합성 next-token 데이터이므로 대형 언어 모델 fine-tuning 품질 실험으로 해석하지 않는다.', '',
        '각 seed에서 무중단120 step과 별도로73 step에서 프로세스를 예상 종료86으로 끊었다. '
        '저장은20-step 주기여서 최신 확정 파일은60 step이다. **13 step을 잃었고 재개 때 다시 계산했다.** '
        '기존 Pod를 실제 삭제하고 다른 ID의 Pod에서 전체 복구(F)와 가중치만 복구(W)를 수행했다. '
        'W는 optimizer·scheduler·RNG·batch 순서가 모두 초기화되어 단일 요소의 효과를 분리한 실험은 아니다.', '',
        '| seed | 무중단 평가 loss | 전체 복구 평가 loss | 가중치만 평가 loss | F 파라미터 최대오차 | W 파라미터 최대오차 | F 기준 |',
        '|---|---:|---:|---:|---:|---:|---|']
    for seed, t in trials.items():
        lines.append(f"| {seed} | {t['baseline']['eval_loss']:.6f} | {t['full']['eval_loss']:.6f} | "
            f"{t['weights']['eval_loss']:.6f} | {t['full']['parameter_max_abs_error']:.3g} | "
            f"{t['weights']['parameter_max_abs_error']:.3g} | {'통과' if full_ok[seed] else '미통과'} |")
    lines += ['', '![학습 loss 곡선](figures/followup/training-loss.png)', '',
        '![최종 파라미터 오차](figures/followup/recovery-error.png)', '',
        '가중치만 복구했을 때 평가 loss가 더 낮게 나와도 같은 학습을 재현한 것은 아니다. '
        '여기서의 성공은 최종 성능 경쟁이 아니라 무중단 궤적 복원이다. 실제 W는 scheduler도 '
        '초기화하여 재개 첫 learning rate가0.001이고 F는0.0005였다. 데이터 순서도 달라 '
        '낮은 평가 loss의 원인을 한 요소로 돌릴 수 없다.', '',
        '| seed | F 체크포인트 로드 초 | F 나머지60-step 학습 초 | F 최대 loss 오차 | F batch 순서 일치 |',
        '|---|---:|---:|---:|---|']
    for seed, t in trials.items():
        f = t['full']
        lines.append(f"| {seed} | {f['checkpoint_load_seconds']:.3f} | {f['train_seconds']:.3f} | "
            f"{f['max_loss_abs_error']:.3g} | {f['batch_sequence_matches']} |")
    lines += ['', f'새 Pod 생성 요청 직전부터 첫 seed 복구 결과의 로컬 회수까지 {first_restore_seconds:.1f}초였다. '
        '이 값에는 새 Pod 기동·프로세스 import·남은 학습·회수가 포함된다. 나머지 seed들은 같은 Pod를 '
        '공유했으므로 각각 새 Pod를 만들었을 때의 독립 end-to-end 복구시간이라고 주장하지 않는다.', '',
        '60-step checkpoint와 기준 최종 상태는 S3 전체 객체로 로컬 백업했다. '
        '`backup-manifest.json`에 bytes/SHA-256을 남겼다. F/W의 최종 상태6개도 S3 전체 객체로 '
        '추가 백업했고 결과 hash와 대조했다(`recovered-states-backup-manifest.json`). 대형 파일은 Git 제외 경로 '
        '`private/followup-backups/`에 보관한다. 모델 다운로드 파일과 달리 학습 데이터·가중치는 직접 생성한 것이다.', '',
        '## 3. 비용·실패·정리', '',
        f"Pod 수명×견적 비용 추정 ${cleanup['pod_runtime_cost_estimate_usd']:.4f}, "
        f"container disk 추정 ${container_est:.4f}, network volume 연속시간 환산 추정 "
        f"${cleanup['network_volume_estimate_usd']:.4f}. 합계 약 $"
        f"{cleanup['pod_runtime_cost_estimate_usd']+container_est+cleanup['network_volume_estimate_usd']:.4f}다. "
        '견적에 디스크가 포함됐는지에 따라 중복 가능성이 있으며 공급자 확정 청구가 아니다. '
        'Network volume은 시간 단위 과금이므로 연속시간 환산과 실제 청구는 다를 수 있다. '
        '세금·에이전트 비용은 포함하지 않았다.', '',
        f"관측 계정 잔액 감소: ${cleanup['observed_account_balance_decrease_usd']:.4f}. "
        '계정 전체 관측으로 실행별 확정 청구와 구분한다. '
        f"최종 계정 Pod {cleanup['account_pod_count']}개, network volume "
        f"{cleanup['account_network_volume_count']}개, 시간당 사용액 ${cleanup['account_current_spend_per_hour']}.", '',
        '추가 실행의 공급자 usage 조회에는 아직7개 Pod 중0개의 내역만 나타났다 '
        '(`records/followup/billing-partial.json`). 확정 비용은 알 수 없으며0달러라는 뜻이 아니다.', '',
        '각 fault 실행의 종료86은 계획된 주입이다. 계획 밖 오류가 있으면 '
        '`execution-error.json`, `pod-*-failure.json`, `attempts/`와 수정 기록을 함께 확인한다. '
        '실패와 재실행 비용은 최종 합계에서 제외하지 않는다. 이번에는 비교 측정 전 준비 단계에서 '
        'SFTP가 없는 선택적 결과 파일의 빈 로컬 파일을 남겨 JSON 파싱에 실패한1회가 있었다. '
        '이를 수정하고 전 자원을 삭제한 뒤 재시작했다. 실패한 첫 시도의 Pod 비용 약$0.0422도 '
        '위 합계에 포함했다. 상세 실행 차이는 `docs/followup/실행기록.md`에 있다.', '',
        '### 기존 실험 청구의 사후 확인', '',
        '2026-10-24에 기존10월17일 실험의 공급자 usage를 다시 조회했다. '
        '알려진17개 Pod 모두 사용 내역이 나타났고 Pod usage 합계는 $' +
        f"{read(R / 'original-billing-recheck.json')['pod_usage_amount_usd']:.4f}" +
        '였다. 당시 GPU 수명 추정 $0.4446과는 수집 경계·디스크 포함 여부가 달라 '
        '완전히 같은 비용 범주라고 단정하지 않는다. Network volume은 계정 시간창 집계만 '
        '제공되어 실행별로 나누지 않았다. 이 자료도 세금 포함 최종 청구서 확인과는 다르다. '
        '증거는 `original-billing-recheck.json`이며 기존 보고서는 당시 관측 기록으로 유지했다.', '',
        '## 4. 해석의 한계와 다음 단계', '',
        '- 표본은 저장소3 Pod 블록, 복구3 seed와 한 쌍의 전후 Pod다. 일반적 실패율·p95를 추정할 수 없다.',
        '- 새 Pod ID가 서로 다른 물리 호스트를 의미하지는 않는다. 물리 호스트 이동을 별도로 검증한 실험은 아니다.',
        '- 저장 경로 효과는 지역·volume 상태·기존 파일 캐시와 함께 달라진다. `/tmp`가 별도 파일시스템임은 원본 `environment.filesystems`로 확인한다.',
        '- FP32 작은 단일-GPU 모델의 복구가 성공해도 BF16 LLM·AMP scaler·분산 sampler·다중 GPU 상태까지 검증한 것은 아니다.',
        '- 전체 상태와 가중치만 비교는 여러 상태를 동시에 바꾼다. 어떤 상태가 차이의 주원인인지 알려면 optimizer/RNG 등의 개별 제거 비교가 필요하다.',
        '- 저장 주기를 여러 값으로 바꾸거나 혼합 유지 정책을 실제 trace에서 비교하는 것은 후속 후보이며 이번 실측으로 주장하지 않는다.', '',
        '설계·계획은 `docs/followup/`, 선정 과정은 `추가실험-아이디어선정.md`, 원자료는 `records/followup/`다. '
        '참고: [RunPod 가격](https://docs.runpod.io/pods/pricing), '
        '[PyTorch checkpoint](https://docs.pytorch.org/tutorials/recipes/recipes/saving_and_loading_a_general_checkpoint.html).', '']
    document = re.sub(r'(?<=[가-힣])(?=[0-9])', ' ', '\n'.join(lines))
    (REPORT / 'followup-results.md').write_text(document, encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
