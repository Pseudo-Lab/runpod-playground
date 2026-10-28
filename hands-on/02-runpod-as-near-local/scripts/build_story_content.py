"""Build the personal rental narrative and its matching standalone HTML talk."""
import html
import json
import re
from pathlib import Path

import build_slides as figures
import build_speculative_content as speculative
from runpod_api import ROOT


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def recolor(svg):
    for a,b in [('#295f4b','#294db4'),('#244137','#292d2a'),('#33996b','#5579ca'),
                ('#233b31','#282a25'),('#344d3e','#282a25'),('#3c5144','#525a58'),
                ('#dce1d4','#ddded6'),('#d8ded0','#ddded6')]:
        svg=svg.replace(a,b)
    return svg


def main():
    s=read(ROOT/'reports/story-results.json')
    previous=read(ROOT/'reports/results.json')
    follow=read(ROOT/'reports/followup-results.json')
    spec=read(ROOT/'reports/speculative-results.json')
    all_cost=previous['provider_total_estimate_before_tax_usd']+follow['cleanup']['pod_runtime_cost_estimate_usd']+follow['container_disk_estimate_usd']+follow['cleanup']['network_volume_estimate_usd']+s['total_resource_estimate_usd']
    all_cost+=spec['total_resource_estimate_usd']
    cached=[read(ROOT/f'records/story/cached-{i}/measurement.json') for i in (1,2,3)]
    rows=''.join(f'<tr><td>{i}</td><td>{read(ROOT/f"records/story/pod-cached-{i}.json")["ssh_seconds"]:.1f}초</td><td>{r["intent_to_collected_result_seconds"]:.1f}초</td></tr>' for i,r in enumerate(cached,1))
    values={'cached_median':f'{s["cached_median_seconds"]:.1f}','cold_e2e':f'{s["cold_end_to_end_seconds"]:.1f}',
        'download':f'{s["cold_download_and_lookup_seconds"]:.1f}','install':f'{s["cold_install_seconds"]:.1f}',
        'package':f'{s["cold_archive_build_seconds"]:.1f}','model_load':f'{s["cached_model_load_median_seconds"]:.2f}',
        'extract':f'{s["cached_extract_median_seconds"]:.2f}','new_cost':f'{s["total_resource_estimate_usd"]:.3f}',
        'all_cost':f'{all_cost:.2f}','cached_rows':rows,'speculative_section':speculative.blog(spec)}
    article=(ROOT/'story/blog.template.html').read_text(encoding='utf-8')
    for key,value in values.items():
        article=article.replace('{{'+key+'}}',value)
    assert not re.search(r'\{\{\w+\}\}',article)
    (ROOT/'blog.html').write_text(article,encoding='utf-8')

    slides=[]
    def slide(title,body,notes,foot='',theme='',chapter='',seconds=60,appendix=False):
        if title=='빌린 GPU는 버려도, 하던 일은 챙겼다':
            speculative.add_slides(slide,spec)
        if title=='숫자가 수상할 때 볼 곳':
            speculative.appendix(slide,spec)
            chapter='부록 F'
        index=len(slides)+1
        attrs=f' data-appendix="true"' if appendix else f' data-seconds="{seconds}"'
        header='' if 'cover' in theme else f'<header><p class="section-label">{chapter}</p><h2>{title}</h2></header>'
        content=body if 'cover' in theme else '<div class="content">'+body+'</div>'
        footer=f'<p class="footnote">{foot}</p>' if foot else ''
        p=''.join('<p>'+html.escape(x)+'</p>' for x in notes.split('\n\n'))
        slides.append(f'<section class="slide {theme}" data-title="{html.escape(re.sub("<[^>]+>","",title),quote=True)}" data-chapter="{chapter}"{attrs}>{header}{content}{footer}<aside class="speaker-notes">{p}</aside></section>')

    slide('5090은 안 샀습니다', '''<p class="section-label">가끔 GPU가 필요한 사람의 이야기</p><h1>5090은<br><em>안 샀습니다</em></h1><p class="sub">대신 빌려서 놀았습니다</p><p class="cover-date">2026.10.27　　작은 실험과 조금 긴 합리화</p>''',
        '이 발표는 내 사용 패턴에서 GPU 임대가 어떤 선택이었는지 확인한 기록입니다. 비싼 GPU를 사는 대신 필요할 때 빌려 어디까지 해볼 수 있는지 봤습니다. 마지막에는 안 산 이유도 조금 더 솔직하게 말씀드리겠습니다.\n\n기본 실험, 저장 위치와 학습 복구 실험, 실제 RTX5090 재사용 실험, 보존 정책 실험을 구분해서 보여드립니다. 근거: blog.html과 reports/의 각 결과 보고서.',theme='dark cover',chapter='도입',seconds=20)
    slide('천이백만원을 쓴다고 쳐봅시다', '''<div class="price-scene"><span class="handnote">구매 시나리오</span><div class="price">1,200<span>만 원</span></div><p class="big-sentence">비싸게 들여온 GPU 하나<br>나는 이걸 얼마나 잘 쓸까</p></div>''',
        '1,200만원은 비싼 구매 상황을 가정한 숫자입니다. 5090의 정가나 모든 제품의 시장가가 아닙니다. 확인한 컴퓨존 제품 하나의 표시가격은 약 960만원이었습니다.\n\n핵심은 내 사용법을 위해 큰 선투자를 할 것인가라는 질문입니다. 특정 제품 구매추천이나 총소유비용 손익분기는 주장하지 않습니다. 출처: 컴퓨존 상품 1213663, 2026-10-24 확인.',
        '1,200만원은 구매예산 가정. 제품별 가격은 다르며, 확인한 판매페이지 한 곳의 표시가격은 약 960만원이었다',chapter='일단 가정 하나',seconds=60)
    slide('내가 사면, 거의 놀릴 것 같았다', '''<div class="row baseline"><div class="huge accent">99<small>%</small></div><p class="big-sentence" style="margin-left:45px">실제로 잰 사용률은 아니고<br>내가 사면 이럴 것 같았다</p></div><div class="idle-bar"><span></span></div><p class="note-line">처음 며칠 신나게 돌리고<br>그다음엔 코드를 고치고, 읽고, 생각할 사람</p>''',
        '99% 유휴는 시장 통계가 아니라 내가 예상하는 개인적 사용 패턴입니다. 그래픽카드가 있다고 매일 열심히 쓸 사람이 되지는 않을 것 같았습니다.\n\n게임이나 긴 작업까지 매일 하는 분에게 이 가정을 적용하면 안 됩니다. 내게 상시 소유가 얼마나 가치 있는지를 묻는 장면입니다.',
        '99%는 개인적 예상. 실제 사용자 세션이나 구매자의 평균 GPU 유휴율을 측정한 수치가 아니다',chapter='나는 내가 안다',seconds=60)
    slide('그래서 필요할 때 빌렸다', '''<div class="two-col rule"><div><p class="metric-label">이번 실제 RTX5090 견적</p><div class="metric-number">$1.19<small>/ 시간</small></div><p class="metric-detail">EU-RO-1, On-demand<br>2026.10.24 조회</p></div><div><p class="statement">쓸 때 켜고<br>결과를 챙기고<br><strong>GPU는 지운다</strong></p><p class="note-line">모델과 준비물은 따로 보관</p></div></div>''',
        '실제 RTX5090을 빌렸고, 생성 직전 확인한 GPU 견적은 시간당 $1.19였습니다. 동시에 GPU는 한 개만 사용했습니다. 별도 정리 감시기와 자원 만료시간도 두었습니다.\n\nGPU를 지운 뒤 모델을 재사용하기 위해 별도 network volume을 연결했습니다. 단가는 모든 지역과 시점에 보장되는 가격이 아닙니다. 근거: records/story/preflight.json과 pod-*.json.',
        '실제 생성 전 단가 재확인. 이번 지역·시점의 견적이며, 상시 재고나 같은 가격을 보장하지 않는다',chapter='소유 대신 임대',seconds=50)
    slide('원격 GPU는 뜨는데 오래 걸리지 않나?', f'''<p class="handnote">나도 이게 궁금했다</p><div class="answer-number">{s['cached_median_seconds']:.1f}<span>초</span></div><p class="big-sentence">준비물을 남긴 뒤 새 5090에서<br>요청부터 첫 결과 회수까지의 중앙값</p>''',
        '준비물을 남기고 GPU만 삭제한 뒤 새 RTX5090을 세 번 만들었습니다. 요청부터 결과 회수까지의 중앙값은 33.156초였습니다.\n\n0초에 뜬다는 주장은 아닙니다. 내 가벼운 실험에서는 받아들일 만하다는 판단입니다. 근거: reports/story-results.json.',
        '약 3.09GB Qwen2.5-1.5B-Instruct의 짧은 추론. 준비물 재사용 3회이며, 큰 모델·다른 지역으로 일반화하지 않는다',chapter='첫 번째 반론',seconds=50)
    slide('세 번 다 새 GPU를 받았다', f'''<table class="plain-table"><thead><tr><th>새 5090 Pod</th><th class="num">SSH 연결까지</th><th class="num">첫 결과 회수까지</th></tr></thead><tbody>{''.join(f'<tr><th>{i}</th><td class="num">{read(ROOT/f"records/story/pod-cached-{i}.json")["ssh_seconds"]:.1f}초</td><td class="num accent">{r["intent_to_collected_result_seconds"]:.1f}초</td></tr>' for i,r in enumerate(cached,1))}</tbody></table><p class="note-line">모델 재다운로드 0회<br>파일 hash와 출력 토큰은 최초 결과와 모두 일치</p>''',
        '서로 다른 ID의 새 Pod 세 개입니다. 다른 물리 호스트로 이동했는지는 확인하지 않았습니다. 생성 API, SSH, 코드 전송, 준비물 전개, import, 파일 검증, 모델 로드, 추론과 결과 회수를 포함했습니다.\n\n공급자와 OS 캐시는 비우지 않았습니다. 세 번의 관측으로 일반적인 p95를 추정하지 않습니다. 근거: records/story/cached-{1,2,3}/measurement.json.',
        '요청부터 결과 회수까지 계측. 새 Pod ID 확인, 물리 호스트 이동 미확인. 고정 모델·BF16·batch 1·greedy',chapter='실측',seconds=75)

    cold=s['cold_end_to_end_seconds'];parts=[(s['cold_install_seconds'],'의존성 설치','#294db4'),(s['cold_archive_build_seconds'],'준비물 묶기','#95aad8'),(s['cold_download_and_lookup_seconds'],'모델 받기·조회','#bb784b')]
    parts.append((cold-sum(v[0] for v in parts),'생성·실행·회수 등','#d8d8ca'))
    chart='';x=0
    for value,label,color in parts:
        w=value/cold*1400;chart+=f'<rect x="{x:.2f}" y="22" width="{w:.2f}" height="80" fill="{color}"/>';x+=w
    for i,(value,label,color) in enumerate(parts):
        xx=i*350;chart+=f'<rect x="{xx}" y="145" width="15" height="15" fill="{color}"/>'+figures.text(xx+27,162,label,24)+figures.text(xx+27,211,f'{value:.1f}초',32,'#282a25',weight=650)
    first_chart=figures.svg(chart,1400,245,'첫 준비 141.2초의 구간. 설치 78초, 묶기 14초, 모델 다운로드·조회 8.1초, 나머지는 생성·실행·회수.')
    slide('처음부터 준비하면 이야기가 다르다', f'''<div class="row baseline"><div class="metric-number">{cold:.1f}<small>초</small></div><p class="big-sentence" style="margin-left:45px">빈 저장소에서 준비해<br>첫 결과를 받을 때까지</p></div><div style="margin-top:38px">{first_chart}</div><p class="caption">이번엔 모델 받기보다 pip가 오래 걸렸다</p>''',
        '최초 준비는 141.156초였습니다. 의존성 설치 78.031초, tar 생성 13.969초, 모델 다운로드와 조회 8.113초였습니다. 나머지는 생성과 실행, 회수 등의 잔여 구간입니다.\n\n최초 준비 1회와 준비물 재사용 3회는 서로 다른 시나리오입니다. 캐시만 바꾼 무작위 비교나 로컬 GPU와의 성능 대결은 아닙니다. 근거: records/story/cold/measurement.json.',
        '최초 준비 1회, 모델 약 3.09GB. 나머지는 전체시간의 잔여값이며, 일반적인 cold-start 상한이 아니다',chapter='첫 실행은 별도',seconds=85)
    slide('나는 어차피 에이전트에 맡겨 놓는다', '''<p class="editorial-quote">코드를 짜고, 설치하고,<br>에러가 나면 다시 고치게 한다</p><div class="thin-rule"></div><p class="big-sentence">Codex나 Claude Code에 시켜두고 기다리는 내 사용법에서는<br>GPU 기동의 몇십 초도 받아들일 만했다</p>''',
        '모델이나 effort별 대기시간을 재서 비교한 결과는 아닙니다. 에이전트에 일을 맡기고 기다리는 내 사용법에서 GPU 기동시간을 어떻게 받아들이는지에 관한 판단입니다.\n\n즉시 응답이 필요한 서비스라면 기준이 다를 수 있습니다. 로컬에서도 설치시간이 똑같다고 단정한 벤치마크도 아닙니다.',
        '개인적 사용 관점. 모델·effort별 지연은 미측정이며, 실제 서비스의 지연 허용기준과 구분한다',chapter='내가 기다리는 방식',seconds=85)
    slide('로컬에는 모델 캐시가 있다고?', '''<p class="editorial-quote">GPU는 지우고<br><span class="marker">파일은 남기면 된다</span></p><p class="big-sentence" style="margin-top:50px">준비된 모델과 의존성은 network volume에<br>다음에 빌린 GPU가 같은 파일을 읽는다</p>''',
        '원격에서도 파일까지 함께 버릴 필요는 없습니다. 모델과 의존성 아카이브는 network volume에 남기고 GPU만 삭제했습니다.\n\n새 Pod는 아카이브를 /tmp에 풀고 모델은 volume에서 offline 모드로 읽습니다. 아카이브 전개 중앙값 0.260초, 모델 로드 중앙값 1.541초였습니다. 패키징 비용도 최초 준비와 전체비용에 포함했습니다.',
        '모델 재다운로드 없이 새 Pod에서 파일과 토큰의 일치를 확인. 같은 지원 지역의 volume을 재사용한 관측이다',chapter='두 번째 반론',seconds=45)
    slide('S3, 그 AWS S3 말고요', '''<div class="row baseline"><div class="huge accent">S3</div><p class="big-sentence" style="margin-left:75px">RunPod network volume의 파일에<br>S3 호환 API로 접근</p></div><div class="thin-rule" style="margin-top:60px"></div><p class="big-sentence">GPU 없이도 읽고 쓴다<br>새 Pod에는 그 저장소를 마운트한다</p>''',
        '여기서 S3는 AWS에 별도 버킷을 만들었다는 뜻이 아닙니다. RunPod network volume의 파일에 S3 호환 도구로 접근하는 경로입니다. Pod 마운트 경로와 S3 객체 경로가 대응합니다.\n\n지원 데이터센터에 volume을 만들고 같은 지역의 GPU 재고를 확보해야 합니다. 제어 API 키와 S3 키도 구분합니다. 출처: https://docs.runpod.io/storage/s3-api .',
        'RunPod S3 호환 API와 network volume의 관계. AWS S3에 별도 모델 버킷을 만들었다는 설명이 아니다',chapter='이름 때문에 생기는 오해',seconds=70)
    slide('GPU가 없어도 모델 파일은 남아 있었다', '''<div class="two-col rule"><div><p class="metric-label">S3 확인 당시 할당된 Pod</p><div class="metric-number">0<small>개</small></div><p class="metric-detail">표식 파일을 쓰고 읽음</p></div><div><p class="metric-label">저장된 모델 객체</p><div class="metric-number">3.09<small>GB</small></div><p class="metric-detail">HEAD와 64KB Range hash 검증<br>새 Pod에서는 모델 전체 hash 확인</p></div></div>''',
        'Pod가 0개일 때 S3로 표식 파일을 쓰고 읽었습니다. 모델 객체의 HEAD로 크기를 확인하고 64KB 구간의 SHA-256도 대조했습니다. 이후 새 Pod의 마운트에서 표식과 모델 전체 hash를 확인했습니다.\n\n3GB 모델 전체를 S3로 내 PC에 다운로드했다가 다시 올린 시험은 아닙니다. 근거: records/story/s3-without-pod-*.json과 cached-*/measurement.json.',
        'S3 접근과 새 Pod의 마운트 재사용을 확인했다. 모델 전체의 S3 왕복 전송이나 multipart 중단·재개는 시험하지 않았다',chapter='직접 확인한 것',seconds=55)
    slide('그 파일들 놔둘 돈은?', '''<p class="handnote">20GB를 한 달 내내 할당한다면</p><div class="answer-number">$1.40<span>/ 월</span></div><p class="big-sentence">1TB 미만 구간 $0.07 / GB / 월<br>실제 3GB 파일 크기가 아니라 할당한 20GB 기준</p>''',
        'GPU를 꺼도 저장소는 유료입니다. 1TB 미만 공식 단가를 적용하면 20GB 한 달 보관은 $1.40입니다. 실제 파일 3GB만 과금한다는 계산은 아닙니다.\n\n큰 파일을 많이 쌓아두면 비용도 커집니다. 실험 종료 후에는 volume도 삭제했습니다. 출처: https://docs.runpod.io/pods/pricing , 2026-10-24 확인.',
        '공식 network volume 단가로 계산한 예. GPU를 삭제해도 보관한 volume의 과금은 계속된다',chapter='보관비 계산',seconds=60)
    slide('한 달에 7.2시간 빌린다고 치면', '''<p class="pill">월간 할당시간 가정</p><div class="row baseline" style="margin-top:30px"><div class="answer-number" style="margin:0">$9.97<span>/ 월</span></div></div><p class="big-sentence" style="margin-top:36px">GPU 7.2시간 × $1.19 = $8.568<br>20GB 한 달 보관 = $1.40</p><p class="caption" style="margin-top:26px">기동·설치까지 7.2시간에 포함했다고 가정한 두 항목 계산</p>''',
        '720시간의 1%는 7.2시간입니다. 실제 연산 사용률을 임대시간으로 옮긴 수치가 아닙니다. 기동과 설치를 포함한 모든 Pod 할당시간이 7.2시간이라고 가정했습니다.\n\n실제 월간 사용내역이나 TCO 손익분기가 아닙니다. 임시 디스크, 세금, 환율, 에이전트 비용과 구매 쪽의 전기료·감가·재판매가 등은 별도입니다. 근거: reports/story-results.json scenario.',
        '가정: 월 720시간 중 Pod 할당 7.2시간, 20GB 한 달 보관. 세금·임시 디스크 등 별도. 실제 사용내역이나 TCO가 아니다',chapter='감 잡는 용도',seconds=75)
    slide('물론 삽질도 했다', '''<div class="row baseline"><div class="huge warm">73.6<small>초</small></div><p class="big-sentence" style="margin-left:55px">의존성을 디렉터리째<br>가져오는 데 든 시간</p></div><div class="thin-rule"></div><p class="big-sentence">import는 24.4초에서 2.3초로 감소<br>전체 작업은 32.5초에서 85.3초로 증가</p><p class="handnote" style="margin-top:25px">빨라진 부분만 자랑할 뻔했다</p>''',
        '기존 L4 실험에서 파일을 복사하니 import는 빨라졌지만 복사비용이 더 컸습니다. 이번에는 아카이브를 재사용하는 흐름으로 실제 30~40초대 결과를 얻었습니다.\n\n하드웨어와 환경, 실행 흐름도 달라졌으므로 tar 하나의 인과적 개선율로 계산하지 않았습니다. 부분 구간과 전체 대기시간을 구분해야 한다는 결과입니다. 근거: reports/followup-results.md.',
        '이전 L4의 군별 3회 중앙값. 이번 5090과 조건이 달라 두 결과의 차이를 tar 하나의 인과효과로 주장하지 않는다',chapter='안 좋게 나온 결과도 있다',seconds=75)
    slide('안 쓰는 동안 지우면 돈은 덜 들었다', '''<div class="two-col rule"><div><p class="metric-label">GPU 추정 비용</p><div class="metric-number">−40.5<small>%</small></div></div><div><p class="metric-label">전체 완료시간</p><div class="metric-number copper-text">+32.7<small>%</small></div></div></div><p class="note-line">5분 간격, 짧은 추론 두 번을 3쌍 비교<br>아낀 돈에는 다음 GPU를 기다리는 시간이 따라왔다</p>''',
        '기본 비교는 L4에서 5분 간격으로 추론을 두 번 하는 합성 패턴입니다. 유지형과 삭제형을 세 쌍 실행했습니다. 비용 절감 30% 이상은 충족했지만 전체시간 증가 20% 이하는 충족하지 못했습니다. 따라서 사전 가설은 통과하지 못했습니다.\n\n로컬 소유 대 임대가 아니라, 임대 Pod 유지 대 삭제의 비교입니다. 실제 사용자 trace나 긴 학습으로 일반화하지 않습니다. 근거: reports/results.json.',
        '이전 L4의 5분 합성 패턴 3쌍. GPU 비용 추정이며 저장소·세금·에이전트 비용 별도. 원래 시간기준은 미충족',chapter='기다림은 생긴다',seconds=70)
    slide('빌린 GPU는 버려도, 하던 일은 챙겼다', f'''<div class="timeline-small">{recolor(figures.timeline())}</div><div class="row spread" style="margin-top:4px"><p class="big-sentence">전체 상태 복구<br><strong class="accent">3개 seed 모두 파라미터 오차 0</strong></p><p class="caption">가중치만 복구하면 다른 학습 궤적<br>평가 loss는 오히려 더 낮았음</p></div>''',
        '약 30.6만 파라미터인 작은 Transformer의 합성 학습입니다. 120 step 학습 중 73 step에서 종료하고 Pod를 삭제했습니다. 새 Pod에서 마지막 확정 체크포인트인 60 step을 읽고 13 step을 다시 계산했습니다.\n\n가중치·optimizer·scheduler·난수·데이터 진행 상태를 복원하면 세 seed 모두 무중단과 일치했습니다. 가중치만 복구한 쪽은 다른 학습을 했고 평가 loss는 더 낮았습니다. Qwen 1.5B를 fine-tuning한 시험은 아닙니다.',
        '작은 FP32 합성 학습, 약 30.6만 파라미터. 대형 LLM·분산학습 미검증. 가중치만 복구한 군은 여러 조건이 함께 다르다',chapter='학습도 끊어 봤다',seconds=90)
    slide('살 이유가 있는 사람도 많다', '''<div class="taste-list"><p>매일 오래 돌리는 사람</p><p>게임까지 같이 하는 사람</p><p>떠오른 걸 즉시 실행하고 싶은 사람</p><p>재고와 지역을 신경 쓰고 싶지 않은 사람</p></div><p class="big-sentence accent" style="margin-top:40px">나는 가끔 깨작거리는 쪽에 가까웠다</p>''',
        'GPU 소유가 틀렸다는 주장이 아닙니다. 긴 사용시간, 게임, 오프라인 사용, 즉각적인 응답과 재고 걱정 없는 편의성은 소유의 값어치입니다.\n\n내가 가벼운 실험을 가끔 하는 사용법에서 임대로도 해볼 만한지 확인한 정도입니다. 같은 volume 지역에서 원하는 GPU가 항상 다시 배정되지는 않습니다.',
        '개인적 선택의 기준. 실제 이용률·로컬 GPU 성능·전기료·감가·재판매가를 포함한 총소유비용 비교는 하지 않았다',chapter='내 주장에도 범위는 있다',seconds=60)
    slide('실험비는 남았고, 장비는 돌려줬다', f'''<div class="two-col rule"><div><p class="metric-label">기본·후속·이번 실험 자원비용 합계</p><div class="metric-number">${all_cost:.2f}<small>추정</small></div><p class="metric-detail">캐시 재사용 실험 네 번은 약 ${s['total_resource_estimate_usd']:.3f}</p></div><div><p class="metric-label">실험 종료 후 남긴 유료 자원</p><div class="metric-number">0<small>개</small></div><p class="metric-detail">GPU Pod와 network volume 모두 삭제<br>중요 파일은 로컬로 회수</p></div></div>''',
        '작은 작업과 적은 반복수에서 나온 자원비용 추정입니다. 최초 준비와 실패한 실행도 전체비용에 포함했습니다. 세금과 에이전트 비용은 제외했으며 확정 청구액이 아닙니다.\n\n이 예산으로 긴 학습이나 서비스를 운영한다는 뜻은 아닙니다. 필요한 파일의 회수를 확인하고 Pod와 volume을 삭제했습니다. 근거: reports/의 각 결과 JSON과 cleanup 기록.',
        '사용시간과 견적단가로 환산한 추정. 세금·에이전트 비용 제외, 청구 미확정. 작은 작업의 합계이며 운영예산 대표값이 아니다',chapter='정리까지',seconds=50)
    slide('사실 돈이 없어서 못 샀습니다', '''<p class="section-label">여기까지 듣고 나면 합리적으로 보이겠지만</p><h1>사실 돈이 없어서<br><em>못 샀습니다</em></h1><p class="sub">못 사는 김에 합리화를 좀 정교하게 해봤습니다</p><p class="cover-date">돈이 생기면 입장이 달라질 수 있습니다　　질문 받습니다</p>''',
        '마무리는 가볍게 합니다. 좋은 소비철학이 먼저 있어서 안 산 것이 아니라, 못 사는 김에 실험을 붙여봤다는 농담입니다. 실험의 가치는 남기되 모든 소유자를 설득하는 절대명제로 받지 않도록 합니다.\n\n부록에는 실행 조건, 불리했던 결과의 원자료, 복구 곡선, 가정과 출처를 담았습니다. 확인한 범위와 다음 질문을 나누어 답하면 됩니다.',theme='dark cover',chapter='마지막 고백',seconds=50)

    slide('이번 실험의 조건', '''<table class="plain-table small"><tbody><tr><th>GPU / 지역</th><td>RTX5090 / EU-RO-1, $1.19/h</td></tr><tr><th>실행</th><td>최초 준비 1회, 준비물 재사용 새 Pod 3회</td></tr><tr><th>모델</th><td>Qwen2.5-1.5B-Instruct, 약 3.09GB, BF16</td></tr><tr><th>추론</th><td>batch 1, 고정 prompt, greedy, 최대 128토큰</td></tr><tr><th>환경</th><td>고정 image digest, Torch2.8.0.dev20250319+cu128</td></tr><tr><th>재사용</th><td>volume의 모델, tar로 묶은 의존성을 /tmp에 전개</td></tr><tr><th>경계</th><td>provider·OS 캐시, 물리 호스트 이동, p95 미검증</td></tr></tbody></table>''',
        '이미지 digest와 모델 revision을 고정했습니다. 최초 준비 1회와 재사용 3회는 서로 다른 사용 시나리오의 관측이며 캐시만 바꾼 무작위 비교가 아닙니다. 과거 3090과 L4 결과도 다른 조건으로 보존했습니다. 근거: records/story/preregistered.json과 각 measurement.json.',
        '사전 설계·소스 hash·모든 실행 로그 보존. 실패를 숨기거나 가정을 실험 결과로 제시하지 않았다',chapter='부록 A',appendix=True)
    slide('이전 L4 저장 위치 실험의 원자료', '<div class="chart-box">'+recolor(figures.storage_chart())+'</div>',
        'A/B/C 순서로 정렬한 실제 9개 측정입니다. 실행 순서는 ABC/BCA/CAB였습니다. 복사비용을 포함했기 때문에 import만 빨라진 상황을 숨기지 않았습니다. 근거: records/followup/storage-*/result.json.',
        '군별 3회, 서로 다른 Pod 3개. 이번 5090 아카이브 흐름과 환경이 달라 단일 요인의 개선율로 비교하지 않았다',chapter='부록 B',appendix=True)
    slide('전체 상태 복구와 가중치만 복구', '<div class="chart-box">'+recolor(figures.loss_chart())+'</div>',
        '검은선은 무중단, 파란 점선은 전체 복구, 주황 점선은 가중치만 복구입니다. 전체 복구의 곡선은 기준선과 겹칩니다. 파라미터 최대오차와 평가 loss 차이는 세 seed 모두 0입니다.\n\n가중치만 복구한 군의 재개 학습률은 0.001, 전체 복구군은 0.0005였고 데이터 순서도 달랐습니다. 여러 상태가 함께 달라 단일 원인의 효과로 해석하지 않습니다.',
        '합성 데이터의 작은 FP32 학습. 새 Pod 한 쌍에서 seed 세 개 실행. 낮은 loss와 같은 학습의 재현은 별도 기준이다',chapter='부록 C',appendix=True)
    slide('가정과 사실을 나눠 둔 부분', '''<table class="plain-table small"><thead><tr><th>표현</th><th>성격</th></tr></thead><tbody><tr><th>1,200만원</th><td>구매예산 가정. 시장가·정가 아님</td></tr><tr><th>99% 유휴</th><td>개인적 예상. 다른 사용자 실측 아님</td></tr><tr><th>월$9.97</th><td>Pod 할당 7.2시간과 20GB 보관의 두 항목 계산</td></tr><tr><th>에이전트를 기다림</th><td>개인적 작업 방식. 모델·effort별 지연 미측정</td></tr><tr><th>새 5090 첫 결과 33.2초</th><td>이번 준비물 재사용 3회의 중앙값</td></tr></tbody></table><p class="caption" style="margin-top:25px">같은 조건의 로컬 5090 성능 대결과 TCO 손익분기 분석은 하지 않았다</p>''',
        '확인한 컴퓨존 제품의 표시가격은 약 960만원이었습니다. 특정 제품의 표시가격으로만 쓰며 1,200만원을 정가로 표현하지 않았습니다. 99%도 개인적 예상입니다.\n\n월 7.2시간에는 기동과 설치도 들어간다고 가정했습니다. 세금과 임시 디스크 등은 별도입니다. 근거: reports/story-results.json과 공식 과금 문서.',
        '가격 확인: 2026-10-24. 가정을 관측값이나 사용자 전체의 통계로 제시하지 않았다',chapter='부록 D',appendix=True)
    slide('숫자가 수상할 때 볼 곳', '''<div class="source-list"><a href="https://runpod-gpu-notes-20261018.coolspeed.chatgpt.site/" target="_blank" rel="noopener noreferrer">블로그와 원자료 모음</a><p>이번 5090: reports/story-results.md / .json</p><p>기본: reports/results.md　　저장 위치·학습 복구: reports/followup-results.md</p><p>이번 사전 설계: docs/story-experiment.md</p><a href="https://docs.runpod.io/pods/pricing" target="_blank" rel="noopener noreferrer">RunPod 공식 과금 문서</a><a href="https://docs.runpod.io/storage/s3-api" target="_blank" rel="noopener noreferrer">RunPod S3 호환 API 문서</a><a href="https://www.compuzone.co.kr/product/product_detail.htm?DivNo=2043&amp;MediumDivNo=1016&amp;ProductNo=1213663" target="_blank" rel="noopener noreferrer">확인한 RTX5090 판매페이지</a></div>''',
        'HTML의 도표와 발표 노트는 파일 안에 있습니다. 온라인 출처를 열 때는 인터넷과 본인 계정이 필요합니다. GPU와 저장소의 자격증명은 파일에 넣지 않았습니다.\n\n실제 GPU 실행과 실측 보정 재생을 나눠 읽어주세요. 재생 횟수를 실제 GPU 실험 횟수로 제시하지 않았습니다.',
        '기존 본인 전용 Sites에 게시. 도표와 노트는 외부 라이브러리 없이 동작한다',chapter='부록 E',appendix=True)

    original=(ROOT/'deck/template.html').read_text(encoding='utf-8')
    head=original.split('<main id="stage"')[0]
    tail=original.split('</main>',1)[1]
    head=head.replace('<title>GPU를 껐다 켜며 알게 된 것들 · 발표</title>','<title>5090은 안 샀습니다 · 발표</title>')
    overrides='''<style>
:root{--paper:#f7f5ee;--ink:#282a25;--green:#294db4;--deep:#202422;--muted:#73776d;--line:#d9dbcf;--copper:#ab5d39}body{background:#171d1b}.slide.dark{background:#202422}.dark .section-label{color:#b8bda6}.cover h1{font-family:"Noto Serif KR",Batang,serif;font-weight:500;font-size:108px;line-height:1.35;letter-spacing:-.065em}.cover h1 em{color:#f0e2a3}.cover .sub{color:#c0c6b2;font-size:33px}.cover-date{color:#9ba38e}.cover:after{display:none}.handnote{font-family:Batang,serif;color:#294db4;font-size:29px;line-height:1.6;width:max-content;max-width:1200px;transform:rotate(-2deg);border-bottom:1px solid #8797c7;padding:0 8px 7px}.price-scene{margin-top:12px}.price{font-size:192px;font-weight:580;line-height:1.15;letter-spacing:-.08em;color:#294db4;margin:16px 0 34px}.price span{font-size:57px;margin-left:24px;letter-spacing:-.04em}.idle-bar{height:42px;background:#e2e5d8;margin:36px 0 39px}.idle-bar span{display:block;height:100%;width:1%;background:#294db4}.answer-number{font-size:178px;line-height:1.16;letter-spacing:-.08em;font-weight:550;color:#294db4;margin:17px 0 25px}.answer-number span{font-size:39px;margin-left:17px;letter-spacing:-.02em}.editorial-quote{font-family:Batang,serif;font-size:67px;line-height:1.6;letter-spacing:-.055em;margin-top:24px}.marker{background:linear-gradient(transparent 62%,#eee09a 62%);padding-bottom:2px}.timeline-small svg{max-height:370px}.taste-list{display:grid;grid-template-columns:1fr 1fr;gap:25px 55px;margin-top:20px}.taste-list p{font-size:34px;border-bottom:1px solid #d9dbcf;padding:17px 0 23px;letter-spacing:-.03em}.chart-box svg{max-height:590px}.plain-table{font-size:27px}.plain-table.small{font-size:24px}.slide:not(.cover) h2{font-size:57px}.footnote{font-size:18px}.notes-drawer{background:#25322c}.presenter-mode .presenter-only{background:#25322c}
</style>'''
    head=head.replace('</head>',overrides+'</head>')
    tail=tail.replace('본편20장과 부록5장','본편 22장과 부록 6장').replace('01 / 25','01 / 28')
    for before,after in [('HTML파일','HTML 파일'),('페이지별PDF','페이지별 PDF'),('슬라이드가16:9비율','슬라이드가 16:9 비율')]:
        tail=tail.replace(before,after)
    deck=head+'<main id="stage" class="stage" aria-label="5090 임대 실험 발표 슬라이드">'+''.join(slides)+'</main>'+tail
    assert len(slides)==28
    (ROOT/'slides.html').write_text(deck,encoding='utf-8')
    print(json.dumps({'blog_bytes':len(article.encode()),'slides':len(slides),'main':22,'appendix':6,'total_resource_estimate_usd':all_cost},ensure_ascii=False))


if __name__=='__main__':main()
