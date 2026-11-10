# GPU 한 장으로 동시 요청을 얼마나 처리할 수 있을까?

- 작성자: ldyoung4032
- 리뷰어: 미정
- 상태: 완료
- 실행 확인일: 2026-11-09
- 관련 Issue / 주간 기록: 미정
- 발표 자료: [HTML](slides.html) · [PDF](slides.pdf)

## 확인하려는 질문

RTX 5090 한 장에서 vLLM으로 Kanana 1.5 8B를 서빙할 때의 처리 한계와 구간별 소요 시간을 측정합니다.

1. 동시 요청 수를 늘려도 GPU가 처리하는 양이 거의 늘지 않는 지점은 어디인가?
2. 답변이 눈에 띄게 느려지기 시작하는 동시 요청 수는 몇인가?
3. 답변 하나를 만드는 동안 어느 단계가 가장 오래 걸리고, 동시 요청이 늘면 어느 단계가 느려지는가?

비교 조건은 동시 요청 수(1, 2, 4, 8, 16, 32, 64, 128, 256)뿐이고 나머지는 고정했습니다. 합격선을 두지 않고 관찰하는 실험이라 별도의 성공 기준은 없습니다.

## 준비 환경

- Runpod 제품 유형: Pod, On-Demand, Secure Cloud
- GPU 종류와 개수: NVIDIA GeForce RTX 5090 (32GB) 1장, RAM 92GB, vCPU 16개
- 컨테이너 이미지·태그: `runpod/pytorch:1.5.0-cu1281-torch280-ubuntu2404`
- 주요 라이브러리 버전: vLLM 0.26.0, PyTorch 2.11.0 (CUDA 13.0 빌드), lm-evaluation-harness 0.4.13, 드라이버 595.91.07
- 모델·데이터와 출처:
  - 모델: [`kakaocorp/kanana-1.5-8b-instruct-2505`](https://huggingface.co/kakaocorp/kanana-1.5-8b-instruct-2505) (Apache-2.0)
  - 부하 데이터: [`FreedomIntelligence/sharegpt-korean`](https://huggingface.co/datasets/FreedomIntelligence/sharegpt-korean) 6,014건 (데이터셋 카드 표기 Apache-2.0, 원본은 저장소에 포함하지 않음. [`dataset/README.md`](dataset/README.md) 참고)
  - 품질 데이터: [`skt/kobest_v1`](https://huggingface.co/datasets/skt/kobest_v1) (CC BY-SA 4.0)
- 필요한 스토리지: 컨테이너 디스크 50GB (Network Volume 미사용, 실행 중 약 34GB 사용)

## 예상 사용량과 비용

비용 산정일은 2026-11-09입니다.

| 항목 | 값 | 구분 |
|---|---|---|
| GPU | 시간당 $1.19 | 콘솔 표시 가격 |
| 컨테이너 디스크 50GB | 시간당 약 $0.007 | 콘솔 표시 가격 |
| 사용 시간 | 약 3시간 (환경 구성, KoBEST, 동시성 측정 포함) | 추정 |
| 총비용 | 약 $3.6 | 추정 |

## 실행 방법

키와 토큰은 환경변수로만 다루고 저장소에 올리지 않습니다. 별도 표시가 없으면 Pod 터미널에서 실행합니다.

### 1. 프로젝트 복사

로컬에서 실행합니다. `<pod>`는 Pod의 SSH 접속 이름입니다. 공인 IP와 TCP 포트로 접속하는 SSH를 사용합니다.

```bash
cd hands-on
COPYFILE_DISABLE=1 tar --exclude=.venv --exclude=__pycache__ -czf - 03-gpu-concurrency-limit \
  | ssh <pod> "mkdir -p /workspace && tar -xzf - -C /workspace"
```

부하 데이터는 [`dataset/README.md`](dataset/README.md)의 revision으로 받아 Pod의 `dataset/sharegpt_ko.json`에 둡니다.

### 2. 도구 설치

vLLM과 평가 도구의 패키지가 충돌하지 않도록 환경을 분리합니다.

```bash
pip install uv

uv venv /opt/vllm-env --python 3.12
source /opt/vllm-env/bin/activate
uv pip install "vllm==0.26.0"
deactivate

uv venv /opt/lm-eval-env --python 3.12
source /opt/lm-eval-env/bin/activate
uv pip install "lm-eval[api]==0.4.13" transformers sentencepiece
deactivate
```

### 3. 서버 시작

```bash
source /opt/vllm-env/bin/activate
cd /workspace/03-gpu-concurrency-limit
mkdir -p /workspace/logs
openssl rand -hex 16 > /workspace/.vllm_key && chmod 600 /workspace/.vllm_key
export VLLM_API_KEY=$(cat /workspace/.vllm_key)
export OPENAI_API_KEY=$VLLM_API_KEY
export HF_HOME=/workspace/hf
export VLLM_USE_FLASHINFER_SAMPLER=0
nohup sh deploy/pod/start_vllm.sh > /workspace/logs/start.log 2>&1 &
```

`Application startup complete`가 로그에 나오면 준비가 끝난 것입니다.

`VLLM_USE_FLASHINFER_SAMPLER=0`은 이 환경에서 필요합니다. `start_vllm.sh`에 들어 있지 않으므로 직접 설정합니다.

vLLM 시작 로그의 `non-default args` 줄에는 API 키가 출력됩니다. 로그를 공유할 때는 이 줄을 제외합니다.

### 4. KoBEST 측정

새 터미널에서 실행합니다.

```bash
source /opt/lm-eval-env/bin/activate
cd /workspace/03-gpu-concurrency-limit
export HF_HOME=/workspace/hf
export OPENAI_API_KEY=$(cat /workspace/.vllm_key)
sh deploy/pod/run_kobest.sh http://localhost:8000 round1
```

### 5. 동시성 측정

동시 요청 1~256을 단계별로 3회 반복해 총 27회 측정합니다. 이미 결과 파일이 있는 단계는 건너뜁니다.

```bash
source /opt/vllm-env/bin/activate
cd /workspace/03-gpu-concurrency-limit
export HF_HOME=/workspace/hf
export VLLM_API_KEY=$(cat /workspace/.vllm_key)
export OPENAI_API_KEY=$VLLM_API_KEY
mkdir -p /workspace/logs/metrics-round1
nohup sh deploy/pod/collect_metrics.sh /workspace/logs/metrics-round1 > /dev/null 2>&1 &
PYTHONPATH=src python -m llm_serving_bench.loadgen.run --base-url http://localhost:8000
```

## 결과 확인 방법

```bash
PYTHONPATH=src python -m llm_serving_bench.analysis.report
```

동시 요청별 처리량, TTFT, TPOT, latency, 대기·prefill·decode 시간, 실패 건수가 출력되고 `results/round1/summary.json`에 저장됩니다.

분석 코드는 로컬에서 `uv run python -m unittest discover -s tests`로 테스트할 수 있습니다.

## 결과와 시행착오

### 측정 조건

- 측정: `vllm bench serve`, `/v1/chat/completions`, `request-rate=inf`, `max-concurrency`로 동시 요청 수 고정
- 생성 설정: `temperature=0`, `seed=42`, 출력 길이는 데이터의 답변 길이 사용
- 시나리오: 시스템 프롬프트 없는 단일 턴 한국어 QnA
- 부하 도구는 GPU와 같은 Pod에서 실행
- 동시 요청별 3회, 총 27회, 요청 31,140건, 실패 0건
- 입력 평균 약 105~117토큰, 출력 평균 약 340~377토큰
- 동시 1~64를 먼저 측정한 뒤 포화가 보이지 않아 같은 서버에서 128과 256을 추가 측정

### 서빙 성능 (측정값, 3회 평균)

| 동시 요청 | 요청/초 | 생성 토큰/초 | TTFT p50/p95 | TPOT p50/p95 | latency p50/p95 |
|---|---|---|---|---|---|
| 1 | 0.27 | 100 | 22 / 39ms | 10.0 / 10.0ms | 3.51 / 8.09초 |
| 2 | 0.50 | 189 | 31 / 35ms | 10.5 / 10.5ms | 3.70 / 8.57초 |
| 4 | 0.99 | 371 | 32 / 36ms | 10.6 / 10.6ms | 3.72 / 8.81초 |
| 8 | 1.82 | 675 | 34 / 51ms | 11.2 / 11.4ms | 3.73 / 9.60초 |
| 16 | 3.56 | 1,282 | 37 / 67ms | 11.7 / 12.1ms | 3.73 / 10.04초 |
| 32 | 6.94 | 2,423 | 42 / 109ms | 12.5 / 12.9ms | 3.91 / 10.16초 |
| 64 | 11.56 | 3,927 | 53 / 138ms | 15.1 / 15.8ms | 4.62 / 11.91초 |
| 128 | 16.13 | 5,514 | 90 / 286ms | 21.7 / 22.6ms | 6.75 / 16.91초 |
| 256 | 17.19 | 5,863 | 169 / 1,221ms | 42.3 / 45.2ms | 13.08 / 32.87초 |

### 단계별 소요 시간 (측정값, 요청당 평균, 초)

| 동시 요청 | 대기열 | prefill | decode | 그 외 | KV 캐시 사용률 평균 |
|---|---|---|---|---|---|
| 1 | 0.00 | 0.02 | 3.70 | 0.03 | - |
| 16 | 0.00 | 0.03 | 4.21 | 0.02 | - |
| 64 | 0.00 | 0.05 | 5.09 | 0.03 | 23.6% |
| 128 | 0.01 | 0.07 | 7.33 | 0.05 | 45.0% |
| 256 | 0.07 | 0.11 | 14.20 | 0.09 | 88.9% (최대 99.9%) |

### 질문별 결과

1. 동시 요청 128에서 256 사이에서 처리량 증가가 거의 멈췄습니다. 2배 늘렸을 때 처리량은 약 6~7%만 늘었고, 초당 약 17건(약 5,900토큰)에 머물렀습니다.
2. 답변 시간 중간값은 동시 64까지 3.5초에서 4.6초로 늘었고, 128에서 약 6.8초, 256에서 약 13.1초가 됐습니다.
3. 전체 시간의 약 98%가 decode입니다. decode 평균 시간은 동시 1의 3.70초에서 동시 256의 14.20초로 가장 많이 늘었습니다.

### 비용 (계산값)

GPU 시간당 $1.19를 측정 처리량으로 나눈 값입니다. 해당 동시성을 쉬지 않고 채웠을 때의 단가이며 유휴 시간과 디스크 비용은 포함하지 않습니다. 100만 토큰당 비용은 입력과 출력 토큰의 합을 기준으로 합니다.

| 동시 요청 | 요청당 | 100만 토큰당 |
|---|---|---|
| 1 | $0.001240 | $2.581 |
| 16 | $0.000093 | $0.195 |
| 64 | $0.000029 | $0.064 |
| 128 | $0.000020 | $0.046 |
| 256 | $0.000019 | $0.043 |

### 한국어 성능 (측정값, KoBEST, 0-shot, 채팅 템플릿 적용)

| 태스크 | 문항 수 | 정확도 | F1 |
|---|---|---|---|
| boolq | 1,404 | 0.8960 | 0.8959 |
| copa | 1,000 | 0.7610 | 0.7607 |
| hellaswag | 500 | 0.4340 (acc_norm 0.5020) | 0.4319 |
| sentineg | 397 | 0.7431 | 0.7369 |
| wic | 1,260 | 0.6024 | 0.5211 |

### 시행착오

| 문제 | 원인 | 조치 |
|---|---|---|
| RTX 5090 배포 실패 | 재고 표시가 있어도 배포 시점에 재고 없음 | 재시도로 확보 |
| Network Volume 연결 시 배포 제약 | 볼륨이 데이터센터에 고정됨 | 볼륨 없이 Any region으로 배포 |
| 서버 시작 실패 (`FlashInfer requires GPUs with sm75 or higher`) | FlashInfer 샘플러의 GPU 세대 확인 실패. 로그에 `SM 12.x requires CUDA >= 12.9` 표시, 템플릿 CUDA 12.8.1과의 호환 문제로 추정 | `VLLM_USE_FLASHINFER_SAMPLER=0` 설정 |
| 시작 로그에 API 키 출력 | `non-default args` 줄에 키가 표시됨 | 결과 백업 시 해당 줄 제외 |

### 아직 확인하지 못한 부분

- 동시 요청 수를 고정하는 방식이라 일정한 요청률로 들어오는 트래픽보다 대기열 지연이 덜 드러날 수 있습니다.
- 부하 도구가 GPU와 같은 Pod에서 실행되어 CPU를 공유하며, 네트워크 지연은 포함되지 않았습니다.
- FlashInfer 샘플러를 켰을 때의 차이와 CUDA 12.9 이상에서 오류가 해결되는지는 확인하지 않았습니다.
- 동시 요청 256을 넘는 구간은 측정하지 않았습니다.
- 멀티턴과 시스템 프롬프트가 있는 요청, RAG 등 LLM 서버 앞뒤의 처리는 측정하지 않았습니다.

## 실습 종료 후 정리

Pod의 컨테이너 디스크는 Pod를 멈추면 지워지므로 먼저 결과를 로컬로 복사합니다. 로컬에서 실행합니다.

```bash
ssh <pod> "tar -czf - -C /workspace/03-gpu-concurrency-limit results -C /workspace/logs metrics-round1" \
  | tar -xzf - -C .
```

복사를 확인한 뒤 RunPod 콘솔에서 Pod를 **Terminate**합니다. 이번 실험은 Network Volume을 쓰지 않았습니다. 볼륨을 만들었다면 Storage 메뉴에서 삭제해야 비용이 멈춥니다.

## 다음에 확인할 것

- 양자화 등 모델 경량화가 decode 시간과 KoBEST 점수에 미치는 영향
- `--max-num-seqs` 조정에 따른 답변 시간과 처리량의 균형
- FlashInfer 샘플러를 켠 환경과의 비교
- 일정한 요청률로 보내는 부하 테스트
- 출력 길이를 바꿨을 때의 처리 한계

## 참고 자료

- [vLLM Benchmark CLI](https://docs.vllm.ai/en/latest/benchmarking/cli/)
- [vLLM Metrics](https://docs.vllm.ai/en/stable/usage/metrics/)
- [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness)
