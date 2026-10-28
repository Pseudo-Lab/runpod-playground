# 이 repo에서 쓰는 RunPod API

공개 명세와 공식 문서 원문은 `cache/runpod-api/`에 저장한다. 새 작업에서는 이 파일들을 먼저 참고한다. 인증키나 계정 응답이 들어가는 캐시가 아니다.

```powershell
python scripts/cache_api_docs.py
python scripts/cache_api_docs.py --refresh
```

기본 유효기간은 7일이다. API 명세와 실제 응답이 다르면 강제 갱신한다. 출처·조회 시각·SHA-256은 `cache/runpod-api/index.json`에 기록한다. GPU 가격 캐시는 별도로 `cache/gpu-prices.json`에서 24시간 재사용한다.

## 호출 코드

`scripts/runpod_api.py`의 `Runpod.request()`는 REST, `Runpod.graphql()`은 GraphQL을 호출한다. 인증키는 `.env`에서 로드해 Authorization 헤더로만 전송한다. 생성 요청은 자동 재시도하지 않고, 응답 유실 시 실험 고유 이름으로 조회해 대조한다.

| 기능 | 경로 또는 로컬 참고 파일 |
|---|---|
| Pod 생성·목록 | `POST /pods`, `GET /pods` |
| Pod 조회·삭제 | `GET /pods/{podId}`, `DELETE /pods/{podId}` |
| Network volume 생성·목록 | `POST /networkvolumes`, `GET /networkvolumes` |
| Network volume 삭제 | `DELETE /networkvolumes/{networkVolumeId}` |
| GPU·지역·현재 재고 | `scripts/preflight.py`의 GraphQL 쿼리 |
| 실제 사용 쿼리 예시 | `docs/runpod-queries.graphql` |
| Pod·저장소 과금 | `GET /billing/pods`, `GET /billing/networkvolumes` |
| S3 파일 접근 | `scripts/experiment.py`의 `s3_client()` |

Pod 생성·삭제와 현재 상태 조회의 결과는 캐시해서 재사용하지 않는다. 가격·공개 문서와 달리 현재 자원 상태와 삭제 여부는 실제 API로 확인한다. 계정 원본 응답·SSH 비밀키·소유권 원장은 `private/`에만 저장한다.

`experiment.py init`은 유료 volume을 생성하고, `run`은 유료 Pod를 생성한다. `finish`는 이 실험이 만든 자원만 삭제하고 삭제 여부를 확인한다. 상세 실행 결과는 `records/`에 남긴다.
