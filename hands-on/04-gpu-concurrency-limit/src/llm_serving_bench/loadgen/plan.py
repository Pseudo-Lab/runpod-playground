"""Turns the experiment config into a list of `vllm bench serve` runs."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Step:
    filename: str
    num_prompts: int
    max_concurrency: int


def concurrency_steps(config: dict[str, Any]) -> list[Step]:
    test = config["concurrency_test"]
    return [
        Step(
            filename=f"concurrency-{level}-rep{repeat}.json",
            num_prompts=max(test["min_prompts"], level * test["prompts_per_level_slot"]),
            max_concurrency=level,
        )
        for repeat in range(1, test["repeats"] + 1)
        for level in test["levels"]
    ]


def build_command(config: dict[str, Any], step: Step, base_url: str, result_dir: Path) -> list[str]:
    return [
        "vllm", "bench", "serve",
        "--backend", config["request"]["backend"],
        "--endpoint", config["request"]["endpoint"],
        "--base-url", base_url,
        "--model", config["model"]["name"],
        "--tokenizer", config["model"]["name"],
        "--dataset-name", config["dataset"]["name"],
        "--dataset-path", config["dataset"]["path"],
        "--seed", str(config["dataset"]["seed"]),
        "--temperature", str(config["request"]["temperature"]),
        "--num-prompts", str(step.num_prompts),
        "--request-rate", "inf",
        "--max-concurrency", str(step.max_concurrency),
        "--percentile-metrics", "ttft,tpot,itl,e2el",
        "--metric-percentiles", "50,95,99",
        "--ready-check-timeout-sec", "120",
        "--save-result",
        "--save-detailed",
        "--result-dir", str(result_dir),
        "--result-filename", step.filename,
    ]
