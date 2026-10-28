# 5090을 사는 대신, RunPod GPU를 빌려서 실험하기

기본 실험의 설계는 [실험계획.md](실험계획.md), 당시 Qwen 모델과 이미지 설정은 [experiment.json](experiment.json)에 있다. ACE-Step 재검증은 [별도 설계와 계획](docs/ace-step-experiment.md)을 따른다.

## 블로그와 발표

현재 이야기는 ACE-Step 1.5 음악 생성을 중심으로 [5090은 안 샀다. 대신 빌려서 놀았다](blog.html)와 [HTML 슬라이드 42장](slides.html)에 담았다. 본편 35장과 질의응답용 부록 7장이다. [발표 흐름](reports/ace-talk.md)을 함께 제공한다.

공식 turbo 2B DiT와 4B 5Hz LM으로 실제 60초 음악을 생성했다. 빈 저장소의 첫 준비, 새 Pod의 캐시 재사용 3회, 상주 상태의 추가 생성, 유휴 GPU의 실제 보존·반납 네 정책을 구분한다. 새 Pod의 첫 음원 회수는 201.8·165.9·178.6초였다. [실측 결과](reports/ace-step-results.md), [수치 JSON](reports/ace-step-results.json), [계측 해석과 한계](docs/ace-step-interpretation.md), 원자료 `records/ace-step/`를 제공한다.

이번 재실행은 총 23회 생성했고, 모든 음원을 로컬로 회수·검증했다. GPU와 network volume을 모두 삭제했으며, 전체 자원비용은 약 $1.27 추정이다. [전달·검수 기록](reports/ace-delivery.json)에 게시와 바탕화면 복사본 확인을 남겼다.

음원 일부는 HTML 안에 MP3로 포함한다. 계측과 검증은 원본 FLAC 기준이며, 모델 파일의 일치와 PCM의 재현 여부를 따로 기록한다. 이전의 작은 합성 학습 복구는 ACE-Step 학습·LoRA 재개 시험이 아니다.

현재 글과 슬라이드는 이 폴더에서 다음 명령으로 다시 만든다. 공개된 보고서·원자료·감상용 음원을 읽으며 유료 자원을 생성하지 않는다. 저장소 루트에서 먼저 `cd hands-on/02-runpod-as-near-local`로 이동한다.

```powershell
python -m pip install -r requirements.txt -r requirements-authoring.txt
python scripts/build_ace_content.py
```

`python scripts/summarize_ace.py`는 모든 생성 원본을 다시 해독해 결과를 재집계하는 별도 명령이다. 이 명령에는 원 실험의 `private/ace-audio/` 전체 파일이 필요하다. 공개 저장소에는 보고서, 측정 JSON·로그, 대표 FLAC과 감상용 MP3를 포함했고, 로컬 비공개 디렉터리와 모델 가중치는 포함하지 않았다. HTML 재생성과 열람에는 해당 비공개 파일이 필요하지 않다.

Git 체크아웃이 사전 기록한 소스·데이터 hash를 바꾸지 않도록 `.gitattributes`에서 줄바꿈 자동 변환을 껐다. 공개 폴더 구조를 만들면서 실험 당시의 코드·원자료는 바꾸지 않았다.

원문은 `story/ace-blog.template.html`과 `story/ace-policy-section.template.html`, 슬라이드 내용은 `scripts/ace_slides.py`에 있다. 실제 유료 실험의 실행 파일은 `ace_control.py`와 `ace_policy_experiment.py`다. 이미 있는 ledger와 원자료를 덮어쓰지 않으므로 완료한 실행을 무심코 다시 시작할 수 없게 했다.

## 이전 Qwen과 정책 예비 실험

RTX5090을 실제로 새로 할당한 추가 실험의 첫 결과는 준비물 재사용 3회에서 31.9·33.2·40.2초였다. [사전 설계](docs/story-experiment.md), [결과 보고서](reports/story-results.md), [수치 JSON](reports/story-results.json), `records/story/`에 근거를 보존했다. 최초 준비와 재사용은 다른 시나리오이며, 로컬 GPU와의 성능 비교는 아니다.

ACE-Step 이전 버전의 원문은 `story/blog.template.html`과 `story/speculative-section.template.html`에 보존했다. `build_story_content.py`는 그 이전 버전을 만드는 스크립트이므로 현재 글에는 위의 `build_ace_content.py`를 사용한다.

GPU를 잠시 보존할지 미리 반납할지 정하는 [추가 정책 실험 설계](docs/speculative-gpu-experiment.md), [결과](reports/speculative-results.md), [수치 JSON](reports/speculative-results.json)을 제공한다. 네 정책의 실제 RTX5090 실행과, 실측 시간으로 보정한 합성 요청 재생은 구분한다. 원자료는 `records/speculative/`에 있다.

## 2026-10-24 추가 실험

발표 준비를 위해 [20 → 10 → 5 → 2 아이디어 선정](추가실험-아이디어선정.md)을 거쳐 저장 위치별 준비시간과 학습 중단 후 새 Pod 복구를 실제 실행했다. [추가 결과 보고서](reports/followup-results.md), [결과 JSON](reports/followup-results.json), [20분 발표 구성안](reports/발표구성안.md)에 결과와 발표 흐름을 정리했다. 도표는 `reports/figures/followup/`의 PNG·SVG로 제공한다.

- 실험01: [설계](docs/followup/실험01-설계.md), [계획](docs/followup/실험01-계획.md)
- 실험02: [설계](docs/followup/실험02-설계.md), [계획](docs/followup/실험02-계획.md)
- [실행 기록과 계획 대비 차이](docs/followup/실행기록.md), 원자료 `records/followup/`

의존성을 임시 디스크로 복사하면 import는 빨라졌지만, 복사비용을 포함한 한 번의 작업은 더 느렸다. 작은 Transformer의 전체 상태 복구는 3개 seed 모두 무중단과 정확히 일치했다. 가중치만 복구한 군은 달랐다. 초기 실패를 포함한 추가 추정 비용은 약 $0.253이며 확정 청구는 아니다. 실험용 Pod·network volume은 모두 삭제했다.

## 2026-10-18 기본 실험

2026-10-18 기본 범위 실험을 완료하고 모든 실험용 Pod와 network volume을 삭제했다. 실측 결과와 한계는 [결과 보고서](reports/results.md), 상세 수치는 [결과 JSON](reports/results.json)에 있다. 비교 당시 고정 설정은 [동결 설정](records/frozen-inference-config.json), 모델 출처·hash는 [모델 manifest](manifests/model.json)에 보관했다.

RunPod API 사용법과 캐시 위치는 [로컬 API 참고 문서](docs/runpod-api.md)에 있다. 공식 API 명세와 문서 원문은 `cache/runpod-api/`에 저장하며 `python scripts/cache_api_docs.py`로 준비한다.

## 사전점검

```powershell
python -m pip install -r requirements.txt
python scripts/preflight.py
```

이 명령은 조회만 하며 유료 자원을 생성하지 않는다. GPU 가격은 `cache/gpu-prices.json`에 24시간 캐시한다. 명시적 갱신은 `python scripts/preflight.py --refresh-prices`로 한다. 캐시에 포함된 재고 상태는 조회 당시의 참고값이며 사전점검에서는 현재 재고를 별도로 조회한다.

로컬 `.env`에 다음 변수를 채운다. 값은 Git에 넣지 않는다.

```dotenv
RUNPOD_API_KEY=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

뒤의 두 변수는 RunPod S3 API Keys에서 발급하는 별도 자격증명이다. 일반 RunPod API 키를 대신 넣지 않는다.

실험용 SSH 키는 `private/`에 자동 생성하고 공개키만 Pod에 전달한다. 콘솔에 SSH 키를 수동 등록할 필요는 없다. `.env`와 SSH 비밀키는 GPU Pod에 전송하지 않는다.

최초 연결 확인 기록은 [사전점검 보고서](reports/preflight.md)에 있다. 이후 S3 연결과 GPU 실행을 완료했으며, 최종 상태는 [실행 결과](reports/results.md)를 참고한다.

## GitHub 공개본의 범위

- `.env.example`에는 변수 이름만 있다. 실제 API 키는 `.env`에 로컬로 보관하고 커밋하지 않는다.
- SSH 비밀키, 계정 자격증명, 모델·환경 캐시, Sites 배포용 체크아웃은 제외했다.
- 과거 측정 JSON의 로컬 경로와 사전 소스 hash는 당시 기록을 보존한 것이다.
- 유료 실험 스크립트와 HTML 작성 스크립트를 구분한다. 발표 자료를 열거나 다시 만드는 작업에는 GPU 임대가 필요 없다.
- 기존 측정값은 2026년 10월 실험 당시의 관측이며, 현재의 재고·가격·성능을 보장하지 않는다.
