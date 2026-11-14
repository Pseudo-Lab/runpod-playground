"""Builds the concurrency and cost report for one experiment round."""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from llm_serving_bench.analysis import cost, metrics
from llm_serving_bench.config import load_config


def build_report(config: dict, round_dir: Path) -> dict:
    files = sorted((round_dir / "concurrency").glob("concurrency-*.json"))
    levels = metrics.summarize_levels([metrics.summarize_run(p) for p in files])
    report: dict = {"levels": [asdict(level) for level in levels]}

    pod_hourly = config["cost"]["pod_hourly_usd"]
    measured = [level for level in levels if level.requests_per_second > 0]
    report["cost"] = [
        asdict(cost.level_cost(level.concurrency, pod_hourly, level.requests_per_second, level.total_tokens_per_second))
        for level in measured
    ]

    serverless_hourly = config["cost"].get("serverless_hourly_usd")
    single = next((level for level in measured if level.concurrency == 1), None)
    if serverless_hourly and measured and single:
        max_rps = max(level.requests_per_second for level in measured)
        estimate = cost.serverless_estimate(pod_hourly, serverless_hourly, max_rps, single.mean_latency_seconds)
        report["serverless_estimate"] = asdict(estimate)
    return report


def seconds(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def print_report(report: dict) -> None:
    print("conc | req/s (stdev) | out tok/s | TTFT p50/p95 ms | TPOT p50/p95 ms | latency p50/p95 s | queue/prefill/decode/other s | failed")
    for level in report["levels"]:
        print(
            f"{level['concurrency']:>4} | {level['requests_per_second']:.2f} ({level['requests_per_second_stdev']:.2f}) | "
            f"{level['output_tokens_per_second']:.0f} | {level['p50_ttft_ms']:.0f}/{level['p95_ttft_ms']:.0f} | "
            f"{level['p50_tpot_ms']:.1f}/{level['p95_tpot_ms']:.1f} | "
            f"{level['p50_latency_seconds']:.2f}/{level['p95_latency_seconds']:.2f} | "
            f"{seconds(level['queue_seconds'])}/{seconds(level['prefill_seconds'])}/"
            f"{seconds(level['decode_seconds'])}/{seconds(level['other_seconds'])} | {level['failed']}"
        )
    for row in report["cost"]:
        print(
            f"concurrency {row['concurrency']:>4}: ${row['cost_per_request']:.6f}/request, "
            f"${row['cost_per_million_tokens']:.3f}/1M tokens"
        )
    estimate = report.get("serverless_estimate")
    if estimate:
        print(
            f"Serverless breakeven (no cold start or idle cost): "
            f"{estimate['worst_case_breakeven_rps']:.3f} to {estimate['best_case_breakeven_rps']:.3f} req/s"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/experiment.toml")
    parser.add_argument("--round", default="round1", help="Folder name under results/")
    args = parser.parse_args()

    round_dir = Path("results") / args.round
    report = build_report(load_config(args.config), round_dir)
    print_report(report)
    with open(round_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
