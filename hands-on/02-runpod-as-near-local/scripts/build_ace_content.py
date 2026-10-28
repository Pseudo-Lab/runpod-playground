"""Build the ACE-Step longform article and self-contained HTML presentation."""
import base64
import html
import json
import re

from ace_slides import make_slides,NAMES,MAIN_COUNT,APPENDIX_COUNT
from runpod_api import ROOT

def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))

def main():
    r=read('reports/ace-step-results.json')
    first=read('reports/results.json');follow=read('reports/followup-results.json')
    legacy=first['provider_total_estimate_before_tax_usd']+follow['cleanup']['pod_runtime_cost_estimate_usd']+follow['container_disk_estimate_usd']+follow['cleanup']['network_volume_estimate_usd']
    legacy+=read('reports/story-results.json')['total_resource_estimate_usd']+read('reports/speculative-results.json')['total_resource_estimate_usd']
    all_cost=legacy+r['total_resource_estimate_usd']
    encoded=base64.b64encode((ROOT/r['audio_demo']['mp3']).read_bytes()).decode()
    audio=f'<audio controls preload="metadata" src="data:audio/mpeg;base64,{encoded}" aria-label="실제로 생성한 60초 ACE-Step 음악">이 브라우저에서는 음악을 재생할 수 없습니다.</audio>'
    alternate_encoded=base64.b64encode((ROOT/r['audio_demo']['alternate_mp3']).read_bytes()).decode()
    alternate_audio=f'<audio controls preload="metadata" src="data:audio/mpeg;base64,{alternate_encoded}" aria-label="새 Pod 3회차의 60초 ACE-Step 음악">이 브라우저에서는 음악을 재생할 수 없습니다.</audio>'
    waveform=(ROOT/'reports/figures/ace-waveform.svg').read_text(encoding='utf-8')
    audio_block='<figure class="measurement audio-proof">'+waveform+audio+'<figcaption>실제로 생성해 회수한 60초 instrumental. 원본은 48kHz stereo FLAC이며, 여기에는 감상용 MP3를 넣었다. 자동 재생은 하지 않는다.</figcaption></figure>'
    rows=[]
    for i in (1,2,3):
        m=read(f'records/ace-step/cached-{i}/measurement.json');rd=read(f'records/ace-step/cached-{i}/ready.json')
        rows.append(f'<tr><td>{i}</td><td>{rd["request_to_ready_seconds"]:.1f}초</td><td>{m["intent_to_collected_seconds"]:.1f}초</td><td>{m["generation_seconds"]:.1f}초</td></tr>')
    seconds=r['cached_median_seconds'];minutes=int(seconds//60);remaining=seconds-minutes*60
    warm=(f'중앙값은 약 {minutes}분 {remaining:.0f}초였다. 작은 모델의 33초를 이번에도 기대했다면 꽤 다르게 느껴질 숫자다. '
        '장비는 먼저 도착했지만 음악을 만들 준비까지는 일이 더 남아 있었다. '
        '모델을 다시 받지 않는다는 장점은 확인했지만, 이미 GPU 메모리에 올라간 로컬 모델과 똑같이 즉시 시작하는 것은 아니었다.')
    comparisons=r['audio_comparisons'];same=sum(x['same_pcm_as_cold'] for x in comparisons)
    if same==len(comparisons):
        repro='이번에 같은 입력과 seed로 생성한 최초 실행과 새 Pod 세 번에서는 PCM hash까지 일치했다. 장비 ID가 바뀐 뒤에도 이 설정에서 같은 waveform을 관측한 것이다. 그렇다고 모든 프롬프트와 모든 backend, 향후 패키지 버전에서도 같다는 보장은 아니다. 관측한 네 번의 재현으로 범위를 한정했다.'
    else:
        repro=(f'최초 실행을 포함한 네 번 가운데 PCM hash가 기준과 일치한 것은 {same}번이었다. '
            '동일 입력과 seed가 모든 GPU 실행에서 bitwise 일치를 보장하지는 않았다. '
            '샘플별 hash와 파형의 RMSE를 원자료에 남겼고, 유효한 음악을 생성했다는 확인과 정확한 waveform 재현은 나눠 적었다.')
    policies=r['policies'];policy_rows=''.join(f'<tr><td>{NAMES[name]}</td><td>{p["allocated_seconds"]:.1f}초</td><td>{p["mean_latency_seconds"]:.1f}초</td><td>{p["max_latency_seconds"]:.1f}초</td><td>{p["restarts"]}회</td></tr>' for name,p in policies.items())
    p=policies['predict'];f=policies['fixed20'];k=policies['keep'];d=policies['delete']
    observation=(f'이 세션에서 상시 보존의 평균 응답은 {k["mean_latency_seconds"]:.1f}초였고, '
        f'보유 근사시간은 {k["allocated_seconds"]:.1f}초였다. 고정 20초 정책은 각각 '
        f'{f["mean_latency_seconds"]:.1f}초와 {f["allocated_seconds"]:.1f}초, 예측 TTL은 '
        f'{p["mean_latency_seconds"]:.1f}초와 {p["allocated_seconds"]:.1f}초였다. '
        '보존하는 시간이 줄었다는 말만으로 결과가 더 편해졌다고 할 수는 없었다.')
    change=100*(d['gpu_estimate_usd']/k['gpu_estimate_usd']-1)
    if change>0:
        delete=(f'특히 즉시 반납은 더 자주 장비를 돌려줬는데도, 이번 세션의 추정 비용은 상시 보존보다 {change:.1f}% 더 들었다. '
            f'평균 응답도 {d["mean_latency_seconds"]:.1f}초였다. '
            '아무 일도 하지 않는 구간을 줄였다는 사실과 전체 임대시간이 줄었다는 사실이 같지 않았다. '
            '이 요청 패턴에서는 되돌아오는 준비비가 절약한 공백을 잠식했다.')
    else:
        delete=(f'즉시 반납은 상시 보존보다 추정 비용을 {abs(change):.1f}% 줄였다. '
            f'대신 평균 응답은 {k["mean_latency_seconds"]:.1f}초에서 {d["mean_latency_seconds"]:.1f}초로 달라졌다. '
            '이 절감률은 이번 네 번 생성과 정해진 쉼에서 나온 값이다. '
            '매번 반납하면 언제나 이 비율로 아낀다는 약속은 아니다.')
    policy=(ROOT/'story/ace-policy-section.template.html').read_text(encoding='utf-8')
    for key,value in {'ace_policy_rows':policy_rows,'ace_policy_observation':observation,'ace_delete_comparison':delete}.items():policy=policy.replace('{{'+key+'}}',value)
    values={'weight_gb':f'{r["used_weight_bytes"]/1e9:.2f}','download_gb':f'{r["downloaded_checkpoint_artifact_bytes"]/1e9:.2f}',
        'peak_cuda_gib':f'{r["peak_cuda_allocated_bytes"]/2**30:.1f}',
        'cold_e2e':f'{r["cold_intent_to_collected_seconds"]:.1f}','install':f'{r["cold_bootstrap"]["install_seconds"]:.1f}',
        'download':f'{r["cold_bootstrap"]["download_seconds"]:.1f}','audio_block':audio_block,
        'cached_median':f'{r["cached_median_seconds"]:.1f}','cached_rows':''.join(rows),'warm_interpretation':warm,
        'resident_generation':f'{r["resident_generation_median_seconds"]:.1f}','resident_roundtrip':f'{r["resident_roundtrip_median_seconds"]:.1f}',
        'month_total':f'{r["gpu_and_storage_month_scenario_usd"]:.2f}','ace_policy_section':policy,
        'audio_repro_observation':repro,'audio_comparison_block':'<details class="audio-comparison"><summary>새 Pod 3회차의 음원도 들어보기</summary><p class="caption">같은 설정과 seed로 새 Pod에서 생성한 다른 실행이다. 실제 파일의 일치 여부와 차이는 위의 관측 및 수치 JSON에 남겼다. 감상용 MP3 변환본이다.</p>'+alternate_audio+'</details>',
        'ace_cost':f'{r["total_resource_estimate_usd"]:.2f}','all_cost':f'{all_cost:.2f}'}
    article=(ROOT/'story/ace-blog.template.html').read_text(encoding='utf-8')
    for key,value in values.items():article=article.replace('{{'+key+'}}',value)
    assert not re.search(r'\{\{\w+\}\}',article),'Unexpanded article placeholder'
    article=article.replace('</style>','.audio-proof svg{width:100%;height:auto;max-height:180px}.article audio{width:100%;height:48px;display:block;margin-top:8px}.audio-comparison{margin:24px 0 30px;padding:18px 0;border-block:1px solid var(--line)}.audio-comparison summary{cursor:pointer;color:var(--blue);font-size:14px}@media print{audio{display:none}}\n</style>',1)
    single_audio_script='<script>document.addEventListener("play",e=>{if(e.target.tagName==="AUDIO")document.querySelectorAll("audio").forEach(a=>{if(a!==e.target)a.pause()})},true);</script>'
    article=article.replace('</body>',single_audio_script+'</body>')
    (ROOT/'blog.html').write_text(article,encoding='utf-8')
    slides=make_slides(r,audio,all_cost,alternate_audio)
    rendered=[]
    for s in slides:
        attrs=' data-appendix="true"' if s['appendix'] else f' data-seconds="{s["seconds"]}"'
        header='' if 'cover' in s['theme'] else '<header><p class="section-label">'+s['chapter']+'</p><h2>'+s['title']+'</h2></header>'
        body=s['body'] if 'cover' in s['theme'] else '<div class="content">'+s['body']+'</div>'
        foot='<p class="footnote">'+s['foot']+'</p>' if s['foot'] else ''
        notes=''.join('<p>'+html.escape(x)+'</p>' for x in s['notes'].split('\n\n'))
        rendered.append(f'<section class="slide {s["theme"]}" data-title="{html.escape(s["title"],quote=True)}" data-chapter="{s["chapter"]}"{attrs}>{header}{body}{foot}<aside class="speaker-notes">{notes}</aside></section>')
    template=(ROOT/'deck/template.html').read_text(encoding='utf-8')
    head=template.split('<main id="stage"')[0];tail=template.split('</main>',1)[1]
    head=re.sub('<title>.*?</title>','<title>5090은 안 샀습니다 · ACE-Step 음악 실험</title>',head)
    head=re.sub(r'<meta name="description" content="[^"]*">',f'<meta name="description" content="ACE-Step 1.5 실제 음악 생성으로 살펴본 원격 GPU의 준비시간, 캐시와 보존·반납 정책. 본편 {MAIN_COUNT}장과 부록 {APPENDIX_COUNT}장.">',head)
    head=head.replace('</head>','<style>'+(ROOT/'deck/ace-theme.css').read_text(encoding='utf-8')+'</style></head>')
    tail=tail.replace('01 / 25',f'01 / {len(slides)}').replace('본편20장과 부록5장',f'본편 {MAIN_COUNT}장과 부록 {APPENDIX_COUNT}장')
    for before,after in [('HTML파일','HTML 파일'),('페이지별PDF','페이지별 PDF'),('슬라이드가16:9비율','슬라이드가 16:9 비율')]:tail=tail.replace(before,after)
    extra='''<script>(()=>{const stage=document.querySelector('#stage');const pauseHidden=()=>{stage.querySelectorAll('.slide:not(.active) audio').forEach(a=>a.pause())};new MutationObserver(pauseHidden).observe(stage,{subtree:true,attributes:true,attributeFilter:['class']});document.addEventListener('keydown',e=>{if(e.target.closest&&e.target.closest('audio'))e.stopPropagation()},true)})();</script>'''
    deck=head+'<main id="stage" class="stage" aria-label="ACE-Step 음악 생성과 GPU 임대 발표">'+''.join(rendered)+'</main>'+tail
    deck=deck.replace('</body>',extra+'</body>')
    (ROOT/'slides.html').write_text(deck,encoding='utf-8')
    print(json.dumps({'blog_bytes':len(article.encode()),'slides':len(slides),'main':MAIN_COUNT,'appendix':APPENDIX_COUNT,'ace_cost_usd':r['total_resource_estimate_usd'],'all_cost_usd':all_cost},ensure_ascii=True))

if __name__=='__main__':main()
