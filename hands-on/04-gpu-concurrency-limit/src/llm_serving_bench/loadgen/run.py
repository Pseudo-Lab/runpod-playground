"""Runs the concurrency test by calling `vllm bench serve` for each step."""
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from llm_serving_bench.config import load_config
from llm_serving_bench.loadgen import plan

SETTLE_SECONDS = 2


def strip_generated_text(path: Path) -> None:
    """Keeps timing data and drops model output, which is large and not used in analysis."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.pop("generated_texts", None)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def save_server_metrics(base_url: str, api_key: str, target: Path) -> None:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/metrics", headers={"Authorization": f"Bearer {api_key}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        target.write_bytes(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="For example http://<public-ip>:<tcp-port>")
    parser.add_argument("--config", default="configs/experiment.toml")
    parser.add_argument("--round", default="round1", help="Folder name under results/")
    parser.add_argument("--dry-run", action="store_true", help="Print the commands without running them")
    parser.add_argument("--force", action="store_true", help="Run again even if a result file exists")
    args = parser.parse_args()

    config = load_config(args.config)
    result_dir = Path("results") / args.round / "concurrency"
    steps = plan.concurrency_steps(config)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not args.dry_run and not api_key:
        raise SystemExit("Set OPENAI_API_KEY to the API key used by the vLLM server.")

    for number, step in enumerate(steps, start=1):
        target = result_dir / step.filename
        command = plan.build_command(config, step, args.base_url, result_dir)
        if args.dry_run:
            print(shlex.join(command))
            continue
        if target.exists() and not args.force:
            print(f"[{number}/{len(steps)}] skip, already measured: {target}")
            continue
        print(f"[{number}/{len(steps)}] {step.filename}: {step.num_prompts} prompts", flush=True)
        result_dir.mkdir(parents=True, exist_ok=True)
        save_server_metrics(args.base_url, api_key, target.with_suffix(".metrics_before.prom"))
        completed = subprocess.run(command)
        if completed.returncode != 0:
            print(f"Stopped: {step.filename} exited with {completed.returncode}", file=sys.stderr)
            return completed.returncode
        time.sleep(SETTLE_SECONDS)
        save_server_metrics(args.base_url, api_key, target.with_suffix(".metrics_after.prom"))
        strip_generated_text(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
