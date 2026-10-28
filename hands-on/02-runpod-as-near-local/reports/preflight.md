# RunPod 실험 사전점검

이 문서는 최초 사전점검의 과거 기록이다. 이후 S3 자격증명을 입력해 2026-10-18 기본 실험을 완료했다. 최신 결과는 [실행 결과](results.md)에 있다.

2026-10-17 23:16 KST 기준. GPU 실험 결과가 아니라 실행 전 실제 API 조회 결과다.

| 항목 | 결과 |
|---|---|
| 일반 RunPod API 인증 | 성공 |
| Pod 목록 조회 | 성공, 기존 Pod 0개 |
| Network volume 목록 조회 | 성공, 기존 volume 0개 |
| GPU 가격·S3 지원 데이터센터·재고 조회 | 성공 |
| 5090 기준 견적 | EU-RO-1, Secure Cloud On-demand, 단일 GPU $1.19/h |
| 저가 후보 | RTX A4500 / EU-RO-1, 단일 GPU $0.25/h |
| 가격 캐시 | `cache/gpu-prices.json`, 유효기간 24시간 |
| 캐시 재사용 검사 | 네트워크 호출을 금지한 객체로 재실행해 가격 API 미호출 확인 |
| S3 자격증명 | `.env`에 없음 |
| 생성한 유료 자원 | 없음 |
| H1~H5 | GPU 작업 미실시로 판단 유보 |

가격은 GPU 견적이며 디스크·network volume 비용을 포함하지 않는다. 선택 후보의 배포 가능성은 실제 생성 시 달라질 수 있다.

고정 추론 후보는 `Qwen/Qwen2.5-1.5B-Instruct`이며 모델 revision과 RunPod PyTorch 이미지 digest를 `experiment.json`에 기록했다. 아직 모델 다운로드나 GPU 추론은 하지 않았다. 실행 전 필요한 의존성, 모델 파일 hash, 출력 검증 기준을 확정한다.

다음 단계는 RunPod 콘솔에서 S3 API 키를 발급하고 로컬 `.env`에 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`를 입력하는 것이다. 입력 후 10GB network volume의 가격·수명·정리 방법을 확정하고 작은 파일 왕복을 먼저 검증한다. 계획의 Phase A 통과 조건을 충족하기 전에는 대용량 업로드나 반복 GPU 실행으로 진행하지 않는다.

근거: [API 명세](https://rest.runpod.io/v1/openapi.json), [GraphQL 명세](https://graphql-spec.runpod.io/), [S3 인증·지원 지역](https://docs.runpod.io/storage/s3-api). 실제 조회 요약은 `records/preflight.json`에 있으며 계정 정보와 원본 응답은 Git에서 제외한 `private/`에 보관한다.
