# 3. 8bit에서 4bit로 내리면 손해일까?

- 작성자: kimjaejeong
- 리뷰어: 미정
- 상태: 완료 (KV 캐시 양자화는 다음 실험으로 남김)
- 실행 확인일: 2026-11-07 (모든 Pod 삭제 확인 포함)
- 관련 Issue / 주간 기록: 미등록
- 발표 자료: [slides.pdf](slides.pdf)
- 결과 데이터: [results/](results/)

## 확인하려는 질문

4bit로 내리면 항상 손해라고 생각했는데, 실제로 써 본 GLM 4bit 모델은 생각보다 괜찮았습니다. 그래서 다음 네 가지를 직접 재 봤습니다.

1. 8bit는 원본과 같을까?
2. 4bit는 몇 B부터 괜찮을까?
3. 메모리가 같다면 작은 모델 원본과 큰 모델 4bit 중 어느 쪽이 나을까?
4. 4bit는 정말 빠르고 쌀까?

실험은 세 번 했습니다. 앞 실험을 보고 든 의문으로 다음 실험을 정했습니다.

| 실험 | 궁금했던 것 | 바꾼 것 |
| --- | --- | --- |
| 1 | 위 네 가지 | Qwen3.5 크기별, 원본·8bit·4bit, 쉬운 수학과 한국어 지식, 1번씩 |
| 2 | 실험 1은 문제가 쉬워서 차이가 없었던 건 아닐까? | 어려운 문제와 금융, 3번씩, Gemma 4와 MoE 모델 추가 |
| 3 | 같은 모델에서 4bit 방식만 바꾸면 달라질까? | Gemma 26B MoE를 NVFP4로, Blackwell GPU에서 |

점수가 떨어졌다고 판단한 기준은 같은 문제끼리 비교했을 때 p < 0.05인 경우입니다. 실험 1은 McNemar 검정, 실험 2와 3은 문제별 3번 평균의 짝 비교(정규근사)를 썼습니다.

## 준비 환경

| 항목 | 내용 |
| --- | --- |
| Runpod 제품 유형 | GPU Pods, Secure Cloud. Network Volume은 쓰지 않음 |
| GPU | 정확도: 48GB L40S 또는 RTX 6000 Ada ($1.09/h 전후)<br>속도: RTX 4090 ($0.89/h), L40S ($1.09/h)<br>실험 3: RTX PRO 4500 Blackwell 32GB ($0.72/h) |
| 컨테이너 이미지 | `vllm/vllm-openai:v0.32.0@sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34` |
| 모델 | Qwen3.5 2B, 4B, 9B, 27B, 35B-A3B / Gemma 4 E2B, E4B, 12B, 31B, 26B-A4B. 리비전은 [설정 파일](config/runpod_exp.yaml)에 고정 |
| 4bit 종류 | Qwen dense: cyankiwi AWQ (커뮤니티)<br>Qwen 35B MoE: Qwen 공식 GPTQ<br>Gemma dense: Google 공식 QAT<br>Gemma 26B MoE: cyankiwi AWQ (커뮤니티), NVIDIA 공식 NVFP4 |
| 필요한 스토리지 | 컨테이너 디스크 80GB |

| 실험 | 문제 | 출처와 이용 조건 |
| --- | --- | --- |
| 1 | 수학 1,319개, 한국어 지식 1,035개 | GSM8K, KMMLU (CC-BY-ND-4.0) |
| 2, 3 | 어려운 수학 400개 | HRM8K MATH Level 5 (MIT) |
| 2, 3 | 어려운 한국어 지식 585개 | KMMLU-HARD |
| 2, 3 | 금융 928개 | KMMLU-HARD 금융 과목 + allganize/financial-mmlu-ko |

문제 원문과 문항별 답은 이 저장소에 올리지 않았습니다. 스크립트가 Hugging Face에서 내려받습니다. allganize 데이터셋은 Hugging Face 페이지에서 라이선스 표시를 찾지 못했으니, 다시 쓰기 전에 확인해 주세요.

## 예상 사용량과 비용

세 실험을 합쳐 **약 $14.9**를 썼습니다. 실험 전 예산은 $30이었습니다. Pod별 합계는 RunPod 청구 내역 기준이고, 실험 3 등 집계 시점에 청구 전이던 일부는 시간과 단가로 추정했습니다.

| 실험 | 비용 | 비고 |
| --- | --- | --- |
| 1 | 약 $6.0 | 그중 $3.3은 방치된 Pod와 기동 실패 |
| 2 | 약 $8.6 | 전체에서 실험 1, 3을 뺀 근사값. 가장 비싼 조합은 Qwen 27B 4bit로 약 $3.3 |
| 3 | 약 $0.3 | NVFP4 $0.22, AWQ 속도 측정 $0.09 |

2026-11 기준 가격이며 재고와 가격은 달라질 수 있습니다. 조합별 값은 [results/cost.json](results/cost.json)에 있습니다.

## 실행 방법

아래 예시는 유료 Pod를 만듭니다. 비용을 확인하고 실행하세요.

1. 위 이미지로 Pod를 만들고 8000번 포트를 엽니다. 시작 명령은 `vllm serve` 뒤에 아래 인자를 붙입니다. 모델별 값은 [config/runpod_exp.yaml](config/runpod_exp.yaml)을 봅니다.

   ```text
   nvidia/Gemma-4-26B-A4B-NVFP4 --revision a19cfe00be84568a6867111c9a68c9c44fdcffe6
   --served-model-name exp-g4-26b-a4b-nvfp4-pro4500 --port 8000 --max-model-len 4096
   --max-num-seqs 64 --gpu-memory-utilization 0.9
   --default-chat-template-kwargs '{"enable_thinking": false}'
   --limit-mm-per-prompt '{"image": 0, "audio": 0}'
   ```

2. 평가를 실행합니다. 이름에 `TOLLGATE`가 붙은 환경변수는 원래 실험에서 쓰던 이름이며, OpenAI 호환 주소와 키를 넣으면 됩니다.

   ```bash
   cd hands-on/03-quantization-8bit-vs-4bit
   pip install -r requirements.txt

   export TOLLGATE_GATEWAY_URL=https://<podId>-8000.proxy.runpod.net
   export TOLLGATE_EXP_KEY=<키>
   export MODEL=exp-g4-26b-a4b-nvfp4-pro4500

   python scripts/quant_eval.py prepare                    # 실험 1 문제 내려받기
   python scripts/quant_hard.py prepare                    # 실험 2, 3 문제 내려받기
   python scripts/quant_hard.py run --model "$MODEL"       # 어려운 문제 3번
   python scripts/quant_bench.py run --model "$MODEL" --cost-per-hr 0.72   # 속도
   python scripts/quant_hard.py summary
   ```

원래 실험에서는 Pod 생성, 삭제와 비용 집계를 개인 프로젝트의 별도 도구로 처리했습니다. 그 코드는 여기에 없으므로 Pod는 Runpod 콘솔이나 API로 직접 관리해야 합니다. **이 폴더의 스크립트만으로 처음부터 다시 돌려 보지는 않았습니다.** 실제 실험은 같은 스크립트를 자체 LLM 게이트웨이 뒤에서 실행했습니다.

## 결과 확인 방법

- 정확도: 조합별 정답률과 8bit 대비 차이, p값
- 속도: 동시 요청 1, 16, 48개의 처리량, 첫 토큰까지 시간, 100만 출력 토큰당 비용 (256토큰 고정)

## 결과와 시행착오

표의 숫자는 정답률(%)이고 `8bit → 4bit` 순서입니다. **굵은 글씨**는 p < 0.05로 떨어진 경우입니다.

### 실험 1: 쉬운 문제

| 크기 | 수학 | 한국어 지식 |
| --- | --- | --- |
| 2B | 73.2 → 71.7 | **36.0 → 31.5** |
| 4B | 92.3 → 92.8 | **51.1 → 46.7** |
| 9B | 93.5 → 93.8 | 56.7 → 56.0 |
| 27B | 97.0 → 96.8 | 67.8 → 68.2 |

- **8bit와 원본:** 2B, 4B, 9B 모두 점수 차이가 1점 이내였고 메모리는 33~41% 줄었습니다. 27B 원본은 L40S에 올라가지 않아 비교하지 못했습니다.
- **같은 메모리:** 비슷한 메모리의 세 쌍 모두 큰 모델 4bit가 나았습니다. 예를 들어 18GB 안팎에서 한국어 지식은 9B 원본 57.5점, 27B 4bit 68.2점입니다.
- **속도와 비용:** 혼자 쓸 때 4bit가 8bit보다 약 1.6배 빨랐습니다. 동시 48개 기준 100만 출력 토큰 비용은 27B, L40S에서 $0.54에서 $0.35로 35% 낮았습니다. 9B는 4090에서 AWQ $0.10으로 L40S보다 쌌습니다.
- **GPU 제약:** 27B 4bit는 4090(24GB)에서 서빙되지 못했습니다.

### 실험 2: 어려운 문제, 3번 평균

| 모델 | 4bit | 어려운 수학 | 어려운 한국어 지식 | 금융 |
| --- | --- | --- | --- | --- |
| Qwen 2B | AWQ | **17.8 → 13.6** | 24.7 → 22.9 | **40.0 → 36.3** |
| Qwen 4B | AWQ | 52.2 → 50.8 | 28.8 → 29.3 | **50.4 → 47.7** |
| Qwen 9B | AWQ | 60.0 → 57.8 | 31.1 → 30.4 | 55.5 → 54.2 |
| Qwen 27B | AWQ | **88.9 → 86.4** | 44.5 → 43.2 | 65.6 → 66.3 |
| Gemma E2B | QAT | **48.4 → 42.3** | 19.5 → 23.9 | 45.9 → 43.9 |
| Gemma E4B | QAT | 63.2 → 62.4 | 26.0 → 24.9 | 49.0 → 50.4 |
| Gemma 12B | QAT | **79.8 → 76.3** | 33.0 → 30.1 | 61.9 → 59.9 |
| Gemma 31B | QAT | 92.6 → 92.7 | 56.3 → 54.8 | 74.2 → 72.8 |
| Qwen 35B MoE | GPTQ | 73.6 → 72.8 | 42.3 → 41.6 | 62.0 → 60.9 |
| Gemma 26B MoE | AWQ | **83.2 → 77.5** | **45.6 → 40.5** | **68.2 → 66.2** |

- 실험 1의 "9B부터 괜찮다"는 쉬운 문제에서만 맞았습니다. 어려운 수학에서는 Qwen 27B도 떨어졌습니다.
- Google 공식 4bit인 Gemma도 E2B와 12B는 수학이 떨어졌습니다. 공식판이라고 항상 안전한 것은 아닙니다.
- 한국어 지식의 작은 모델 점수는 찍기(25%) 근처라 비교 의미가 적습니다. Gemma E2B가 오른 것(19.5 → 23.9, p < 0.001)도 그렇게 봤습니다.
- MoE 두 모델은 결과가 정반대였지만 모델과 4bit 방식이 함께 달라서 원인을 나눌 수 없었습니다. 그래서 실험 3을 했습니다.

### 실험 3: 같은 모델, 다른 4bit (Gemma 26B MoE)

| 4bit | 어려운 수학 | 어려운 한국어 지식 | 금융 |
| --- | --- | --- | --- |
| AWQ (커뮤니티) | **83.2 → 77.5** | **45.6 → 40.5** | **68.2 → 66.2** |
| NVFP4 (NVIDIA 공식) | 83.2 → 83.2 | 45.6 → 44.8 | 68.2 → 67.5 |

| 같은 Blackwell GPU, 조건별 1번 측정 | AWQ | NVFP4 |
| --- | --- | --- |
| 한 요청의 생성 속도 (동시 1) | 154 tok/s | 114 tok/s |
| 전체 처리량 (동시 16) | 938 tok/s | 948 tok/s |
| 전체 처리량 (동시 48) | 1,890 tok/s | 2,155 tok/s |
| 100만 출력 토큰 비용 (동시 48) | $0.106 | $0.093 |
| 첫 기동까지 | 약 7분 | 약 10분 |

NVFP4는 이 모델에서 8bit와 차이가 없었고, vLLM 로그에서 전용 커널(FlashInfer CUTLASS)을 고른 것을 확인했습니다. 동시 48개에서는 더 많이 처리했지만 혼자 쓸 때는 AWQ가 빨랐습니다.

### 시행착오

- 작업 세션이 끊기면서 27B Pod가 2시간 넘게 방치됐습니다. 이후 실행기를 세션과 분리했습니다.
- CUDA 버전 필터를 걸면 모든 GPU가 재고 없음으로 나왔습니다. 필터를 빼고 이미지를 기본 CUDA 13 판으로 바꿨습니다.
- cu129 이미지는 torchcodec을 읽지 못해 기동에 실패했습니다.
- `RTX PRO 4500 Blackwell Server Edition`은 REST 생성 API가 받지 않았습니다. 요청 자체가 거부되므로 재고 문제와 구분해야 합니다.
- 짧은 `max_tokens`에서 한국어 지식 답이 잘려 16에서 128로 늘렸습니다.

### 해석할 때 주의할 점

- 어려운 문제의 "30B급부터"는 Gemma 31B 한 모델에 기대고 있습니다. Qwen 27B는 수학이 떨어졌고, Qwen 35B MoE는 차이가 없었지만 구조와 4bit 방식이 다릅니다.
- NVFP4와 AWQ의 차이는 모델 하나에서 본 결과입니다.
- 실험 3의 NVFP4는 Blackwell에서, 비교한 8bit는 L40S에서 쟀습니다.
- 실험 1은 temperature 0, 실험 2와 3은 temperature 0.7, top_p 0.8이라 점수를 직접 비교할 수 없습니다.
- 3번 반복 사이의 흔들림이 과제에 따라 최대 약 5점까지 났습니다. 원인은 나누어 보지 않았습니다.
- 속도는 조건별로 1번씩 쟀고, NVFP4가 동시 48개에서 더 처리한 이유도 확인하지 못했습니다.
- 처음 궁금증의 출발이었던 GLM 모델 자체는 재 보지 않았습니다.

## 실습 종료 후 정리

- Pod는 조합이 끝날 때마다 삭제했고, 2026-11-07 실험 종료 후 실험용 Pod 0개를 확인했습니다.
- Network Volume을 만들지 않았으므로 남는 스토리지 비용은 없습니다.
- 직접 실행한다면 평가가 끝난 뒤 Runpod 콘솔에서 Pod를 **Terminate**하세요. Stop 상태에서도 디스크 비용이 날 수 있습니다.

## 다음에 확인할 것

- KV 캐시 양자화: Gemma 12B의 KV 캐시 16bit와 8bit를 비교합니다. 설정(`g4-12b-qat-kv16`, `g4-12b-qat-kv8`)과 긴 문서 찾기 과제(`quant_hard.py prepare-needle`)까지 만들었고 실행은 하지 않았습니다.
- NVFP4를 dense 모델과 다른 계열에서 확인하기
- 한국어 문장으로 보정해서 만든 4bit
- thinking을 켰을 때의 4bit 차이

## 참고 자료

- [vLLM](https://github.com/vllm-project/vllm)
- [KMMLU](https://huggingface.co/datasets/HAERAE-HUB/KMMLU), [KMMLU-HARD](https://huggingface.co/datasets/HAERAE-HUB/KMMLU-HARD), [HRM8K](https://huggingface.co/datasets/HAERAE-HUB/HRM8K), [financial-mmlu-ko](https://huggingface.co/datasets/allganize/financial-mmlu-ko)
