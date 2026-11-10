#!/bin/sh
# Scores Korean quality with KoBEST against a running vLLM server.
# Requires lm-evaluation-harness (`lm_eval`) and OPENAI_API_KEY set to the vLLM API key.
# Usage: run_kobest.sh <base-url> [round]
set -eu

BASE_URL="${1:?Usage: run_kobest.sh <base-url> [round]}"
ROUND="${2:-round1}"
MODEL="kakaocorp/kanana-1.5-8b-instruct-2505"
TASKS="kobest_boolq,kobest_copa,kobest_hellaswag,kobest_sentineg,kobest_wic"

: "${OPENAI_API_KEY:?Set OPENAI_API_KEY to the API key used by the vLLM server}"

lm_eval \
  --model local-completions \
  --model_args "model=${MODEL},base_url=${BASE_URL%/}/v1/completions,num_concurrent=32,max_retries=3,tokenized_requests=True,tokenizer=${MODEL},tokenizer_backend=huggingface,max_length=8192" \
  --tasks "$TASKS" \
  --apply_chat_template \
  --output_path "results/${ROUND}/kobest"
