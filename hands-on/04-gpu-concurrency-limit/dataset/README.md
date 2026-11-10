# dataset/

부하 테스트에 쓰는 한국어 질문 데이터를 두는 폴더입니다. 저장소에는 형식 샘플(`sample.json`)만 포함하고, 실제 데이터 파일은 포함하지 않습니다.

## 사용 데이터

| 항목 | 값 |
|---|---|
| 데이터셋 | [`FreedomIntelligence/sharegpt-korean`](https://huggingface.co/datasets/FreedomIntelligence/sharegpt-korean) |
| 파일 | `sharegpt-korean.json` (6,014건) |
| revision | `cbd0e328f55b6ca568f1e691a9c1d9a38626083c` |
| sha256 | `50b9eea17cc3aeaf0ef409a197e299078461f1c21eb4ec9eec2ece77b2be3160` |
| 라이선스 | 데이터셋 카드 표기 Apache-2.0 |

위 revision의 파일을 받아 `dataset/sharegpt_ko.json`으로 저장하면 됩니다.

## 파일 형식

`sample.json`과 같은 구조의 JSON 배열입니다. `vllm bench serve --dataset-name sharegpt --dataset-path <파일 경로>`로 사용합니다.

- `conversations`에 2턴 이상이 있어야 합니다. 첫 턴이 질문, 둘째 턴이 답변으로 쓰이고 3턴째부터는 사용되지 않습니다.
- 출력 길이는 둘째 턴의 토큰 수로 정해집니다. `--sharegpt-output-len`으로 덮어쓸 수 있습니다.
- 입력 4~1024토큰, 입력과 출력의 합 2048토큰 이하인 항목만 사용되고 나머지는 제외됩니다.
