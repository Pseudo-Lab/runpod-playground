"""Computes serving metrics from `vllm bench serve` results and vLLM server metrics."""
import json
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

PHASE_METRICS = {
    "queue": "vllm:request_queue_time_seconds",
    "prefill": "vllm:request_prefill_time_seconds",
    "decode": "vllm:request_decode_time_seconds",
}


@dataclass(frozen=True)
class ServerBreakdown:
    """Mean seconds per request spent in each server phase."""

    requests: int
    queue_seconds: float
    prefill_seconds: float
    decode_seconds: float


@dataclass(frozen=True)
class RunMetrics:
    name: str
    concurrency: int
    requests: int
    failed: int
    requests_per_second: float
    output_tokens_per_second: float
    total_tokens_per_second: float
    mean_input_tokens: float
    mean_output_tokens: float
    p50_ttft_ms: float
    p95_ttft_ms: float
    p50_tpot_ms: float
    p95_tpot_ms: float
    mean_latency_seconds: float
    p50_latency_seconds: float
    p95_latency_seconds: float
    breakdown: ServerBreakdown | None


@dataclass(frozen=True)
class LevelSummary:
    """Mean over the repeats of one concurrency level."""

    concurrency: int
    repeats: int
    failed: int
    requests_per_second: float
    requests_per_second_stdev: float
    output_tokens_per_second: float
    total_tokens_per_second: float
    mean_input_tokens: float
    mean_output_tokens: float
    p50_ttft_ms: float
    p95_ttft_ms: float
    p50_tpot_ms: float
    p95_tpot_ms: float
    mean_latency_seconds: float
    p50_latency_seconds: float
    p95_latency_seconds: float
    implied_concurrency: float
    queue_seconds: float | None
    prefill_seconds: float | None
    decode_seconds: float | None
    other_seconds: float | None


def percentile(values: list[float], q: float) -> float:
    """Linear interpolation between closest ranks."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def parse_prometheus(text: str) -> dict[str, float]:
    """Sums each metric across its label sets."""
    totals: dict[str, float] = defaultdict(float)
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        series, value = line.rsplit(None, 1)
        totals[series.split("{", 1)[0]] += float(value)
    return dict(totals)


def server_breakdown(before_path: Path, after_path: Path) -> ServerBreakdown | None:
    """Returns the phase times added between two metric snapshots, or None if a snapshot is missing."""
    if not before_path.exists() or not after_path.exists():
        return None
    before = parse_prometheus(before_path.read_text(encoding="utf-8"))
    after = parse_prometheus(after_path.read_text(encoding="utf-8"))

    def delta(name: str) -> float:
        return after.get(name, 0.0) - before.get(name, 0.0)

    requests = delta(f"{PHASE_METRICS['decode']}_count")
    if requests <= 0:
        return None

    def mean_seconds(phase: str) -> float:
        return delta(f"{PHASE_METRICS[phase]}_sum") / delta(f"{PHASE_METRICS[phase]}_count")

    return ServerBreakdown(
        requests=int(requests),
        queue_seconds=mean_seconds("queue"),
        prefill_seconds=mean_seconds("prefill"),
        decode_seconds=mean_seconds("decode"),
    )


def summarize_run(path: str | Path) -> RunMetrics:
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    starts: list[float] = data["start_times"]
    errors: list[str] = data["errors"]
    ttfts: list[float] = data["ttfts"]
    itls: list[list[float]] = data["itls"]
    input_lens: list[int] = data["input_lens"]
    output_lens: list[int] = data["output_lens"]

    succeeded = [i for i in range(len(starts)) if not errors[i]]
    latencies = [ttfts[i] + sum(itls[i]) for i in succeeded]
    tpots = [sum(itls[i]) / (output_lens[i] - 1) * 1000 for i in succeeded if output_lens[i] > 1]

    duration = 0.0
    if succeeded:
        duration = max(starts[i] + latency for i, latency in zip(succeeded, latencies)) - min(starts)
    output_tokens = sum(output_lens[i] for i in succeeded)
    input_tokens = sum(input_lens[i] for i in succeeded)

    def per_second(amount: float) -> float:
        return amount / duration if duration > 0 else 0.0

    def mean_per_request(amount: float) -> float:
        return amount / len(succeeded) if succeeded else float("nan")

    return RunMetrics(
        name=path.name,
        concurrency=data["max_concurrency"],
        requests=len(starts),
        failed=len(starts) - len(succeeded),
        requests_per_second=per_second(len(succeeded)),
        output_tokens_per_second=per_second(output_tokens),
        total_tokens_per_second=per_second(input_tokens + output_tokens),
        mean_input_tokens=mean_per_request(input_tokens),
        mean_output_tokens=mean_per_request(output_tokens),
        p50_ttft_ms=percentile([ttfts[i] * 1000 for i in succeeded], 50),
        p95_ttft_ms=percentile([ttfts[i] * 1000 for i in succeeded], 95),
        p50_tpot_ms=percentile(tpots, 50),
        p95_tpot_ms=percentile(tpots, 95),
        mean_latency_seconds=statistics.fmean(latencies) if latencies else float("nan"),
        p50_latency_seconds=percentile(latencies, 50),
        p95_latency_seconds=percentile(latencies, 95),
        breakdown=server_breakdown(
            path.with_suffix(".metrics_before.prom"), path.with_suffix(".metrics_after.prom")
        ),
    )


def repeat_of(name: str) -> int:
    match = re.search(r"-rep(\d+)", name)
    if match is None:
        raise ValueError(f"No repeat number in file name: {name}")
    return int(match.group(1))


def summarize_levels(runs: list[RunMetrics]) -> list[LevelSummary]:
    by_level: dict[int, list[RunMetrics]] = defaultdict(list)
    for run in runs:
        by_level[run.concurrency].append(run)

    summaries = []
    for concurrency, items in sorted(by_level.items()):
        def mean(field: str) -> float:
            return statistics.fmean(getattr(run, field) for run in items)

        def phase(field: str) -> float | None:
            if any(run.breakdown is None for run in items):
                return None
            return statistics.fmean(getattr(run.breakdown, field) for run in items)

        rps = [run.requests_per_second for run in items]
        latency = mean("mean_latency_seconds")
        queue, prefill, decode = phase("queue_seconds"), phase("prefill_seconds"), phase("decode_seconds")
        other = None if queue is None else latency - queue - prefill - decode
        summaries.append(
            LevelSummary(
                concurrency=concurrency,
                repeats=len(items),
                failed=sum(run.failed for run in items),
                requests_per_second=statistics.fmean(rps),
                requests_per_second_stdev=statistics.stdev(rps) if len(rps) > 1 else 0.0,
                output_tokens_per_second=mean("output_tokens_per_second"),
                total_tokens_per_second=mean("total_tokens_per_second"),
                mean_input_tokens=mean("mean_input_tokens"),
                mean_output_tokens=mean("mean_output_tokens"),
                p50_ttft_ms=mean("p50_ttft_ms"),
                p95_ttft_ms=mean("p95_ttft_ms"),
                p50_tpot_ms=mean("p50_tpot_ms"),
                p95_tpot_ms=mean("p95_tpot_ms"),
                mean_latency_seconds=latency,
                p50_latency_seconds=mean("p50_latency_seconds"),
                p95_latency_seconds=mean("p95_latency_seconds"),
                implied_concurrency=statistics.fmean(rps) * latency,
                queue_seconds=queue,
                prefill_seconds=prefill,
                decode_seconds=decode,
                other_seconds=other,
            )
        )
    return summaries
