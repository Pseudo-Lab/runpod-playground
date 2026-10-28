"""Presentation content for the real ACE-Step music workload."""
import html
import json
import math

import build_slides as fig
from ace_story_expansion import expand_main
from runpod_api import ROOT

NAMES={'keep':'상시 보존','delete':'즉시 반납','fixed20':'고정 20초','predict':'예측 TTL'}
MAIN_COUNT=35
APPENDIX_COUNT=7

def table(head,rows,small=False,numeric_columns=None,widths=None):
    numeric=set(range(1,len(head))) if numeric_columns is None else set(numeric_columns)
    cols='' if widths is None else '<colgroup>'+''.join(f'<col style="width:{w}%">' for w in widths)+'</colgroup>'
    fixed=' style="table-layout:fixed"' if widths is not None else ''
    header=''.join('<th scope="col"'+(' class="num"' if i in numeric else '')+'>'+html.escape(x)+'</th>' for i,x in enumerate(head))
    body=''.join('<tr>'+''.join(('<th scope="row"' if i==0 else '<td')+(' class="num"' if i in numeric else '')+'>'+html.escape(str(x))+('</th>' if i==0 else '</td>') for i,x in enumerate(row))+'</tr>' for row in rows)
    return '<table class="plain-table'+(' small-table' if small else '')+'"'+fixed+'>'+cols+'<thead><tr>'+header+'</tr></thead><tbody>'+body+'</tbody></table>'

def policy_timeline():
    raw={name:json.loads((ROOT/f'records/ace-step/policy/{name}/result.json').read_text()) for name in NAMES}
    maximum=max(x['session_seconds'] for x in raw.values());step=max(60,math.ceil(maximum/6/60)*60);limit=math.ceil(maximum/step)*step
    x0=210;w=1160;svg=''
    def x(t):return x0+w*t/limit
    for i,(name,r) in enumerate(raw.items()):
        y=22+i*85
        svg+=fig.text(0,y+30,NAMES[name],27,'#282a25',weight=650)
        svg+=f'<rect x="{x0}" y="{y}" width="{w}" height="36" fill="#e3e5dc"/>'
        starts=[0.]+[b['start'] for b in r['restarts']]
        ends=[e['confirmed'] for e in r['events'] if e['type'] in ('idle_delete','session_end_delete')]
        assert len(starts)==len(ends)
        for a,b in zip(starts,ends):svg+=f'<rect x="{x(a):.2f}" y="{y}" width="{x(b)-x(a):.2f}" height="36" fill="#294db4"/>'
        for b in r['restarts']:svg+=f'<rect x="{x(b["start"]):.2f}" y="{y}" width="{x(b["ready"])-x(b["start"]):.2f}" height="36" fill="#c28b58"/>'
        for request in r['responses']:
            a=x(request['arrival']);svg+=f'<line x1="{a:.2f}" x2="{a:.2f}" y1="{y-7}" y2="{y+43}" stroke="#282a25" stroke-width="2"/>'
    for tick in range(0,limit+1,step):svg+=fig.text(x(tick),390,f'{tick//60}:{tick%60:02}',22,'#73776d',anchor='middle')
    for xx,color,label in [(210,'#294db4','기동 후 보유'),(595,'#c28b58','재기동 중'),(1010,'#e3e5dc','반납 상태')]:
        svg+=f'<rect x="{xx}" y="430" width="22" height="22" fill="{color}"/>'+fig.text(xx+34,451,label,24)
    return fig.svg(svg,1400,475,'정책별 실제 ACE-Step 세션. 각 행의 검은 선은 해당 정책의 요청 시각이며, 응답 이후 쉼을 주므로 행마다 시각이 다르다.')

def make_slides(r,audio,all_cost,alternate_audio=None):
    slides=[]
    def add(title,body,notes,foot='',theme='',chapter='',seconds=60,appendix=False):
        slides.append(dict(title=title,body=body,notes=notes,foot=foot,theme=theme,chapter=chapter,seconds=seconds,appendix=appendix))
    add('5090은 안 샀습니다','<p class="section-label">가끔 GPU가 필요한 사람의 이야기</p><h1>5090은<br><em>안 샀습니다</em></h1><p class="sub">5090을 사는 대신, 빌린 GPU로 음악을 만들었습니다</p><p class="cover-date">2026.10.27　　필요할 때만 빌려 쓴 GPU 실험기</p>',
        '가끔 모델을 돌려보고 싶은 사람이 큰돈을 먼저 쓰지 않고 GPU를 빌려 실제 작업을 끝낼 수 있는지 확인한 이야기입니다.\n\n60초 음악 생성이라는 구체적인 작업을 정하고, 준비시간과 파일 보관, GPU를 언제 반납할지 직접 재봤습니다. 모든 구매자를 설득하기보다 내 사용법에서 어떤 선택이 맞는지 묻습니다.',theme='dark cover',chapter='도입',seconds=30)
    add('천이백만원을 쓴다고 쳐봅시다','<p class="handnote">구매 시나리오</p><div class="price">1,200<span>만 원</span></div><p class="big-sentence">비싸게 들여온 GPU 하나<br>나는 이걸 얼마나 잘 쓸까</p>',
        '1,200만원은 비싼 구매 상황을 가정한 예산입니다. 5090의 정가나 모든 제품의 시장가가 아닙니다. 확인한 특정 판매페이지의 표시가격은 약 960만원이었습니다.\n\n특정 제품 추천이나 구매와 임대의 TCO 손익분기를 주장하지 않습니다. 먼저 내 사용법에서 큰 선투자가 필요한지 묻습니다.',
        '1,200만원은 구매예산 가정. 확인한 제품 한 곳의 표시가격은 약 960만원이며, 최저가나 실제 결제가가 아니다',chapter='일단 가정 하나')
    add('내가 사면, 거의 놀릴 것 같았다','<div class="row baseline"><div class="huge accent">99<small>%</small></div><p class="big-sentence" style="margin-left:45px">실제로 잰 사용률은 아니고<br>내가 사면 이럴 것 같았다</p></div><div class="idle-bar"><span></span></div><p class="note-line">새 모델을 돌리고, 코드를 고치고, 읽고, 생각할 사람<br>장비가 생긴다고 갑자기 부지런해질 리는 없고</p>',
        '99%는 내가 예상하는 개인적 사용 패턴입니다. 실제 사용률이나 시장 통계로 측정한 값이 아닙니다. 게임과 긴 작업을 매일 하는 사람에게 그대로 적용하면 안 됩니다.\n\n이 장면의 질문은 비싼 GPU의 성능이 아니라, 내가 상시 소유의 값을 얼마나 활용하느냐입니다.',
        '개인적 예상. 실제 사용자 세션이나 구매자들의 평균 GPU 유휴율을 측정한 수치가 아니다',chapter='나는 내가 안다')
    add('그래서 필요할 때 빌렸다','<div class="two-col rule"><div><p class="metric-label">이번 RTX5090 견적</p><div class="metric-number">$1.19<small>/ 시간</small></div><p class="metric-detail">EU-RO-1 · On-demand<br>생성 직전에 재확인</p></div><div><p class="statement">쓸 때 빌리고<br>결과를 챙기고<br><strong>장비는 돌려준다</strong></p><p class="note-line">모델과 실행환경은 별도로 보관</p></div></div>',
        '실제 RTX5090을 사용했고 GPU 견적은 시간당 $1.19였습니다. 동시에 한 개만 사용하고 자원 만료와 독립 감시기를 두었습니다. 저장소와 임시 디스크는 별도입니다.\n\n같은 지역에서 다음에도 재고가 있으리라는 보장은 없습니다. 이번 단가와 시점의 관측으로 읽어주세요.',
        '실제 생성 전 견적 확인. 같은 지역·GPU의 재고와 가격을 항상 보장하지 않는다',chapter='소유 대신 임대',seconds=45)
    add('해볼 일은 정했다. 60초짜리 음악 만들기',f'<div class="ace-stack"><strong>2B</strong><span>turbo DiT</span><strong>4B</strong><span>5Hz LM</span></div><div class="thin-rule"></div><p class="big-sentence">ACE-Step 1.5 · 60초 instrumental<br>실제 사용하는 가중치 약 {r["used_weight_bytes"]/1e9:.2f}GB</p><p class="note-line">공식 코드와 모델 revision 고정<br>batch 1 · seed 42 · 8 diffusion steps</p>',
        '취미로 해볼 작업을 구체적으로 정했습니다. ACE-Step 1.5로 60초 instrumental 음악을 만듭니다. 파일이 내려왔다는 숫자만 보는 대신 바로 들어볼 수 있는 결과물을 가져오기로 했습니다.\n\nturbo 2B DiT에 4B 언어모델, 텍스트 인코더와 공식 VAE를 사용했습니다. 4B라는 말은 LM이며 XL 4B DiT를 사용한 것은 아닙니다. 가중치 크기와 실제 VRAM 할당량은 구분합니다.',
        '공식 ACE-Step 1.5의 음악 생성 구성. 파일 크기와 파라미터 수, VRAM 사용량은 서로 다른 값이다',chapter='이번 본 실험',seconds=65)
    waveform=(ROOT/'reports/figures/ace-waveform.svg').read_text(encoding='utf-8')
    add('이건 실제로 만든 60초 음악입니다',f'<div class="audio-demo">{waveform}{audio}</div><p class="audio-meta" style="margin-top:24px">요청 설정: Lo-fi jazz hip-hop · instrumental · 100 BPM · D minor</p>',
        '실제 새 Pod에서 생성한 파일을 내 PC로 회수했고 hash와 길이, sample rate와 채널 수를 확인했습니다. 재생 파일은 원본 FLAC을 감상용 MP3로 변환한 것입니다. 자동 재생은 하지 않습니다.\n\n원하는 만큼 들려준 뒤 다음 장으로 넘어가면 음악은 멈춥니다. 이 음원은 실제 생성의 증거이며 다른 음악 모델보다 품질이 좋다는 블라인드 평가 결과는 아닙니다.',
        '실제 생성 원본은 48kHz stereo FLAC으로 회수·검증. 슬라이드에는 감상용 MP3를 포함했다',chapter='먼저 결과부터',seconds=45)
    ssh=[]
    for i in (1,2,3):ssh.append(json.loads((ROOT/f'records/ace-step/pod-cached-{i}.json').read_text())['ssh_seconds'])
    import statistics
    add('GPU 접속은 27초, 첫 음원을 받기까지는 약 3분',f'<div class="two-col rule"><div><p class="metric-label">요청부터 SSH 연결까지</p><div class="metric-number">{statistics.median(ssh):.1f}<small>초</small></div></div><div><p class="metric-label">요청부터 60초 음원 회수까지</p><div class="metric-number">{r["cached_median_seconds"]:.1f}<small>초</small></div></div></div><p class="note-line">준비물을 남긴 뒤 새 RTX5090 세 번의 중앙값<br>가중치 검증·import·모델 초기화·생성·파일 회수까지</p>',
        '장비가 빨리 생겼다고 음악도 바로 나오는 것은 아니었습니다. 새 Pod에 연결된 뒤 실행환경을 import하고 모델을 초기화하는 시간이 남습니다. 전체 가중치 hash 검증도 넣었습니다.\n\n관리 화면의 준비 표시나 SSH 접속만으로 음악을 만들 수 있는 상태를 대표하지 않도록 시계를 나눴습니다.',
        '최초 준비와 별개인 새 Pod 재사용 3회. 공급자·OS 캐시와 물리 호스트는 통제하지 않았고 p95를 추정하지 않는다',chapter='첫 번째 반론을 다시 봤다',seconds=70)
    rows=[]
    for i in (1,2,3):
        m=json.loads((ROOT/f'records/ace-step/cached-{i}/measurement.json').read_text());rd=json.loads((ROOT/f'records/ace-step/cached-{i}/ready.json').read_text())
        rows.append([str(i),f'{rd["request_to_ready_seconds"]:.1f}초',f'{m["intent_to_collected_seconds"]:.1f}초',f'{m["generation_seconds"]:.1f}초'])
    add('세 번 다 새 Pod에서 음악을 회수했다',table(['새 Pod','모델 준비까지','음원 회수까지','생성 자체'],rows)+f'<p class="note-line">사용한 가중치 약 {r["used_weight_bytes"]/1e9:.2f}GB의 전체 SHA-256 대조<br>실제 60초 음악 파일을 로컬로 가져와 검증</p>',
        '서로 다른 Pod ID 세 개입니다. 매번 같은 모델 파일을 인터넷에서 다시 받지 않고 volume에서 읽었습니다. 모델 hash는 고정 Hugging Face blob과 대조했고, 음원은 로컬 회수 후 파일 hash도 확인했습니다.\n\n모델 파일의 일치와 생성된 PCM의 일치는 다른 기준입니다. 관측한 재현 여부는 결과 JSON에 따로 보존했습니다.',
        '코드·모델·입력 고정. 새 Pod ID 확인, 다른 물리 서버로 이동했는지는 미확인',chapter='원자료',seconds=55)
    parts=[(r['cold_bootstrap']['install_seconds'],'실행환경 설치','#294db4'),(r['cold_bootstrap']['download_seconds'],'모델 다운로드','#849dcc')]
    imp=json.loads((ROOT/'records/ace-step/cold/ready.json').read_text())['import_seconds'];parts.append((imp,'첫 import','#c28b58'))
    parts.append((r['cold_intent_to_collected_seconds']-sum(x[0] for x in parts),'생성·초기화·회수 등','#d8d8ca'))
    content='';pos=0
    for value,label,color in parts:
        width=value/r['cold_intent_to_collected_seconds']*1400;content+=f'<rect x="{pos}" y="10" width="{width}" height="70" fill="{color}"/>';pos+=width
    for i,(value,label,color) in enumerate(parts):
        xx=i*350;content+=f'<rect x="{xx}" y="120" width="16" height="16" fill="{color}"/>'+fig.text(xx+26,138,label,24)+fig.text(xx+26,188,f'{value:.1f}초',30,'#282a25',weight=650)
    add('처음엔 음악 한 곡 받는 데 12분 걸렸다',f'<div class="metric-number">{r["cold_intent_to_collected_seconds"]:.1f}<small>초</small></div><p class="big-sentence" style="margin-top:16px">프로그램 설치부터 첫 음원을 내 PC로 가져오기까지</p><div style="margin-top:35px">{fig.svg(content,1400,225,"최초 실행의 구간. 설치·다운로드·import와 그 외 잔여시간을 포함한다.")}</div>',
        '첫 준비는 실제 연속 계측입니다. 공식 소스 전송과 전개, 설치, 모델 다운로드, 가중치 검증, 초기화, 음악 생성과 파일 회수를 포함합니다. 표시한 구간 외의 나머지는 전체시간에서 뺀 잔여값입니다.\n\n다운로드한 약 18.52GB에는 기본 저장소에 들어 있는 사용하지 않는 1.7B LM도 포함됩니다. 실제 생성에는 4B를 사용했으며 활성 가중치 크기와 다운로드 총량을 나눴습니다.',
        '최초 준비 1회. 나머지는 소스 전송·전개, SSH, 검증·초기화·생성·회수 등의 잔여값이며 일반적 상한이 아니다',chapter='한 번 내는 준비비',seconds=80)
    add('모델을 올려두니, 60초 음악을 약 7초에 만들었다',f'<p class="handnote">모델이 이미 올라간 같은 Pod에서 추가 3회</p><div class="answer-number">{r["resident_generation_median_seconds"]:.1f}<span>초</span></div><p class="big-sentence">60초 음악의 생성 자체 중앙값<br>파일 회수까지는 {r["resident_roundtrip_median_seconds"]:.1f}초</p>',
        '초기 음악 생성과 상주 상태의 추가 세 번을 구분했습니다. 같은 입력과 seed이며 파일 회수와 검증도 따로 계측했습니다. 캐시 재사용으로 새 Pod를 만드는 시간과 생성 자체의 시간을 섞지 않습니다.\n\n이 차이가 뒤의 보존 정책 질문으로 연결됩니다. 곧 다음 시도를 할 가능성이 있다면 모델이 올라간 상태를 잠깐 남길 값어치가 있습니다.',
        '추가 생성 3회의 중앙값. 이미 준비된 Pod의 수치이며 새 GPU의 기동시간을 포함하지 않는다',chapter='그러니 보존도 생각하게 된다',seconds=60)
    add('나는 어차피 에이전트에 맡겨놓고 기다린다','<p class="editorial-quote">코드를 짜고, 설치하고,<br>에러가 나면 다시 고치게 한다</p><div class="thin-rule"></div><p class="big-sentence">그 작업 흐름에서<br>내가 받아들일 준비시간은 얼마일까</p>',
        '모델·effort별 에이전트 지연을 측정해 비교한 장면은 아닙니다. 내 작업 흐름에서 원격 GPU의 추가 준비시간을 받아들일지 묻는 개인적 판단입니다.\n\n모든 지연을 무시해도 된다는 뜻도 아닙니다. 결과가 와야 다음 행동을 할 때는 기다림이 중요하고, 준비를 맡겨놓고 다른 작업을 할 때는 기준이 달라집니다.',
        '개인적 사용 관점. 에이전트별 지연과 실제 사용자들의 유휴율은 측정하지 않았다',chapter='기다림을 쓰는 방식',seconds=60)
    add('GPU는 반납해도, 준비물은 남길 수 있었다','<p class="editorial-quote">GPU는 지우고<br><span class="marker">모델과 환경은 남긴다</span></p><p class="big-sentence" style="margin-top:45px">새 Pod가 같은 network volume을 읽는다<br>다시 다운로드하지 않아도 초기화는 다시 필요하다</p>',
        '저장소의 모델 파일, 실행환경, GPU 메모리에 올라간 모델은 서로 다른 층입니다. 이번에는 파일과 환경을 보존하고 GPU 메모리는 새로 준비했습니다.\n\n공식 lockfile의 venv를 volume에서 재사용해 설치를 반복하지 않았습니다. 네트워크 파일 접근이 import와 초기화에 영향을 줄 수 있어 모델 자체의 순수 성능으로 보지 않습니다.',
        '파일이 저장소에 남는 것과 모델이 GPU 메모리에 올라가 있는 것은 다른 상태다',chapter='두 번째 반론',seconds=60)
    add('Ceph는 저장 기반과 접근 방식을 나눈다','<p class="storage-intro">Ceph: 분산 스토리지 시스템. 같은 저장 기반 위에 서로 다른 인터페이스를 제공한다.</p><div class="ceph-frontends"><div><strong>CephFS</strong><p>파일시스템</p><small>디렉터리와 파일로 접근</small></div><div><strong>RBD</strong><p>블록 스토리지</p><small>디스크 장치처럼 연결</small></div><div><strong>RGW</strong><p>객체 스토리지 API</p><small>S3·Swift 호환 접근</small></div></div><div class="ceph-connectors" aria-hidden="true"><span>↓</span><span>↓</span><span>↓</span></div><div class="rados-base"><strong>RADOS</strong><span>Ceph의 공통 분산 객체 저장 기반</span></div><p class="storage-takeaway">RADOS가 객체를 저장한다는 것과, S3 API로 접근한다는 것은 다른 계층이다.</p>',
        'Ceph는 여러 서버의 저장장치를 묶어 쓰는 분산 스토리지 시스템입니다. 공통 기반인 RADOS 위에 CephFS, RBD, RGW라는 파일·블록·객체 인터페이스를 제공합니다. 파일시스템도 내부적으로 RADOS 객체에 저장할 수 있지만 S3 API를 거쳐야 하는 것은 아닙니다.\n\n같은 클러스터를 쓴다고 CephFS 파일이 자동으로 RGW의 버킷에서 보이는 것도 아닙니다. 이 그림은 개념 비교이며 RunPod가 실제로 Ceph를 사용한다고 확인한 것은 아닙니다. 근거: https://docs.ceph.com/en/squid/architecture/',
        'Ceph의 구조를 이해하기 위한 비교. RunPod 내부 구현이 Ceph라는 뜻은 아니다. 출처: Ceph 공식 Architecture',chapter='저장 방식과 접근 방식',seconds=70)
    add('RunPod S3는 같은 파일에 접근하는 또 다른 문','<p class="storage-intro">이번 network volume은 원격 파일시스템이다. S3 호환 API도 제공한다.</p><div class="runpod-paths"><div><strong>GPU Pod 안에서는</strong><p>/workspace에 마운트</p><small>Python에서 일반 파일처럼 읽고 쓴다</small></div><div><strong>내 PC에서는</strong><p>S3 호환 API로 접근</p><small>Pod가 없어도 파일을 올리고 내려받는다</small></div></div><div class="rados-base"><strong>같은 network volume의 파일</strong><span>AWS S3 버킷을 따로 만든 것이 아니다</span></div><p class="storage-takeaway">실제 확인: Pod 0개에서 S3 접근 → 새 Pod에서 같은 모델 파일 재사용</p>',
        'AWS S3에 별도 모델 버킷을 만들었다는 뜻이 아닙니다. RunPod network volume의 파일에 S3 호환 도구로 접근하는 경로입니다. GPU가 없는 동안 표식 파일과 큰 모델 객체를 확인했습니다.\n\n이후 새 Pod의 파일 prefix와 S3 Range hash도 대조했습니다. 전체 가중치는 Hugging Face blob과 대조했습니다. 대형 파일의 S3 전체 왕복이나 multipart 중단·재개는 시험하지 않았습니다.',
        'network volume은 파일시스템, S3는 접근 API. 별도 Global Volume은 객체 스토리지 기반이다. 출처: RunPod 공식 문서',chapter='이름 때문에 생기는 오해',seconds=65)
    add('그 파일들 놔둘 돈은?',f'<p class="handnote">이번에 사용한 60GB를 한 달 내내 보관한다면</p><div class="answer-number">${r["storage_month_scenario_usd"]:.2f}<span>/ 월</span></div><p class="big-sentence">network volume · $0.07 / GB / 월<br>실제 파일 크기만이 아니라 할당한 60GB 기준</p>',
        'GPU를 반납해도 남겨둔 저장소의 과금은 계속됩니다. 이번에는 모델과 실행환경을 담기 위해 60GB를 할당했습니다. 1TB 미만 공식 단가를 적용한 한 달 계산은 $4.20입니다.\n\n이전 20GB 예시의 $1.40을 그대로 사용하지 않았습니다. 실험이 끝난 뒤에는 이 volume도 삭제했습니다.',
        '공식 단가로 계산한 보관 예시. 실제 한 달 사용내역이 아니며, 저장소 종류와 할당량에 따라 달라진다',chapter='보관비',seconds=50)
    add('한 달에 7.2시간 빌린다고 치면',f'<p class="pill">월간 할당시간 가정</p><div class="answer-number">${r["gpu_and_storage_month_scenario_usd"]:.2f}<span>/ 월</span></div><p class="big-sentence">GPU 7.2시간 × $1.19 = $8.568<br>60GB 한 달 보관 = $4.20</p><p class="caption" style="margin-top:20px">기동과 설치도 7.2시간에 넣었다고 가정한 두 항목 계산</p>',
        '720시간의 1%는 7.2시간입니다. 실제 연산 이용률 1%를 임대시간으로 옮긴 값이 아닙니다. 기동과 설치를 포함한 모든 Pod 할당시간을 7.2시간으로 가정했습니다.\n\n실제 사용내역이나 TCO 손익분기는 아닙니다. 세금·임시 디스크·환율·에이전트 비용과 구매 쪽의 전기료·감가·재판매가 등은 별도입니다.',
        '가정한 GPU와 저장소 두 항목. 실제 월간 청구나 구매·임대의 총소유비용 손익분기가 아니다',chapter='감 잡는 용도',seconds=60)
    if not r.get('policies'):
        return slides
    add('GPU도 캐시처럼 남길까?','<div class="two-col rule"><div><p class="metric-label">곧 다시 쓸 것 같으면</p><p class="statement">투기적 <strong>보존</strong></p><p class="big-sentence" style="margin-top:35px">틀리면 유휴 비용을 낸다</p></div><div><p class="metric-label">당분간 안 쓸 것 같으면</p><p class="statement">투기적 <strong>반납</strong></p><p class="big-sentence" style="margin-top:35px">틀리면 다시 준비하고 기다린다</p></div></div><p class="handnote" style="margin-top:40px">다음 요청을 모르는 채로 결정한다</p>',
        'CPU·데이터베이스·Redis·LLM 캐시가 같은 구현이라는 뜻은 아닙니다. 미래 재사용의 가치와 보존비용을 비교한다는 질문을 빌려옵니다.\n\n이번 셧다운은 실행 중인 작업 취소나 모델 파일 삭제가 아닙니다. 유휴 GPU Pod만 반납합니다. 보존과 반납의 오판이 각각 돈과 지연으로 나타납니다.',
        '투기적 셧다운은 유휴 Pod의 반납. 활성 작업과 영구 데이터는 보존하며, 미래 요청을 정답지로 주지 않는다',chapter='다음 요청을 예상한다',seconds=65)
    strategy_example=table(['직전 공백','다음 간격 예상','더 켜둘 시간'],[['기록 없음','10초','40초'],['5초','7.5초','30초'],['25초','16.25초','60초']],True,widths=(32,36,32))
    add('GPU를 더 켜둘 시간은 이렇게 정했다','<div class="two-col strategy-layout"><div class="strategy-rules"><p><strong>1.</strong> 처음에는 다음 요청이<br><b>10초 뒤에 온다</b>고 가정했다.</p><p><strong>2.</strong> 새로 관측한 공백과 이전 예상을<br><b>반반 섞어</b> 다음 간격을 예상했다.</p><p><strong>3.</strong> 예상 간격의 <b>4배만큼</b> 기다리되,<br><b>최소 5초, 최대 60초</b>까지만 켜뒀다.</p></div><div><p class="caption" style="margin-bottom:12px">이번 실험에 실제로 적용한 규칙</p>'+strategy_example+'</div></div><p class="strategy-reset">그 안에 새 요청이 오면 처리한 뒤 다시 센다. 끝까지 안 오면 GPU를 반납한다.</p><p class="strategy-alternative">다른 전략의 예: 최근 30분 안에 썼다면 30분 더 보존한다. 이 규칙은 이번 실험에서 시험하지 않았다.</p>',
        '미래 요청을 아는 대신 최근 사용 간격을 단서로 삼습니다. 여기서 공백은 이전 음원을 회수한 뒤 다음 요청까지의 시간입니다. 처음 예상은 10초입니다. 다음 요청이 5초 뒤 왔다면 새 예상은 (10+5)/2=7.5초이고, 그 네 배인 30초를 다음 유예시간으로 씁니다. 이후 공백 25초를 관측하면 (7.5+25)/2=16.25초이고 네 배는 65초지만 상한 때문에 60초만 보존합니다.\n\n새 요청은 처리한 뒤 유휴 타이머를 다시 시작합니다. 작업 중에는 끄지 않습니다. 미래의 긴 공백은 미리 주지 않았습니다. 최근 30분의 사용 여부를 보는 규칙도 가능하지만 그것은 설명용 예시이고 이번 수치의 정책은 아닙니다. 이 간격 기반 휴리스틱은 긴 공백을 예상할수록 보존도 늘리므로 비용 최적 규칙으로 주장하지 않습니다. 정확한 식: EWMA 초기 10초, alpha 0.5, TTL=min(60,max(5,4×EWMA)).',
        '예측 TTL의 사전 고정 규칙. 사용 확률을 직접 계산한 모델은 아니며, 최근 사용 간격으로 유예시간을 정했다',chapter='투기적 보존의 실제 판단 기준',seconds=90)
    p=r['policies'];rows=[[NAMES[name],f'{p[name]["allocated_seconds"]:.1f}초',f'${p[name]["gpu_estimate_usd"]:.4f}',f'{p[name]["mean_latency_seconds"]:.1f}초',str(p[name]['restarts'])] for name in NAMES]
    add('GPU를 언제 끄느냐에 따라 돈과 시간이 달라졌다','<p class="caption" style="margin-bottom:14px">음악을 받고 다음 요청까지 기다리는 동안, GPU를 어떻게 관리할지 비교했다.</p>'+table(['실제 정책','보유 근사시간','비용 추정','평균 응답','재기동'],rows,True,widths=(26,22,20,20,12))+'<p class="note-line">응답 뒤 5·25·180초 쉼 · 마지막 응답 뒤 35초 관측<br>예측 TTL은 과거 think time의 EWMA × 4, 최소 5초·최대 60초</p>',
        '실제 ACE-Step 음악 네 번을 생성하고 로컬로 회수한 뒤 다음 쉼을 시작했습니다. 각 정책의 첫 모델 준비는 공통 제외하되 전체비용에는 포함합니다. 이후에는 실제 Pod를 삭제하고 새로 만듭니다.\n\n정책별 도착 시각은 다릅니다. 이전 Qwen의 고정 시각 요청열과 같은 시험이 아닙니다. 보유시간은 API를 포함한 제어기 근사이며 정확한 공급자 청구시간은 아닙니다. 정책당 한 번의 관측입니다.',
        '정책별 1회·4번 생성. 같은 횟수와 think time을 비교하는 상호작용형 합성 세션이며, 통계적 우월성을 주장하지 않는다',chapter='직접 돌린 정책 네 가지',seconds=85)
    wait_rows=[]
    for name in ('keep','delete'):
        raw=json.loads((ROOT/f'records/ace-step/policy/{name}/result.json').read_text(encoding='utf-8'))
        wait_rows.append([NAMES[name],f'{raw["responses"][1]["complete"]:.1f}초','+ 25초',f'{raw["responses"][2]["arrival"]:.1f}초'])
    add('음악을 받은 뒤 쉬고, 다음 곡을 요청했다','<div class="request-flow"><span>음원 요청</span><b>→</b><span>음원 도착</span><b>→</b><span>정해진 만큼 쉼</span><b>→</b><span>다음 요청</span></div><p class="example-label">예: 두 번째 음원을 받은 뒤 25초 쉬고, 세 번째 요청을 보낸 실제 기록</p>'+table(['정책','두 번째 음원 도착','같은 쉼','세 번째 요청'],wait_rows,True)+'<p class="request-takeaway">음악을 늦게 받으면, 쉬기 시작하는 시각도 늦어진다.<br><strong>같은 것은 요청 횟수와 쉬는 시간이다. 요청 시각은 서로 다르다.</strong></p>',
        '이 실험의 사용자는 결과를 받은 다음에 쉽니다. 두 번째 음원을 받으면 그때부터 25초를 재고 세 번째 요청을 보냈습니다. 상시 보존에서는 34.1초에 받아 59.1초에 요청했고, 즉시 반납에서는 231.0초에 받아 256.0초에 요청했습니다. 수치는 각 정책의 초기 모델 준비가 끝난 시점을 0초로 한 실제 기록입니다.\n\n따라서 모든 정책에 같은 시각의 요청을 밀어 넣은 부하 시험이 아닙니다. 같은 네 번의 생성과 5·25·180초의 쉼을 끝내는 동안 비용과 기다림이 어떻게 달라졌는지를 비교합니다. 상세 상태 전환 그림은 부록 F로 옮겼습니다.',
        '각 정책의 초기 모델 준비 완료가 0초. 응답은 원본 음원의 로컬 회수까지이며, 표시값은 소수 첫째 자리 반올림이다',chapter='이 실험에서 다음 요청을 보내는 방법',seconds=85)
    delete=p['delete'];keep=p['keep'];saving=100*(1-delete['gpu_estimate_usd']/keep['gpu_estimate_usd'])
    if saving>=0:
        insight=f'즉시 반납은 비용 {saving:.1f}% 감소<br>평균 응답은 {delete["mean_latency_seconds"]:.1f}초'
    else:
        insight=f'더 자주 반납했는데<br>비용은 {abs(saving):.1f}% 더 들었다'
    add('재기동도 돈을 내는 시간이었다',f'<p class="editorial-quote">{insight}</p><div class="thin-rule"></div><p class="big-sentence">아무 일도 안 하는 시간은 줄였지만,<br>다시 준비하는 시간이 더 많이 들었다</p>',
        '이번 합성 세션에서 즉시 반납과 상시 보존의 실제 비용을 비교한 문장입니다. 모든 부하에 적용되는 절감률은 아닙니다. 재기동하면서 장비를 빌린 시간도 비용에 들어갑니다.\n\n예측기는 평균 공백을 TTL로 바꾸는 단순 휴리스틱이며 비용 최적 정책이 아닙니다. 긴 공백을 예상한다고 그만큼 보존할 가치가 생기는 것은 아닙니다. 세션을 조금 남길지 긴 공백에 반납할지는 모델 준비비용과 함께 봐야 합니다.',
        '이번 네 번 생성·5/25/180초 쉼의 관측. 다른 유예시간과 장시간 공백, 실제 사용자 트래픽으로 일반화하지 않는다',chapter='이번에 달라진 질문',seconds=70)
    add('이럴 거면 그냥 사는 게 편하지 않을까','<p class="ownership-bridge">맞다. 임대는 큰돈을 먼저 쓰지 않는 대신,<br>다시 켜는 기다림과 관리할 일이 생긴다.</p><div class="taste-list"><p>매일 오래 돌리는 사람</p><p>게임까지 같이 하는 사람</p><p>떠오른 걸 즉시 실행하고 싶은 사람</p><p>재고와 지역을 신경 쓰고 싶지 않은 사람</p></div><p class="big-sentence accent" style="margin-top:30px">나는 가끔 쓰니까, 그 불편을 감수할 만했다</p>',
        '이런 준비와 반납 규칙까지 관리할 바에 그냥 사는 게 편하지 않냐는 반론으로 자연스럽게 넘어갑니다. 그 편의성을 돈 주고 사는 것도 합리적입니다. 임대가 소유와 완전히 같은 경험이라는 주장은 아닙니다.\n\n매일 오래 쓰거나 즉각적인 실행과 재고 걱정 없는 편의를 원하면 살 이유가 있습니다. 나는 가끔 쓰는 편이라 준비시간과 관리의 불편을 감수하는 쪽이 맞았습니다. 개인적 사용 판단이며 실제 월 사용률이나 TCO를 측정한 결론은 아닙니다.',
        '개인적 선택. 로컬 GPU의 동일 조건 성능이나 전기료·감가·재판매가를 포함한 TCO 비교는 하지 않았다',chapter='내 주장에도 범위는 있다',seconds=50)
    add('음악은 남겼고, 장비는 돌려줬다',f'<div class="two-col rule"><div><p class="metric-label">이번 ACE-Step 전체 자원비용</p><div class="metric-number">${r["total_resource_estimate_usd"]:.2f}<small>추정</small></div><p class="metric-detail">앞선 모든 실험까지 합하면 약 ${all_cost:.2f}<br>세금·에이전트 비용 제외, 청구 미확정</p></div><div><p class="metric-label">마지막에 남긴 유료 자원</p><div class="metric-number">0<small>개</small></div><p class="metric-detail">GPU Pod와 network volume 삭제<br>음원과 로그는 로컬로 회수</p></div></div>',
        '이번 비용에는 설치와 최초 준비, 새 Pod 재사용, 상주 반복, 정책 실행의 공통 준비까지 넣었습니다. 비교표에서 제외한 처음 모델 준비도 전체비용에서는 빠지지 않습니다.\n\n사용시간과 단가로 환산한 추정이며 최종 청구서가 아닙니다. 파일 회수와 검증을 끝내고 모든 실험용 GPU와 volume을 삭제했습니다.',
        '전체 자원 수명과 단가로 환산. 볼륨 시간 단위 과금과 차이 가능. 실제 서비스의 월 예산 대표값은 아니다',chapter='정리까지',seconds=50)
    add('사실 돈이 없어서 못 샀습니다','<p class="section-label">여기까지 듣고 나면 합리적으로 보이겠지만</p><h1>사실 돈이 없어서<br><em>못 샀습니다</em></h1><p class="sub">그래서 빌렸고, 궁금한 건 직접 재봤습니다</p><p class="cover-date">돈이 생기면 입장이 달라질 수 있습니다　　질문 받습니다</p>',
        '농담으로 마무리합니다. 처음에는 살 돈이 없어서 GPU를 빌렸고, 빌려 쓰면서 준비시간과 보관비, 반납 전략이 궁금해져 직접 실험했다는 이야기입니다.\n\n모든 소유자를 설득할 결론은 아니지만, 실제 음악과 원자료는 남았습니다. 부록에서는 모델 조건과 실험 범위를 구분해서 답하면 됩니다.',theme='dark cover',chapter='마지막 고백',seconds=40)
    add('이번 ACE-Step 실행 조건',table(['항목','고정 조건'],[
        ['모델','turbo 2B DiT + 4B 5Hz LM · 공식 VAE·텍스트 인코더'],['출력','60초 instrumental · 48kHz stereo · FLAC 회수'],['생성','batch 1 · seed 42 · 8 steps · thinking=True'],
        ['실행환경',f'Torch {r["torch_by_load"][0]} · 실제 LM backend: {r["backend_by_load"][0]}'],['최적화','Flash Attention·torch.compile 끔 · 공식 eager/SDPA 경로'],['기록','코드 commit·모델 revision·가중치 SHA-256·패키지 freeze']],True,numeric_columns=()),
        '정확한 코드 commit과 모델 revision은 결과 보고서에 있습니다. 사용한 가중치의 전체 SHA-256을 Hugging Face blob과 대조했습니다. 기본 저장소의 사용하지 않는 1.7B LM도 다운로드 총량에는 포함돼 있습니다.\n\n최고 속도로 튜닝한 구성은 아닙니다. 검증과 파일 회수를 넣은 이 구성의 실제 대기시간입니다.',
        '사전 설계와 원자료: docs/ace-step-experiment.md, records/ace-step/, reports/ace-step-results.json',chapter='부록 A',appendix=True)
    add('작은 Qwen 결과는 예비 실험으로 남겼다',table(['관측','이전 Qwen','이번 ACE-Step'],[
        ['실제 사용 가중치','약 3.09GB',f'약 {r["used_weight_bytes"]/1e9:.2f}GB'],['작업','짧은 텍스트','60초 음악'],['새 Pod 첫 결과 중앙값','33.2초',f'{r["cached_median_seconds"]:.1f}초'],['상주 상태의 생성','별도 조건',f'{r["resident_generation_median_seconds"]:.1f}초']],True,numeric_columns=()),
        '모델과 작업, 패키지 구성, 실행환경의 배치가 달랐습니다. 두 숫자를 나눠 모델 크기나 GPU의 인과효과로 설명하지 않습니다.\n\n작은 작업에서 확인한 기동성을 큰 음악 모델에 그대로 일반화하면 안 된다는 점 때문에 다시 실험했습니다. 음원 파일은 그 확장의 실제 결과입니다.',
        '다른 조건의 관측 비교. 크기 하나의 효과, 동일 환경의 모델 벤치마크나 로컬 성능 비교가 아니다',chapter='부록 B',appendix=True)
    add('이전 L4에서는 비용과 시간이 엇갈렸다','<div class="two-col rule"><div><p class="metric-label">삭제형의 GPU 추정 비용</p><div class="metric-number">−40.5<small>%</small></div></div><div><p class="metric-label">전체 완료시간</p><div class="metric-number copper-text">+32.7<small>%</small></div></div></div><p class="note-line">5분 간격으로 짧은 추론 두 번 · 유지/삭제 3쌍<br>비용 기준은 통과, 사전 시간기준은 실패</p>',
        '이전 L4의 텍스트 작업입니다. 비용 30% 이상 절감과 전체시간 증가 20% 이하를 동시에 원했지만 시간기준에 실패했습니다.\n\nACE-Step 결과로 바꿔 쓰지 않았습니다. 이번 정책은 응답 이후 쉼을 넣는 다른 세션이며, 모델 준비비용도 다릅니다.',
        '과거 예비 실험. 실제 사용자 trace나 ACE-Step 음악 생성의 절감률이 아니다',chapter='부록 C',appendix=True)
    add('이전의 import 최적화는 전체 작업을 늦췄다','<div class="chart-box">'+fig.storage_chart()+'</div>',
        'L4에서 의존성과 모델의 저장 위치를 바꾼 실제 9회입니다. ABC/BCA/CAB 순서로 세 Pod 블록에서 측정했습니다. 복사비용을 포함하면 임시 디스크 복사가 전체 작업을 늦췄습니다.\n\nimport만 빨라졌다고 자랑하면 사용자 대기시간의 반대를 말하게 됩니다. 이번 ACE-Step의 venv 배치도 별도 조건으로 명시했습니다.',
        '과거 L4 저장 위치 실험. 군별 3회, 파일·출력 일치. 이번 음악 모델의 배치 최적화 결과가 아니다',chapter='부록 D',appendix=True)
    same=sum(x['same_pcm_as_cold'] for x in r['audio_comparisons'])
    add('동일 seed의 음원도 따로 검증했다',f'<div class="row baseline"><div class="huge accent">{same}<small>/ 4</small></div><p class="big-sentence" style="margin-left:50px">기준과 PCM hash 일치<br>최초 실행을 포함한 네 번의 관측</p></div><div class="thin-rule"></div><p class="audio-meta">새 Pod 3회차 · 같은 입력과 seed 42의 결과</p><div class="audio-demo">{alternate_audio}</div>',
        '모델 파일과 공개 API의 입력·seed를 고정했어도, 내부 LM backend의 모든 난수 상태를 통제했다고 가정하지 않았습니다. 최초 실행과 새 Pod 세 번의 PCM hash·RMSE를 따로 비교했습니다.\n\n이것은 음질 우열의 평가가 아닙니다. 차이가 난 원인을 특정 GPU 커널이나 내부 RNG 하나의 효과로 결론 내리지 않습니다. 별도의 작은 합성 학습 복구는 이전 자료이며 ACE-Step 학습 재개 시험이 아닙니다.',
        '파일의 유효성·동일한 PCM·음악의 품질은 다른 기준이다. 원본 FLAC으로 검증했으며 재생은 감상용 MP3다',chapter='부록 E',appendix=True)
    add('실제 GPU 보유 기록을 자세히 보면','<div>'+policy_timeline()+'</div><p class="caption" style="margin-top:16px">가로축은 각 세션의 경과시간. 검은 세로선은 요청 시각.<br>파랑과 갈색 모두 GPU를 빌려둔 시간이며, 회색은 반납한 시간이다.</p>',
        '본편에서는 두 번째 결과 이후 25초 쉰 예로 설명했습니다. 이 그림은 네 번의 전체 기록입니다. 각 행의 0초는 해당 정책의 첫 모델 준비 완료입니다. 회색으로 지내는 동안 돈을 아낄 수 있지만 갈색 재기동 구간에서도 장비를 빌린다는 점을 봅니다.\n\n요청은 각자의 이전 응답 이후에 들어오므로 검은 선들이 서로 맞지 않습니다. 같은 벽시계 시각의 요청열을 비교한 것은 아닙니다. 근거: records/ace-step/policy의 상태 전환 기록.',
        '실제 상태 전환 기록. 정책별 요청 시각이 다르며, 공통 최초 준비는 0초 이전으로 전체비용에는 포함했다',chapter='부록 F',appendix=True)
    add('숫자가 수상할 때 볼 곳','<div class="source-list"><a href="https://runpod-gpu-notes-20261018.coolspeed.chatgpt.site/" target="_blank" rel="noopener noreferrer">블로그와 음원, 원자료 모음</a><p>ACE-Step: reports/ace-step-results.md / .json</p><p>사전 설계: docs/ace-step-experiment.md</p><a href="https://docs.ceph.com/en/squid/architecture/" target="_blank" rel="noopener noreferrer">Ceph 공식 아키텍처 · RADOS와 세 인터페이스</a><a href="https://docs.runpod.io/storage/s3-api" target="_blank" rel="noopener noreferrer">RunPod S3 호환 API 문서</a><a href="https://www.runpod.io/blog/global-volumes-arent-network-volumes" target="_blank" rel="noopener noreferrer">RunPod: network volume과 Global Volume의 차이</a></div>',
        '1,200만원과 99%는 개인적 구매·사용 가정이고, 월 비용은 Pod 할당시간과 60GB 보관의 계산 예입니다. 같은 조건의 로컬 GPU 비교와 총소유비용 분석은 하지 않았습니다.\n\n새 Pod와 정책은 작은 표본입니다. 시간대와 물리 호스트, 공급자 캐시를 통제하지 못했고 재고를 보장하지 않습니다. 음원 파일의 유효성과 음질 평가도 다릅니다. 전체 조건과 원자료는 블로그에서 본인 계정으로 확인할 수 있습니다.',
        '기존 본인 전용 Sites에 게시. HTML의 도표·노트·음원은 파일에 포함하며 외부 라이브러리가 필요 없다',chapter='부록 G',appendix=True)
    slides=expand_main(slides,r,table)
    assert len(slides)==MAIN_COUNT+APPENDIX_COUNT and sum(not s['appendix'] for s in slides)==MAIN_COUNT
    return slides
