"""Editorial text and restrained figures for the real retention-policy study."""
import html
import json
from pathlib import Path

from runpod_api import ROOT
from summarize_speculative import NAMES

ORDER=('keep','delete','fixed20','predict')

def blog(result):
    actual=result['actual']
    rows=''.join(f'<tr><td>{NAMES[name]}</td><td>{actual[name]["allocated_seconds"]:.1f}초</td>'
        f'<td>{actual[name]["mean_latency_seconds"]:.1f}초</td><td>{actual[name]["max_latency_seconds"]:.1f}초</td>'
        f'<td>{actual[name]["restarts"]}회</td></tr>' for name in ORDER)
    fixed,predict,keep=actual['fixed20'],actual['predict'],actual['keep']
    observation=(f'이 요청열에서 고정 20초 정책은 GPU를 {fixed["allocated_seconds"]:.1f}초 보유한 것으로 집계됐고, '
        f'평균 응답은 {fixed["mean_latency_seconds"]:.1f}초였다. 예측 TTL은 각각 '
        f'{predict["allocated_seconds"]:.1f}초와 {predict["mean_latency_seconds"]:.1f}초였다. '
        f'상시 보존은 {keep["allocated_seconds"]:.1f}초 동안 장비를 유지하며 평균 '
        f'{keep["mean_latency_seconds"]:.1f}초에 응답했다. 보존하는 시간과 다음 요청의 기다림을 함께 봐야 할 이유가 숫자로 드러났다.')
    sparse=result['synthetic_replay']['sparse'];bursty=result['synthetic_replay']['bursty']
    same=result['same_trace_replay']
    same_observation=(f'먼저 똑같은 요청열을 이 모델에 넣었다. 재기동시간을 같은 값으로 맞춘 재생에서는 고정 20초의 보유 근사시간이 '
        f'{same["fixed20"]["allocated_seconds"]:.1f}초, 예측 TTL은 {same["predict"]["allocated_seconds"]:.1f}초였다. '
        f'평균 응답은 각각 {same["fixed20"]["mean_latency_seconds"]:.1f}초와 {same["predict"]["mean_latency_seconds"]:.1f}초다. '
        '실측 표에서는 예측 쪽이 보유시간도 짧았지만, 이 단순화된 모델에서는 더 오래 보존한 대가로 덜 기다리는 관계가 드러났다. '
        '원래 실측을 수정한 값이 아니라, 기동시간 변동을 없앴을 때를 살펴본 계산이다.')
    def saving(r):return 100*(1-r['predict']['allocated_seconds']/r['keep']['allocated_seconds'])
    replay=(f'이 모델에서 예측 TTL의 보유 근사시간은 상시 보존보다 군집형 요청에서 평균 {saving(bursty):.1f}%, '
        f'희박한 요청에서 {saving(sparse):.1f}% 적었다. 하지만 예측 TTL과 고정 20초를 비교하면 이야기가 달라진다. '
        f'군집형의 평균 응답은 예측 {bursty["predict"]["mean_latency_seconds"]:.1f}초, '
        f'고정 {bursty["fixed20"]["mean_latency_seconds"]:.1f}초였고, 희박한 요청에서는 예측 '
        f'{sparse["predict"]["mean_latency_seconds"]:.1f}초, 고정 {sparse["fixed20"]["mean_latency_seconds"]:.1f}초였다. '
        '요청분포를 바꾸면 보존시간을 늘린 값어치도 바뀐다. 이 값은 실측을 보정값으로 쓴 재생 결과이며, 새 GPU에서 각각 관측한 응답시간은 아니다.')
    text=(ROOT/'story/speculative-section.template.html').read_text(encoding='utf-8')
    for key,value in {'policy_rows':rows,'policy_observation':observation,'replay_observation':replay,'same_trace_observation':same_observation,
                      'policy_cost':f'{result["total_resource_estimate_usd"]:.3f}'}.items():
        text=text.replace('{{'+key+'}}',value)
    return text

def timeline():
    import build_slides as fig
    raw={name:json.loads((ROOT/f'records/speculative/{name}.json').read_text()) for name in ORDER}
    xmax=max(r['policy_seconds'] for r in raw.values());xmax=max(180,((int(xmax)+19)//20)*20)
    x0=215;w=1150
    def x(t):return x0+t/xmax*w
    svg=''
    for i,name in enumerate(ORDER):
        r=raw[name];y=28+i*86
        svg+=fig.text(0,y+28,NAMES[name],28,'#282a25',weight=650)
        svg+=f'<rect x="{x0}" y="{y}" width="{w}" height="36" fill="#e3e5dc"/>'
        starts=[0.]+[b['start'] for b in r['restarts']]
        ends=[e['confirmed'] for e in r['events'] if e['type'] in ('delete_intent','horizon_delete')]
        assert len(starts)==len(ends)
        for start,end in zip(starts,ends):
            svg+=f'<rect x="{x(start):.2f}" y="{y}" width="{x(end)-x(start):.2f}" height="36" fill="#294db4"/>'
        for b in r['restarts']:
            svg+=f'<rect x="{x(b["start"]):.2f}" y="{y}" width="{x(b["ready"])-x(b["start"]):.2f}" height="36" fill="#c28b58"/>'
        for a in r['trace']:
            svg+=f'<line x1="{x(a):.2f}" x2="{x(a):.2f}" y1="{y-8}" y2="{y+43}" stroke="#282a25" stroke-width="2"/>'
    for t in range(0,int(xmax)+1,20):svg+=fig.text(x(t),396,str(t),23,'#73776d',anchor='middle')
    svg+=fig.text(1370,425,'초',23,'#73776d',anchor='end')
    for xx,color,label in [(215,'#294db4','GPU 보유'),(535,'#c28b58','재기동 중'),(875,'#e3e5dc','반납 상태')]:
        svg+=f'<rect x="{xx}" y="454" width="23" height="23" fill="{color}"/>'+fig.text(xx+35,474,label,25)
    return fig.svg(svg,1400,500,'실제 네 정책의 GPU 보유·재기동·반납 구간. 검은 세로선은 고정 요청 도착시각이다.')

def add_slides(slide,result):
    slide('GPU도 캐시처럼 남길까?', '''<div class="two-col rule"><div><p class="metric-label">곧 다시 쓸 것 같으면</p><p class="statement">투기적 <strong>보존</strong></p><p class="big-sentence" style="margin-top:36px">틀리면 유휴 비용을 낸다</p></div><div><p class="metric-label">당분간 안 쓸 것 같으면</p><p class="statement">투기적 <strong>반납</strong></p><p class="big-sentence" style="margin-top:36px">틀리면 다음 요청이 기다린다</p></div></div><p class="handnote" style="margin-top:45px">모델 파일은 남기고, GPU만 판단한다</p>''',
        '미래 재사용을 예상해 자원을 보존하거나 반납하는 문제입니다. CPU·데이터베이스·Redis·LLM 캐시는 서로 같은 구현이 아닙니다. 재사용 가치와 보존비용을 비교한다는 질문을 빌려온 비유입니다.\n\n이번 반납은 실행 중인 요청 취소나 모델 파일 삭제가 아닙니다. 대기열이 비었을 때 Pod만 삭제하고 준비물은 volume에 남겼습니다. 보존을 틀리면 비용, 반납을 틀리면 재기동 지연이 생깁니다.',
        '투기적 셧다운은 유휴 Pod의 반납을 뜻한다. 실행 중인 요청과 영구 데이터는 보존하며, 미래 요청은 미리 알지 못한다',chapter='다음 요청을 예상한다',seconds=65)
    a=result['actual']
    rows=''.join(f'<tr><th>{NAMES[name]}</th><td class="num">{a[name]["allocated_seconds"]:.1f}초</td>'
        f'<td class="num">{a[name]["mean_latency_seconds"]:.1f}초</td><td class="num">{a[name]["max_latency_seconds"]:.1f}초</td>'
        f'<td class="num">{a[name]["restarts"]}</td></tr>' for name in ORDER)
    slide('보존의 가격과 반납의 기다림을 같이 쟀다',f'''<table class="plain-table" style="font-size:26px"><thead><tr><th>실제 RTX5090</th><th class="num">보유 근사시간</th><th class="num">평균 응답</th><th class="num">최대 응답</th><th class="num">재기동</th></tr></thead><tbody>{rows}</tbody></table><p class="note-line">고정 합성 요청 9개 · 정책당 1회<br>예측 TTL = 과거 도착 간격 EWMA × 4, 최소 5초·최대 60초</p>''',
        '실제 Pod를 삭제하고 다음 요청 때 새로 만들었습니다. 처음 한 대는 모델 준비 완료 상태로 시작했습니다. 이후 기동 중 도착한 요청은 FIFO로 처리했습니다. 도착 시각은 0, 8, 16, 46, 54, 62, 132, 140, 148초입니다. 종료 기준은 175초이며 미완료 요청은 끝까지 처리했습니다.\n\n정책 순서는 사전에 섞었습니다. 예측기는 미래 도착시각을 받지 않고, 초기 간격 10초와 alpha 0.5의 EWMA를 썼습니다. 보유시간은 생성 요청부터 삭제 확인까지의 제어기 구간 근사로, 실제 과금과 다를 수 있습니다. 소표본이므로 정책의 통계적 우월성은 주장하지 않습니다. 근거: reports/speculative-results.json actual.',
        '정책별 1회·9요청. 공통 최초 준비 제외, 전체 실험비에는 포함. 생성 요청~삭제 확인 근사이며 정확한 공급자 청구시간은 아니다',chapter='직접 돌린 정책 네 가지',seconds=90)
    slide('한 번의 반납은 뒤의 요청도 기다리게 했다', '<div style="margin-top:8px">'+timeline()+'</div><p class="caption" style="margin-top:15px">검은 세로선 = 요청 도착. 보존의 오판은 유휴 비용으로, 반납의 오판은 대기열로 남는다.</p>',
        '파랑은 GPU를 보유한 제어기 구간, 갈색은 새 Pod와 worker를 준비한 구간, 회색은 반납 상태입니다. 검은 선은 모든 정책에서 같은 요청 도착시각입니다.\n\n긴 공백 뒤 새 GPU를 기다리는 동안 다음 요청이 도착하면 대기열에 쌓입니다. 즉시 반납은 돈을 줄여도 짧은 요청 군집을 기다리게 할 수 있고, 길게 보존하면 빈 시간을 지불하게 됩니다. 미래의 마지막 요청 시각을 정책에는 주지 않았습니다. 관측 종료에만 사용했습니다. 근거: records/speculative/{policy}.json.',
        '실제 상태 전환 기록. 모델·파일은 volume에 보관. 물리 호스트·공급자 캐시·시간대 차이는 통제하지 못했다',chapter='요청열을 따라가 보면',seconds=75)

def appendix(slide,result):
    labels={'bursty':'짧은 군집','sparse':'희박한 요청','alternating':'짧고 긴 간격 교대','irregular':'불규칙한 간격'}
    rows=''
    for regime,label in labels.items():
        r=result['synthetic_replay'][regime]
        rows+=(f'<tr><th>{label}</th><td class="num">{r["fixed20"]["allocated_seconds"]:.0f} / {r["predict"]["allocated_seconds"]:.0f}</td>'
            f'<td class="num">{r["fixed20"]["mean_latency_seconds"]:.1f} / {r["predict"]["mean_latency_seconds"]:.1f}</td></tr>')
    slide('다른 요청분포는 실측 보정 모델로 재생했다',f'''<table class="plain-table" style="font-size:26px"><thead><tr><th>각 100개 합성 trace</th><th class="num">보유 근사시간, 초<br>고정 / 예측</th><th class="num">평균 응답, 초<br>고정 / 예측</th></tr></thead><tbody>{rows}</tbody></table><p class="note-line">각 24요청 · 같은 보정값과 같은 요청열로 비교<br>실제 400회 GPU 실험이 아니라, 별도 이산사건 재생</p>''',
        '실제 재기동·상주 요청·삭제 확인 시간의 중앙값을 고정한 이산사건 모델입니다. 네 종류의 합성 요청분포에서 100개씩 만들고 같은 요청열을 네 정책에 재생했습니다. 여기에는 고정 20초와 예측 TTL만 표시했고 전체 네 정책은 결과 JSON에 있습니다.\n\n실제 정책 실행 4회와 구분합니다. 네트워크 변동과 재고 실패를 모형화하지 않아 실제 서비스의 지연분포를 나타내지 않습니다. 같은 trace의 재생값과 실측값도 결과 JSON에 함께 보존했습니다. 근거: reports/speculative-results.json과 records/speculative/replay-traces.json.',
        '실측 중앙값으로 보정한 결정론 모델. 각 열은 trace 평균이며, 실제 사용자 트래픽이나 추가 GPU 실행 결과가 아니다',chapter='부록 E',appendix=True)
