#!/bin/sh
# Starts the round 1 baseline inside the Pod: vLLM defaults, no tuning flags.
# Requires VLLM_API_KEY. Records the environment for the experiment log.
set -eu

: "${VLLM_API_KEY:?Set VLLM_API_KEY before starting the server}"

MODEL="kakaocorp/kanana-1.5-8b-instruct-2505"
LOG_DIR="${LOG_DIR:-/workspace/logs}"
export HF_HOME="${HF_HOME:-/workspace/hf}"

mkdir -p "$LOG_DIR"
python -c "import vllm, torch; print('vllm', vllm.__version__); print('torch', torch.__version__, 'cuda', torch.version.cuda, 'available', torch.cuda.is_available())" | tee "$LOG_DIR/versions.txt"
nvidia-smi | tee "$LOG_DIR/nvidia-smi.txt"

vllm serve "$MODEL" --host 0.0.0.0 --port 8000 --api-key "$VLLM_API_KEY" 2>&1 | tee "$LOG_DIR/vllm-server.log"
