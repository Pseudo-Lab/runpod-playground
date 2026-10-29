# Comfy API vs Runpod Serverless — 같은 H3 워크플로 비교

- 작성자: 김진의
- 리뷰어: 미정
- 상태: 완료
- 실행 확인일: 2026-10-19
- 발표 자료: [slides.pdf](slides.pdf)
- 블로그: [Runpod Korea User Group 글](https://runpod-korea-ug.pages.dev/articles/comfy-api-vs-runpod-h3/index.html)
- 측정 코드·원본 결과: [omg-runpod-media `recipes/video/06-comfy-api-vs-runpod-h3`](https://github.com/wlsdml1114/omg-runpod-media/tree/e8faba9780914858a1ec88615d55529c2de082b2/recipes/video/06-comfy-api-vs-runpod-h3) (커밋 고정)

## 확인하려는 질문

ComfyUI 워크플로를 앱에서 API로 부를 때, Comfy API(Comfy Org의 관리형 배포, 2026-09-30 출시)에 맡기는 쪽과 Runpod Serverless에 직접 올리는 쪽은 **준비할 일, 요청 하나를 기다리는 시간, 요청당 비용**이 얼마나 다를까요?

같은 그래프·같은 GPU·같은 시드로 두 곳에서 cold 3회, warm 5회씩 요청을 보내 비교했습니다.

## 준비 환경

| | Comfy API | Runpod Serverless (직접 구축) |
| --- | --- | --- |
| 올리는 단위 | Build → Release → Deployment | Docker 이미지 → Endpoint |
| GPU | RTX PRO 6000 96GB × 1 | RTX PRO 6000 96GB × 1 |
| 워커 | min 0 / max 1 | min 0 / max 1, idle 5초 |
| 모델 위치 (약 42GB) | Comfy network storage | 비공개 Hugging Face 저장소 + Runpod 모델 캐시 |
| 요청 방식 | v2 API, 입력 파일은 assets로 업로드 | `/run`, 입력·출력 모두 base64 |
| torch | 2.12.1 | 2.9.1 |

- 워크플로: MiniMax H3 Ref2VA + Turbo4 LoRA. 5초 인터뷰 영상(1344×768, 124프레임)의 얼굴·머리를 다른 인물로 교체. ComfyUI 기본 노드 18개.
- ComfyUI 커밋 `5cc4b870`(0.41.0)으로 양쪽을 맞췄습니다. 출력 MP4에 남은 그래프를 비교해 파일 이름·저장 경로·시드 외에는 같음을 확인했습니다.
- Comfy API는 `comfy` CLI 1.22.0으로 배포했습니다.
- 모델은 공식 `Comfy-Org/MiniMax-H3` 저장소에서 받았습니다. 모델 파일과 입력 영상·사진은 이 레포와 측정 코드 저장소에 넣지 않았습니다.

## 예상 사용량과 비용

2026-10-19 각 사 가격표 기준 RTX PRO 6000 시간당 단가는 Runpod $3.49, Comfy API $4.54입니다(H100·H200·B200도 모두 정확히 1.3배). 저장 공간은 Comfy API $0.20/GB·월, Runpod Network Storage $0.07/GB·월(1TB 미만)입니다. Comfy API는 Standard($20/월) 이상 플랜이 필요합니다.

이번 측정의 실제 청구액(2026-10-20 조회)은 Runpod 10건 $2.14, Comfy API 9건 $2.29였습니다. cold 기동·유휴 시간·저장 공간이 포함된 값이고, Comfy 구독료는 별도입니다.

## 실행 방법

측정 코드 저장소의 레시피 폴더를 따릅니다.

1. `README.md`에서 두 환경의 조건과 모델 라이선스를 확인합니다.
2. `comfy-build/`의 스펙으로 Comfy API에 Build·Release·Deployment를 만듭니다.
3. `scripts/run_matrix.py --dry-run`으로 실행 순서를 확인한 뒤 cold 3회·warm 5회를 돌립니다.
4. 결과는 `benchmark-output/`에 쌓이고, 발표·블로그의 값은 `results/runs.csv`에 있습니다.

Runpod 쪽 측정 스크립트는 작성자의 핸들러 입력 형식을 가정합니다. 직접 구축한 엔드포인트에 맞게 요청 형식을 고쳐 써야 합니다. API 키는 환경변수로 넘기고 값은 커밋하지 않습니다.

## 결과 확인 방법

- 시간: 같은 Mac에서 요청을 제출한 순간부터 완료를 확인한 순간까지(클라이언트 기준). cold는 직전에 실행 중인 워커가 0인지 확인하고 보냈습니다.
- 단계 분해: 양쪽 ComfyUI 로그의 `Prompt executed`와 샘플링 시간을 비교했습니다.
- 결과물: 16개 결과 모두 1344×768, 24fps, 124프레임인지, 같은 시드끼리 화면이 같은지 확인했습니다.

![같은 시드(42113)로 만든 결과. 위는 Runpod, 아래는 Comfy API. 12, 62, 112번째 프레임.](same-seed-runpod-vs-comfy.jpg)

## 결과와 시행착오

| | Runpod | Comfy API |
| --- | --- | --- |
| warm 중앙값 (클라이언트) | 196.3초 (195.7–250.5) | 165.1초 (164.6–167.4) |
| warm 플랫폼 실행 시간 | 189.0초 | 161.3초 |
| cold 3회 | 221.8 / 221.9 / 371.2초 | 191.3 / 193.9 / 418.8초 |
| warm 1건 계산값 (실행 시간 × 단가) | $0.183 | $0.203 |
| 실제 청구 건당 평균 | $0.214 | $0.254 |

- **샘플링은 같았습니다.** 4스텝 샘플링이 양쪽 모두 약 133초(스텝당 33초)였습니다. warm 약 30초 차이는 그 밖에서 났습니다.
- **약 9초: torch 버전(추정).** torch 2.9.1인 Runpod 이미지에서는 ComfyUI가 `working around nvidia conv3d memory bug` 우회를 켜고, 2.12.1인 Comfy API 쪽은 켜지 않았습니다. 영상 VAE가 3D 합성곱을 쓰므로 가장 유력하지만, torch를 올려 다시 재지는 않았습니다.
- **약 19초: GPU 서버 차이.** warm 5회를 처리한 워커(US-MO-2)는 ComfyUI 실행에 약 187초, 같은 요청을 다른 워커(US-NC-2)에서 다시 돌리면 168초였습니다.
- **cold는 운에 달렸습니다.** 두 곳 모두 금방 다시 뜨는 대기 자리를 들고 있어, 그 자리가 살아나면 몇십 초, 새 GPU를 잡으면 2~4분을 기다렸습니다. 3회로는 어느 쪽 cold가 빠르다고 말할 수 없고, 첫 요청은 양쪽 모두 3~7분으로 흔들릴 수 있습니다.
- **비용:** 단가는 30% 비쌌지만 생성이 빨라 warm 1건 기준 차이는 약 11%였습니다.

Comfy API 준비에서 손이 간 곳:

- `comfy build init --from-workflow`로 만든 첫 스펙의 모델이 0개였습니다. 모델 네 개는 출처(`sourceUri`)를 직접 넣어야 했고, 영상 VAE 후보로는 VAE가 아닌 다른 모드의 확산 모델이 제시됐습니다.
- `comfy build refs resolve`는 다섯 파일 모두 공식 저장소를 1순위로 찾았지만, 영상 VAE 후보에 이름만 같고 크기가 다른 파일이 섞여 있어 직접 골랐습니다.
- Release 생성 6분 35초(39.2GB 이미지), Deployment 약 4분 25초(모델 39.1GB 스테이징 약 3분 포함).

측정하면서 걸린 함정:

| 겪은 일 | 그래서 이렇게 했다 |
| --- | --- |
| Comfy 상태가 제출 2초 뒤부터 `running`이지만 실제 시작은 5분 25초 뒤인 경우도 있음 | 작업의 `started_at`으로 대기 시간을 계산 |
| 문서의 `metrics.queue_ms`가 응답에 없음 | created·started·completed 타임스탬프로 직접 나눔 |
| Comfy 출력에 입력 영상도 섞여 옴 | SaveVideo 노드(17) 출력만 저장 |
| 워커 상태 스냅샷이 약 5분마다 갱신 | 마지막 작업 30초 뒤 찍힌 스냅샷만 '0'으로 인정 |
| warm을 양쪽 cold 뒤에 몰아 두면 Runpod 워커가 식음 | 각 cold 바로 뒤에 같은 쪽 warm 5회 |

아직 확인하지 못한 것: Runpod 쪽의 같은 기준 준비 시간(엔드포인트를 미리 만들어 둠), torch 업그레이드 후 재측정, 24~48GB급 GPU로 충분한 가벼운 워크플로에서의 비교.

## 실습 종료 후 정리

- Comfy API: Deployment만 멈추면 저장 공간 과금이 계속됩니다. **Deployment와 Build를 모두 삭제**한 뒤 목록을 다시 조회해 확인합니다.
- Runpod: 엔드포인트 min 0이면 쉬는 동안 GPU 비용은 없습니다. 더 쓰지 않으면 엔드포인트와 모델 저장소를 삭제합니다.

## 다음에 확인할 것

- Runpod 이미지의 torch를 2.12.x로 올렸을 때 약 9초 차이가 사라지는지
- 가벼운 워크플로(24~48GB GPU)에서 요청당 비용 차이

## 참고 자료

- [Comfy API 출시 소개 글 (Runpod Korea User Group)](https://runpod-korea-ug.pages.dev/articles/comfy-api-launch/index.html)
- [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3)
