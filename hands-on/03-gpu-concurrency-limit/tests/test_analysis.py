"""Checks the analysis against synthetic result files with known answers."""
import json
import tempfile
import unittest
from pathlib import Path

from llm_serving_bench.analysis import cost, metrics, report


def write_run(
    path: Path, concurrency: int, count: int = 40, ttft: float = 0.2, gap: float = 0.02, output_len: int = 11, fail: int = 0
) -> None:
    """Each slot runs requests back to back, so a request takes ttft + gap * (output_len - 1) seconds."""
    latency = ttft + gap * (output_len - 1)
    errors = ["boom" if i < fail else "" for i in range(count)]
    data = {
        "max_concurrency": concurrency,
        "start_times": [1000.0 + (i // concurrency) * latency for i in range(count)],
        "errors": errors,
        "ttfts": [0.0 if errors[i] else ttft for i in range(count)],
        "itls": [[] if errors[i] else [gap] * (output_len - 1) for i in range(count)],
        "input_lens": [100] * count,
        "output_lens": [0 if errors[i] else output_len for i in range(count)],
    }
    path.write_text(json.dumps(data))


def write_snapshots(path: Path, requests: int) -> None:
    labels = '{model_name="m",engine="0"}'
    lines = ["# HELP something", "vllm:num_requests_running" + labels + " 0.0"]
    for phase, total in (("queue", 4.0), ("prefill", 2.0), ("decode", 8.0)):
        lines.append(f"vllm:request_{phase}_time_seconds_sum{labels} {total + 1.0}")
        lines.append(f"vllm:request_{phase}_time_seconds_count{labels} {requests + 5}")
    path.with_suffix(".metrics_after.prom").write_text("\n".join(lines) + "\n")
    before = []
    for phase in ("queue", "prefill", "decode"):
        before.append(f"vllm:request_{phase}_time_seconds_sum{labels} 1.0")
        before.append(f"vllm:request_{phase}_time_seconds_count{labels} 5")
    path.with_suffix(".metrics_before.prom").write_text("\n".join(before) + "\n")


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def test_percentile_interpolates(self):
        self.assertAlmostEqual(metrics.percentile([1, 2, 3, 4, 5], 50), 3)
        self.assertAlmostEqual(metrics.percentile([0, 10], 95), 9.5)

    def test_prometheus_sums_labels_and_skips_comments(self):
        text = '# TYPE x gauge\nx{a="1"} 2\nx{a="2"} 3\ny 1.5\n'
        self.assertEqual(metrics.parse_prometheus(text), {"x": 5.0, "y": 1.5})

    def test_run_values(self):
        path = self.dir / "concurrency-4-rep1.json"
        write_run(path, 4)
        run = metrics.summarize_run(path)
        self.assertEqual(run.concurrency, 4)
        self.assertAlmostEqual(run.requests_per_second, 10.0)
        self.assertAlmostEqual(run.output_tokens_per_second, 110.0)
        self.assertAlmostEqual(run.total_tokens_per_second, 1110.0)
        self.assertAlmostEqual(run.p95_ttft_ms, 200)
        self.assertAlmostEqual(run.p95_tpot_ms, 20)
        self.assertAlmostEqual(run.mean_latency_seconds, 0.4)
        self.assertIsNone(run.breakdown)

    def test_failures_are_excluded_from_latency_and_throughput(self):
        path = self.dir / "concurrency-1-rep1.json"
        write_run(path, 1, count=10, fail=2)
        run = metrics.summarize_run(path)
        self.assertEqual(run.failed, 2)
        self.assertAlmostEqual(run.p95_ttft_ms, 200)
        self.assertAlmostEqual(run.requests_per_second, 8 / (9 * 0.4 + 0.4))

    def test_all_failed_run_reports_zero_throughput(self):
        path = self.dir / "concurrency-1-rep1.json"
        write_run(path, 1, count=4, fail=4)
        run = metrics.summarize_run(path)
        self.assertEqual(run.requests_per_second, 0.0)
        self.assertEqual(run.failed, 4)

    def test_server_breakdown_uses_difference_between_snapshots(self):
        path = self.dir / "concurrency-4-rep1.json"
        write_run(path, 4)
        write_snapshots(path, 40)
        breakdown = metrics.summarize_run(path).breakdown
        self.assertEqual(breakdown.requests, 40)
        self.assertAlmostEqual(breakdown.queue_seconds, 0.1)
        self.assertAlmostEqual(breakdown.prefill_seconds, 0.05)
        self.assertAlmostEqual(breakdown.decode_seconds, 0.2)

    def test_levels_average_repeats(self):
        for repeat, ttft in ((1, 0.2), (2, 0.4)):
            path = self.dir / f"concurrency-4-rep{repeat}.json"
            write_run(path, 4, ttft=ttft)
            write_snapshots(path, 40)
        write_run(self.dir / "concurrency-1-rep1.json", 1)
        runs = [metrics.summarize_run(p) for p in sorted(self.dir.glob("concurrency-*.json"))]
        low, high = metrics.summarize_levels(runs)
        self.assertEqual((low.concurrency, high.concurrency, high.repeats), (1, 4, 2))
        self.assertIsNone(low.queue_seconds)
        self.assertAlmostEqual(high.p95_ttft_ms, 300)
        self.assertAlmostEqual(high.requests_per_second, (10.0 + 4 / 0.6) / 2)
        self.assertGreater(high.requests_per_second_stdev, 0)
        self.assertAlmostEqual(high.other_seconds, 0.5 - 0.35)

    def test_implied_concurrency_matches_slots(self):
        path = self.dir / "concurrency-8-rep1.json"
        write_run(path, 8, count=80)
        level = metrics.summarize_levels([metrics.summarize_run(path)])[0]
        self.assertAlmostEqual(level.implied_concurrency, 8.0)


class CostTest(unittest.TestCase):
    def test_level_cost_hand_calculated(self):
        row = cost.level_cost(4, 1.19, 2.0, 200.0)
        self.assertAlmostEqual(row.cost_per_request, 1.19 / 7200)
        self.assertAlmostEqual(row.cost_per_million_tokens, 1.19 / 720000 * 1_000_000)

    def test_zero_throughput_is_rejected(self):
        with self.assertRaises(ValueError):
            cost.level_cost(1, 1.19, 0, 0)

    def test_breakeven_hand_calculated(self):
        self.assertAlmostEqual(cost.breakeven_rps(1.19, 2.38, 0.5), 1.0)

    def test_breakeven_costs_are_equal(self):
        rps = cost.breakeven_rps(1.19, 2.0, 0.8)
        serverless_hourly_cost = rps * 3600 * 0.8 * (2.0 / 3600)
        self.assertAlmostEqual(serverless_hourly_cost, 1.19)

    def test_serverless_estimate_range(self):
        estimate = cost.serverless_estimate(1.0, 2.0, 4.0, 2.0)
        self.assertAlmostEqual(estimate.busy_fraction, 0.5)
        self.assertAlmostEqual(estimate.best_case_seconds_per_request, 0.25)
        self.assertAlmostEqual(estimate.best_case_breakeven_rps, 2.0)
        self.assertAlmostEqual(estimate.worst_case_breakeven_rps, 0.25)


class ReportTest(unittest.TestCase):
    def build(self, cost_config: dict) -> dict:
        with tempfile.TemporaryDirectory() as temp:
            round_dir = Path(temp)
            (round_dir / "concurrency").mkdir()
            for level in (1, 4):
                for repeat in (1, 2):
                    write_run(round_dir / "concurrency" / f"concurrency-{level}-rep{repeat}.json", level)
            return report.build_report({"cost": cost_config}, round_dir)

    def test_report_without_serverless_price(self):
        result = self.build({"pod_hourly_usd": 1.19})
        self.assertEqual([level["concurrency"] for level in result["levels"]], [1, 4])
        self.assertEqual(len(result["cost"]), 2)
        self.assertNotIn("serverless_estimate", result)

    def test_report_with_serverless_price(self):
        result = self.build({"pod_hourly_usd": 1.19, "serverless_hourly_usd": 2.38})
        estimate = result["serverless_estimate"]
        self.assertAlmostEqual(estimate["best_case_seconds_per_request"], 0.1)
        self.assertAlmostEqual(estimate["worst_case_seconds_per_request"], 0.4)
        self.assertAlmostEqual(estimate["best_case_breakeven_rps"], 5.0)
        self.assertAlmostEqual(estimate["worst_case_breakeven_rps"], 1.25)


if __name__ == "__main__":
    unittest.main()
