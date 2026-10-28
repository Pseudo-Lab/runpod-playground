# 2. RunPod을 로컬 GPU의 대안으로 쓸 수 있을까?

- 작성자: coolspeed
- 리뷰어: 미정
- 상태: 완료
- 실행 확인일: 2026-10-24 (최종 자원 정리 확인 포함)
- 관련 Issue / 주간 기록: 미등록
- 발표 자료: [HTML 슬라이드](slides.html) — 본편 35장 + 부록 7장, [발표 흐름](reports/ace-talk.md)
- 블로그: [5090은 안 샀다. 대신 빌려서 놀았다](blog.html)

## 확인하려는 질문

가끔 모델을 돌리는 개인 사용자라면 GPU를 구매하는 대신 필요할 때만 빌려도 쓸 만할까요? ACE-Step 1.5로 실제 60초 음악을 만들며, **첫 준비와 캐시 재사용에 걸리는 시간**, **모델을 올려둔 뒤의 반복 생성 시간**, **쉬는 동안 GPU를 언제 반납할지에 따른 비용과 대기시간**을 확인했습니다.

빈 저장소에서의 첫 실행, 기존 network volume을 연결한 새 Pod 3회, 같은 Pod의 추가 생성 3회를 구분했습니다. 보존 정책은 상시 보존·즉시 반납·고정 20초 TTL·과거 사용 간격 기반 예측 TTL을 비교했습니다. 로컬 5090과 직접 비교한 성능 시험이나 구매·임대의 전체 소유비용 비교는 아닙니다.

성공 여부는 음원을 로컬로 회수하고 파일·PCM과 가중치 hash를 검증했는지, 준비·생성·회수 시간을 구분했는지로 확인했습니다. 정책 결과가 예상과 달라도 기록했습니다. 사전 조건은 [ACE-Step 설계·계획](docs/ace-step-experiment.md)에 있습니다.

## 준비 환경

| 항목 | 실제 실험 조건 |
| --- | --- |
| Runpod 제품 유형 | GPU Pods + network volume + S3 호환 API |
| GPU 종류와 개수 | RTX 5090 × 1, EU-RO-1, 동시 GPU 최대 1개 |
| 컨테이너 이미지·태그 | `runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04` |
| 고정 이미지 digest | `sha256:cb154fcca15d1d6ce858cfa672b76505e30861ef981d28ec94bd44168767d853` |
| 주요 라이브러리 | 공식 uv.lock, uv 0.13.5, 실행 환경 Torch 2.10.0+cu128, 공식 nano-vllm 기반 LM 실행 |
| 모델 | ACE-Step 1.5 turbo 2B DiT + 4B 5Hz LM + 공식 VAE·Qwen3 텍스트 인코더 |
| 생성 조건 | 60초 instrumental lo-fi jazz hip-hop, batch 1, seed 42, 8 diffusion steps, thinking=True |
| 필요한 스토리지 | 전용 60GB network volume; 실제 사용 가중치 약 14.70GB, 다운로드한 모델 아티팩트 약 18.52GB |

공식 소스는 `ace-step/ACE-Step-1.5`의 `ca1e85fe9430179831e6bc6be790c332190a3866`으로 고정했습니다. 기본 모델은 `ACE-Step/Ace-Step1.5`의 `19671f406d603126926c1b7e2adc169acbcade22`, LM은 `ACE-Step/acestep-5Hz-lm-4B`의 `0a3ec94b557aea7d508da38b31cfe7341f6ff737`입니다. 실제 패키지 목록은 [환경 기록](records/ace-step/environment.txt), 이미지 설정은 [동결 설정](records/ace-step/frozen-config.json)을 참고하세요. 동결 설정에 남은 이전 Qwen 필드와 실제 ACE-Step 실행 조건의 차이는 [계측 해석](docs/ace-step-interpretation.md)에 설명했습니다.

flash-attn·torch.compile·양자화·오프로딩은 사용하지 않았습니다. 최적화된 최고 성능을 측정한 결과는 아닙니다. 앞서 진행한 Qwen·L4·작은 Transformer 실험은 아래 별도 기록으로 구분합니다.

## 예상 사용량과 비용

2026-10-24 실험 당시 RTX 5090 견적은 시간당 $1.19였습니다. ACE-Step 실험의 자원비 예산은 $6, Pod 수명 상한은 40분, 전체 자원 만료는 4시간으로 설정하고 watchdog을 사용했습니다. GPU는 5090 또는 그보다 저렴한 범위로 제한했습니다.

실행 후 계산한 ACE-Step 전체 자원비는 **약 $1.27**입니다. 최초 설치·모델 준비와 재기동을 포함한 견적 기반 추정이며 확정 청구액이 아닙니다. 세금·에이전트 비용은 제외했고, 볼륨 과금 단위와 연속시간 환산 사이에 차이가 있을 수 있습니다. 이전 실험까지 합한 자원비 추정은 약 $2.35입니다.

발표의 60GB × $0.07/GB·월 = $4.20, GPU 월 7.2시간과 합한 약 $12.77은 사용량을 가정한 계산입니다. 실제 한 달 운영비로 측정한 값은 아닙니다. 당시 가격·재고는 현재 조건을 보장하지 않습니다.

## 실행 방법

### 공개 자료 열람·HTML 재생성

저장소를 clone한 뒤 아래 폴더로 이동합니다. `blog.html`과 `slides.html`은 브라우저에서 바로 열 수 있고, 감상용 MP3 두 곡이 각 HTML 안에 포함돼 있습니다. HTML 재생성에는 GPU나 API 키가 필요 없습니다.

```powershell
cd hands-on/02-runpod-as-near-local
python -m pip install -r requirements.txt -r requirements-authoring.txt
python scripts/build_ace_content.py
```

HTML·원자료 연결과 사전 소스 hash를 검증하려면 Node.js도 설치한 뒤 실행합니다.

```powershell
New-Item -ItemType Directory -Path private -Force | Out-Null
python scripts/verify_ace_content.py
```

본문 원문은 `story/ace-blog.template.html`과 `story/ace-policy-section.template.html`, 슬라이드 내용은 `scripts/ace_slides.py`와 `scripts/ace_story_expansion.py`에 있습니다. `build_story_content.py`는 이전 Qwen 중심 버전을 만드는 파일이므로 현재 자료에는 `build_ace_content.py`를 사용합니다.

### 계정 연결 및 실제 유료 실험 코드

계정 조회가 필요하면 `.env.example`을 `.env`로 복사하고 다음 변수에 본인의 키를 넣습니다. 실제 값은 커밋하지 않습니다.

```dotenv
RUNPOD_API_KEY=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

뒤의 두 변수는 RunPod S3 API Keys에서 발급하는 별도 자격증명입니다. 일반 RunPod API 키를 대신 넣지 않습니다. `.env`와 SSH 비밀키는 Pod로 전송하지 않으며, 실험용 SSH 키는 로컬 `private/`에서 관리하고 공개키만 Pod에 전달합니다.

```powershell
python scripts/preflight.py
```

이 명령은 조회만 하며 유료 자원을 만들지 않습니다. GPU 가격은 `cache/gpu-prices.json`에 24시간 캐시합니다. 명시적 갱신은 `python scripts/preflight.py --refresh-prices`로 합니다. 캐시된 재고는 당시 참고값이며 현재 재고는 별도로 조회합니다.

실제 유료 실행은 `scripts/ace_control.py`의 `prepare`·`repeat`·`finish` 단계와 `scripts/ace_policy_experiment.py`에 기록돼 있습니다. **공개본은 완료된 실험의 보존본이며, 새 유료 실험을 처음부터 자동 준비하는 실행 패키지는 아닙니다.** 재실행하려면 고정 소스의 `private/ace-source.tar`, 새 계정·가격·지역에 맞춘 ACE 사전점검, 새 ledger와 원자료 저장 위치를 먼저 준비해야 합니다. `preflight.py`만 실행한다고 이 준비가 모두 끝나지는 않습니다. 기존 `records/`를 덮어쓰지 말고 별도 작업 사본에서 [설계](docs/ace-step-experiment.md)와 [실행 코드](scripts/ace_control.py)를 확인하세요.

`python scripts/summarize_ace.py`는 전체 원본 음원을 다시 해독하는 별도 집계 명령입니다. 원 실험의 `private/ace-audio/` 전체가 필요합니다. 공개본에는 대표 FLAC·감상용 MP3와 모든 측정 JSON·로그를 포함했지만, 23개 원본 음원 전체나 모델 가중치는 포함하지 않았습니다. HTML 열람·재생성에는 해당 비공개 파일이 필요 없습니다.

## 결과 확인 방법

- 시간: Pod 생성 요청부터 로컬 음원 회수까지를 측정하고, 설치·다운로드·모델 초기화·생성·회수를 구분했습니다. 생성 자체의 시간과 사용자가 기다린 전체 시간은 다릅니다.
- 출력: 23회 모두 60초·48kHz·stereo FLAC인지, sample이 유한하고 RMS가 양수인지 확인했습니다. 파일 SHA-256과 PCM hash를 기록했습니다.
- 모델: 사용한 가중치 SHA-256을 고정 Hugging Face blob과 대조했습니다. 새 Pod와 같은 Pod의 재사용을 구분했습니다.
- 정책: 모델 준비 완료 상태에서 정책당 4회 생성하고 응답 후 5·25·180초를 쉬었습니다. 마지막 응답 뒤 35초를 관측했습니다. 응답이 늦으면 다음 요청도 늦어지는 방식이므로 정책별 실제 요청 도착시각은 다릅니다.
- 비용: 생성 의도부터 삭제 확인까지의 보유 근사시간에 당시 단가를 적용했습니다. 공급자의 정확한 과금시간과 동일하다고 가정하지 않았습니다.

[결과 보고서](reports/ace-step-results.md), [수치 JSON](reports/ace-step-results.json), [원자료](records/ace-step/), [계측 해석과 한계](docs/ace-step-interpretation.md)를 함께 제공합니다. `.gitattributes`로 줄바꿈 자동 변환을 꺼서 사전 기록한 소스·데이터 hash가 체크아웃 때 바뀌지 않게 했습니다.

## 결과와 시행착오

| 조건 | 실측 결과 |
| --- | --- |
| 빈 저장소에서 첫 준비 → 로컬 음원 회수 | 728.3초, 약 12분 8초 |
| 준비물을 재사용한 새 Pod 3회 → 로컬 음원 회수 | 201.8 / 165.9 / 178.6초, 중앙값 178.6초 |
| 같은 Pod의 추가 생성 3회 | 생성 자체 중앙값 6.9초, 파일 회수까지 중앙값 11.0초 |
| 상시 보존 / 즉시 반납 | 정책 구간 GPU 비용 추정 $0.09842 / $0.20004 |
| 고정 20초 TTL / 예측 TTL | 정책 구간 GPU 비용 추정 $0.17038 / $0.12082 |

짧게 쉬는 이 세션에서는 **즉시 반납이 상시 보존보다 약 103% 비쌌습니다.** 다시 띄우고 모델을 준비하는 동안에도 GPU 비용이 들었기 때문입니다. 각 정책은 1회 실행한 설명용 소표본이며, 모든 사용 패턴에서 보존이 유리하다는 뜻은 아닙니다.

예측 TTL은 응답 후 다음 요청까지의 간격을 EWMA로 추정합니다. 초기값 10초, alpha 0.5, `TTL = min(60, max(5, 4 × EWMA))`초이며 다음 요청이 도착한 뒤에만 관측값을 반영합니다. 미래 공백을 미리 알려주지 않았고, 비용 최적 정책으로 주장하지 않습니다.

같은 seed의 초기·재사용 4개 음원 중 3개는 PCM이 같았고 하나는 달랐습니다. 파일 유효성과 bitwise 재현은 별개입니다. 블라인드 음질 평가나 상용 모델과의 품질 비교는 하지 않았습니다.

Pod 0개 상태에서 S3 표식 왕복, 대형 가중치 HEAD와 64KB Range hash를 확인했습니다. 모델 전체의 S3 왕복이나 multipart 중단·재개를 시험한 것은 아닙니다. RunPod의 S3 호환 API는 같은 network volume에 접근하는 경로이며, RunPod 내부 구현이 Ceph라는 점을 확인한 것은 아닙니다.

### 이전 실험과 실패 기록

| 실험 | 확인한 내용과 한계 | 설계·결과 |
| --- | --- | --- |
| Qwen 짧은 텍스트 추론 | 새 RTX 5090의 캐시 재사용 첫 결과 31.9 / 33.2 / 40.2초. ACE와 모델·환경·부하가 달라 직접 성능 비교 불가 | [설계](docs/story-experiment.md) · [결과](reports/story-results.md) |
| L4 보존·반납 예비 시험 | 5분 간격에서 반납 시 비용 약 40.5% 절감, 전체 완료시간 약 32.7% 증가. 목표인 비용 30% 이상 절감·시간 증가 20% 이하를 동시에 충족하지 못함 | [설계](docs/speculative-gpu-experiment.md) · [결과](reports/speculative-results.md) |
| 저장 위치별 준비시간 | 임시 디스크 복사로 import는 빨라졌지만 복사비용을 포함한 한 번의 작업은 더 느림 | [설계](docs/followup/실험01-설계.md) · [계획](docs/followup/실험01-계획.md) · [결과](reports/followup-results.md) |
| 작은 Transformer 학습 복구 | 전체 상태 복구는 3개 seed에서 무중단과 일치, 가중치만 복구하면 달라짐. ACE-Step 학습·LoRA 재개 시험은 아님 | [설계](docs/followup/실험02-설계.md) · [계획](docs/followup/실험02-계획.md) · [실행 기록](docs/followup/실행기록.md) |

기본 실험은 [실험계획](실험계획.md), [결과](reports/results.md), [동결 설정](records/frozen-inference-config.json), [모델 manifest](manifests/model.json)에 남겼습니다. 후속 실험은 [20 → 10 → 5 → 2 아이디어 선정](추가실험-아이디어선정.md)을 거쳤습니다. 과거 측정 JSON의 로컬 경로와 사전 소스 hash는 당시 기록 그대로입니다.

## 실습 종료 후 정리

음원·측정값·로그를 로컬로 회수한 뒤 실험용 Pod와 network volume을 모두 삭제했습니다. **2026-10-24 최종 조회에서 Pod 0개, network volume 0개, 시간당 사용액 0**을 확인했습니다. [최종 정리 확인](records/final-storage-audit.json), [ACE 종료 기록](records/ace-step/final-cleanup.json)을 제공합니다. 이는 기록 당시의 상태입니다.

다시 실험한다면 결과를 먼저 백업하고 Pod를 삭제한 다음, 더 보관하지 않을 network volume도 별도로 삭제해야 합니다. GPU만 반납하고 volume을 남겨두면 저장소 비용이 계속 발생합니다. 이번에 사용한 RunPod S3는 이 volume의 접근 API이며 별도 AWS S3 버킷은 사용하지 않았습니다.

실제 API 키·SSH 비밀키·계정 자격증명·모델과 실행환경 캐시·Sites 게시용 체크아웃은 공개본에서 제외했습니다. `.env.example`에는 빈 변수 이름만 남겼고 `.gitignore`로 로컬 비밀 파일을 제외합니다.

## 다음에 확인할 것

- 수십 분~수시간 공백과 더 긴 사용 이력에서 보존·반납 정책을 반복 측정하기
- 정책 순서를 바꾸고 반복 횟수를 늘려 재고·호스트·시간대 변동을 확인하기
- 긴 간격일수록 무조건 오래 보존하는 휴리스틱 대신, 재기동 비용을 반영한 TTL과 비교하기
- 모델 전체의 S3 전송·복구와 multipart 중단·재개를 실제 검증하기
- 같은 조건의 로컬 GPU와 비교해 편의·대기시간·전체 비용을 따로 평가하기

## 참고 자료

- [ACE-Step 1.5 공식 소스](https://github.com/ace-step/ACE-Step-1.5) · [공식 추론 문서](https://ace-step.github.io/ACE-Step-1.5/en/INFERENCE)
- [ACE-Step 실험 설계·계획](docs/ace-step-experiment.md) · [계측 해석](docs/ace-step-interpretation.md)
- [RunPod S3 호환 API](https://docs.runpod.io/storage/s3-api) · [Pod·스토리지 가격 안내](https://docs.runpod.io/pods/pricing)
- [로컬 RunPod API 참고 문서](docs/runpod-api.md) — 공식 명세·문서 원문 캐시는 `cache/runpod-api/`
- [사전점검 기록](reports/preflight.md) · [발표·게시 검수 기록](reports/ace-delivery.json)
