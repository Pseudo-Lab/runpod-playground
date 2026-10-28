"""Additional main-story slides for an audience new to these experiments."""
import json
from runpod_api import ROOT

def expand_main(slides,r,table):
    def insert(anchor,title,body,notes,foot,chapter,seconds=65):
        pos=next(i for i,s in enumerate(slides) if s['title']==anchor)+1
        slides.insert(pos,dict(title=title,body=body,notes=notes,foot=foot,theme='',chapter=chapter,seconds=seconds,appendix=False))
    def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
    insert('그래서 필요할 때 빌렸다','계산할 때만 요금을 내는 건 아니었다',
        '<p class="editorial-quote">GPU를 빌려둔 시간에<br>돈을 낸다</p><div class="thin-rule"></div><p class="big-sentence">코드를 고치고, 설치를 기다리고, 결과를 듣는 동안도 마찬가지다.</p><p class="note-line">시간당 $1.19라면 30분 켜두는 데 약 $0.60<br>연산한 시간만 세면 임대비용을 작게 잡게 된다</p>',
        '임대라서 자동으로 싼 것은 아닙니다. GPU를 빌려놓고 아무것도 하지 않아도 시간이 지나면 비용이 듭니다. 여기의 30분 금액은 이번 견적을 곱한 계산 예시입니다. 실제로 한 곡을 만드는 비용이라고 읽으면 안 됩니다.',
        '30분 × $1.19/시간의 계산 예. GPU 항목만이며 저장소·세금·에이전트 비용은 별도다','임대도 사용법이 중요했다')
    insert('계산할 때만 요금을 내는 건 아니었다','GPU는 빌리고, 결과를 챙긴 다음 돌려줬다',
        '<div class="process-steps"><div><strong>1</strong><h3>GPU를 빌린다</h3><p>API로 Pod를 만들고<br>SSH로 접속한다</p></div><div><strong>2</strong><h3>음악을 만든다</h3><p>저장해둔 모델과<br>실행환경을 읽는다</p></div><div><strong>3</strong><h3>결과를 챙긴다</h3><p>음원을 내 PC로 가져와<br>파일을 확인한다</p></div><div><strong>4</strong><h3>GPU를 반납한다</h3><p>다음 실험에 쓸 파일은<br>별도 저장소에 남긴다</p></div></div><p class="big-sentence" style="margin-top:55px">원격 GPU를 내 PC의 CUDA 장치처럼 연결한 것은 아니다.<br>원격 컴퓨터에서 작업을 실행하고, 결과 파일을 가져왔다.</p>',
        'RunPod API로 GPU Pod를 만들고 SSH로 작업을 실행했습니다. 결과 파일은 원격에 생긴 뒤 로컬로 회수했습니다. GPU의 수명과 모델·결과 파일의 수명을 나눈 구조입니다. 마지막 실험이 끝난 뒤에는 저장소도 정리했습니다.',
        '실제 제어 흐름: API → SSH → 음악 생성 → 원본 FLAC 회수·검증 → Pod 삭제','어떻게 써봤나',75)
    insert('이건 실제로 만든 60초 음악입니다','60초 음악을 만드는 일을 23번 반복했다',
        '<div class="run-counts"><div><strong>1</strong><p>설치부터 시작</p></div><div><strong>3</strong><p>새 GPU에서 재사용</p></div><div><strong>3</strong><p>같은 GPU에서 반복</p></div><div><strong>16</strong><p>보존 정책 비교</p></div></div><p class="big-sentence" style="margin-top:55px">매번 원본 FLAC을 내 PC로 가져왔다.<br>길이·채널·유효한 파형과 파일 hash를 확인했다.</p><p class="note-line">23개의 서로 다른 곡이라는 뜻은 아니다.<br>같은 설정으로 생성 요청을 23회 실행했다.</p>',
        '최초 준비 한 번, 새 Pod 세 번, 상주 상태 추가 세 번, 정책 네 가지에서 네 번씩 생성해 총 23회입니다. 같은 입력과 seed를 쓰므로 서로 다른 노래 23곡을 수집한 품질 평가가 아닙니다. 실제 파일을 끝까지 회수하는 작업을 반복했습니다.',
        '23회 모두 원본 FLAC 로컬 해독과 파일·PCM hash를 확인했다. 음악의 품질을 평가한 블라인드 시험은 아니다','한 번 켜보고 끝낸 실험은 아니다',65)
    rd=read('records/ace-step/cached-1/ready.json')
    rows=[[label,f'{rd[key]:.1f}초'] for label,key in [('Python import','import_seconds'),('가중치 전체 hash 검증','weight_hash_seconds'),('DiT 초기화','dit_init_seconds'),('4B LM 초기화','lm_init_seconds')]]
    insert('처음엔 음악 한 곡 받는 데 12분 걸렸다','파일이 있어도, 모델을 다시 올리는 시간은 들었다',
        '<div class="two-col rule"><div><p class="big-sentence">다시 설치하지 않고<br>모델도 다시 받지 않았다.</p><p class="note-line">그래도 실행환경을 읽고<br>GPU 메모리에 모델을 올려야 했다.</p></div><div>'+table(['새 Pod 1회차의 구간','실측'],rows,True)+'</div></div><p class="note-line">이 구간들 외에도 Pod 할당·SSH·음악 생성·파일 회수가 있다.<br>이 한 번의 전체시간은 201.8초였다.</p>',
        '새 Pod 첫 회의 실제 구간입니다. 파일 캐시가 있다고 GPU 메모리에 올라간 상태까지 남는 것은 아닙니다. 전체시간은 201.8초이며 구간 표의 합과 같지 않습니다. 검증을 위해 가중치 약 14.7GB를 전부 읽는 비용도 포함했습니다.',
        '새 Pod 1회차의 관측. 최적화한 최소 기동시간이 아니며, 네트워크·공급자 캐시는 통제하지 않았다','다운로드와 초기화는 달랐다',75)
    resident=[read(f'records/ace-step/resident-{i}/music.json') for i in (1,2,3)]
    rows=[['새 Pod에서 첫 생성','201.8초']]+[[f'같은 Pod에서 추가 {i}회차',f'{x["request_to_collected_seconds"]:.1f}초'] for i,x in enumerate(resident,1)]
    insert('모델을 올려두니, 60초 음악을 약 7초에 만들었다','한 번 켜서 이어 만들면, 기다림이 확 줄었다',
        table(['같은 GPU에서 이어서 한 일','요청부터 파일 회수까지'],rows)+ '<p class="big-sentence" style="margin-top:40px">처음 준비한 상태를 잠깐 유지할 값어치가 있었다.</p>',
        '첫 캐시 재사용 Pod에서 첫 음악을 받은 뒤 추가 세 번을 실행한 실제 순서입니다. 첫 줄은 Pod 생성부터이고 다음 줄은 모델이 이미 올라간 뒤의 요청부터입니다. 서로 다른 출발점을 의도적으로 표시해 한 번의 준비를 이어 쓰는 경험을 설명합니다. 몇 초 뒤 다음 시도를 할 거라면 매번 지울 이유가 약해집니다.',
        '같은 Pod의 실제 순서. 첫 줄에는 자원 생성·초기화가 포함되고 다음 세 줄은 이미 준비된 상태에서 시작한다','다음 요청까지 남겨둘까',65)
    insert('RunPod S3는 같은 파일에 접근하는 또 다른 문','GPU가 없어도 파일을 읽고 쓸 수 있었다',
        '<div class="evidence-steps"><div><strong>Pod 0개</strong><p>S3 API로 표식 파일을 쓰고 다시 읽었다.</p></div><div><strong>큰 가중치 파일</strong><p>HEAD로 크기를 확인하고, 64KB 구간을 읽었다.</p></div><div><strong>새 Pod</strong><p>마운트된 같은 구간의 hash와 대조했다.<br>사용 가중치 전체도 고정된 원본과 대조했다.</p></div></div><p class="note-line">GPU를 지웠는데 모델 파일까지 사라진 것은 아니었다.</p>',
        'GPU가 없는 동안 저장소에 접근할 수 있는지 실제로 시험했습니다. 큰 파일 전체를 S3로 로컬 왕복한 시험은 아닙니다. 새 Pod의 마운트 파일과 S3 Range로 읽은 구간을 대조하고 모델 전체는 Hugging Face의 고정된 blob과 SHA-256을 대조했습니다.',
        'S3 표식 왕복·HEAD·64KB Range와 이후 마운트 재사용 검증. 전체 모델 S3 왕복이나 multipart 재개는 미실시','캐시가 남았다는 증거',70)
    raw=read('records/ace-step/policy/fixed20/result.json')
    insert('GPU를 더 켜둘 시간은 이렇게 정했다','20초 뒤 껐는데, 25초 뒤 다시 필요해졌다',
        '<div class="two-col rule"><div><p class="metric-label">고정 유예시간</p><div class="metric-number">20<small>초</small></div><p class="metric-detail">두 번째 음악 뒤 기다리다 반납</p></div><div><p class="metric-label">실제로 다음 요청이 온 간격</p><div class="metric-number">25<small>초</small></div><p class="metric-detail">불과 5초 차이로 다시 기동</p></div></div><p class="big-sentence" style="margin-top:45px">그다음 음원을 받는 데는 '+f'{raw["responses"][2]["latency_seconds"]:.1f}초가 걸렸다.'+'</p><p class="note-line">조금 더 남겨둘지 결정하는 문제가 생기는 이유다.</p>',
        '고정 20초 정책의 실제 세 번째 요청입니다. 앞의 결과를 받고 약 20초 뒤 삭제를 시작했고 다음 요청은 25초 뒤 들어왔습니다. 그래서 새 Pod와 모델을 준비한 뒤 음원을 회수했습니다. 25초 간격을 정책이 미리 알았던 것은 아닙니다. 결과를 보고 25초로 최적화했다고 주장하는 사례도 아닙니다.',
        '고정 20초 정책에서 실제 관측. 시간은 반올림했으며, 응답 209.1초에는 재할당·초기화·생성·파일 회수가 포함된다','보존을 너무 일찍 끝내면',75)
    insert('재기동도 돈을 내는 시간이었다','5분 쉬는 짧은 작업에서는, 반납해서 돈을 아꼈다',
        '<p class="caption" style="margin-bottom:35px">별도 시험: L4 · Qwen2.5-1.5B의 짧은 텍스트 추론 두 번 · 중간에 5분 쉼</p><div class="two-col rule"><div><p class="metric-label">GPU 추정 비용</p><div class="metric-number">−40.5<small>%</small></div></div><div><p class="metric-label">두 번째 결과까지 전체시간</p><div class="metric-number copper-text">+32.7<small>%</small></div></div></div><p class="big-sentence" style="margin-top:45px">돈은 줄었지만, 기다림도 분명 생겼다.</p><p class="note-line">미리 정한 목표: 비용 30% 이상 절감 + 시간 증가 20% 이내<br>두 조건을 모두 만족하지 못했으니 가설은 실패다.</p>',
        '음악과 다른 작은 텍스트 작업도 시험했습니다. 유지와 삭제를 L4에서 세 쌍 비교했습니다. 비용 기준은 통과했지만 시간 기준에는 실패했습니다. 짧은 원격 추론 구간만 비교하지 않고 두 작업을 끝내는 전체 흐름으로 판단했습니다.',
        'L4의 5분 합성 패턴 3쌍. ACE-Step 음악의 절감률이 아니며, 실제 사용자 호출 기록과도 다르다','반납이 유리했던 조건도 있었다',75)
    increase=(r['policies']['delete']['gpu_estimate_usd']/r['policies']['keep']['gpu_estimate_usd']-1)*100
    insert('5분 쉬는 짧은 작업에서는, 반납해서 돈을 아꼈다','모든 작업에 같은 반납 규칙을 쓸 수는 없었다',
        table(['비교한 작업','공백','즉시 반납의 GPU 비용'],[['L4 · 짧은 텍스트 두 번','5분','40.5% 감소'],['5090 · 60초 음악 네 번','5·25·180초',f'{increase:.1f}% 증가']],True,numeric_columns=(2,))+'<p class="big-sentence" style="margin-top:50px">다시 준비하는 데 드는 시간과<br>다음 사용까지의 공백을 함께 봐야 했다.</p><p class="note-line">서로 다른 작업의 관측이다. 모델·GPU·실행환경·요청 패턴이 모두 달랐다.</p>',
        '한쪽에서는 반납이 비용을 줄였고 다른 쪽에서는 늘렸습니다. 이것으로 GPU 하나나 모델 크기 하나의 인과효과를 분리할 수는 없습니다. 내가 실제로 쓸 모델과 간격에서 규칙을 검증해야 한다는 교훈입니다. 시간 지표의 범위도 달라 여기서는 같은 GPU 비용의 방향만 나란히 봅니다.',
        '각 작업 안에서의 유지 대비 삭제 GPU 비용 추정. 서로 다른 환경으로 통제된 모델·GPU 간 성능 대결이 아니다','정답 하나로 끝나지 않았다',75)
    insert('모든 작업에 같은 반납 규칙을 쓸 수는 없었다','시작을 빠르게 하려고 파일을 옮겼더니, 더 느려졌다',
        '<p class="caption" style="margin-bottom:30px">별도 L4 시험: 의존성을 network volume에서 임시 디스크로 복사했다.</p><div class="two-col rule"><div><p class="metric-label">import 자체</p><div class="metric-number">24.4 → 2.3<small>초</small></div><p class="metric-detail">읽는 구간은 빨라졌다</p></div><div><p class="metric-label">복사까지 포함한 전체 작업</p><div class="metric-number copper-text">32.5 → 85.3<small>초</small></div><p class="metric-detail">의존성 복사에 73.6초가 들었다</p></div></div><p class="big-sentence" style="margin-top:45px">빨라진 한 구간보다, 결과가 오는 순간까지를 봐야 했다.</p>',
        'L4에서 저장 위치를 세 군으로 나누고 세 Pod에 ABC, BCA, CAB 순서로 실행한 9회 시험입니다. 여기서는 둘 다 volume에 둔 A와 의존성만 복사한 B의 중앙값을 보여줍니다. 파일과 출력은 일치했습니다. 복사비용을 빼면 성공처럼 보이지만 한 번 실행하고 끝내는 전체 작업은 더 느렸습니다. ACE-Step의 배치를 통제 비교한 시험은 아닙니다.',
        'L4 저장 위치 시험 A/B의 군별 3회 중앙값. 모든 모델·반복 횟수에서 복사가 불리하다는 뜻은 아니다','준비시간도 줄여보려 했다',80)
    insert('시작을 빠르게 하려고 파일을 옮겼더니, 더 느려졌다','내가 다시 한다면 이렇게 쓸 것 같다',
        '<div class="evidence-steps"><div><strong>빌리기 전</strong><p>할 작업과 코드를 먼저 정리한다.<br>GPU를 켜놓고 고민하는 시간을 줄인다.</p></div><div><strong>연달아 실험할 때</strong><p>이미 올려둔 모델을 이어 쓴다.<br>몇 초 뒤 다시 쓸 GPU를 매번 지우지는 않는다.</p></div><div><strong>자리를 오래 비울 때</strong><p>음원과 로그를 챙기고 GPU를 반납한다.<br>다시 쓸 모델 파일은 더 저렴한 저장소에 남긴다.</p></div></div>',
        '실측을 보고 고른 나의 사용법입니다. 이 세 단계 자체를 실제 사용자 세션으로 다시 비교한 최적 정책 실험은 아닙니다. 긴 공백의 경계도 이 표본만으로 정하지 않았습니다. 파일과 GPU의 수명을 나누고 짧은 반복에서는 준비 상태를 재사용한다는 실용적인 선택입니다.',
        '실험에서 얻은 개인적 운영 원칙. 실제 사용자 트래픽에서 검증한 최적 유예시간이나 보편적 절감률은 아니다','그래서 어떻게 쓸 건가',75)
    return slides
