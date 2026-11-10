#!/bin/sh
# Samples vLLM and GPU metrics inside the Pod every INTERVAL seconds until stopped.
# Requires VLLM_API_KEY. Usage: collect_metrics.sh <output-dir>
set -eu

: "${VLLM_API_KEY:?Set VLLM_API_KEY before collecting metrics}"

OUT_DIR="${1:?Usage: collect_metrics.sh <output-dir>}"
INTERVAL="${INTERVAL:-5}"
PATTERN='^vllm:(num_requests_running|num_requests_waiting|kv_cache_usage_perc|num_preemptions|request_(queue|prefill|decode|inference)_time_seconds_(sum|count))'

mkdir -p "$OUT_DIR"
while :; do
  NOW="$(date +%s)"
  curl -fs -H "Authorization: Bearer $VLLM_API_KEY" http://127.0.0.1:8000/metrics \
    | grep -E "$PATTERN" | sed "s/^/$NOW /" >> "$OUT_DIR/vllm_metrics.txt" || true
  nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu --format=csv,noheader,nounits \
    | sed "s/^/$NOW, /" >> "$OUT_DIR/gpu_metrics.csv" || true
  sleep "$INTERVAL"
done
