"""Pod cost at each concurrency level and a price-based Serverless estimate."""
from dataclasses import dataclass


@dataclass(frozen=True)
class LevelCost:
    concurrency: int
    cost_per_request: float
    cost_per_million_tokens: float


@dataclass(frozen=True)
class ServerlessEstimate:
    """Traffic where Pod and Serverless cost the same. More traffic favors the Pod.

    Calculated from prices and Pod measurements only: cold starts and idle time are not included.
    """

    busy_fraction: float
    best_case_seconds_per_request: float
    best_case_breakeven_rps: float
    worst_case_seconds_per_request: float
    worst_case_breakeven_rps: float


def level_cost(concurrency: int, pod_hourly_usd: float, requests_per_second: float, tokens_per_second: float) -> LevelCost:
    if requests_per_second <= 0 or tokens_per_second <= 0:
        raise ValueError("Throughput must be positive.")
    return LevelCost(
        concurrency=concurrency,
        cost_per_request=pod_hourly_usd / (requests_per_second * 3600),
        cost_per_million_tokens=pod_hourly_usd / (tokens_per_second * 3600) * 1_000_000,
    )


def breakeven_rps(pod_hourly_usd: float, serverless_hourly_usd: float, seconds_per_request: float) -> float:
    return pod_hourly_usd / (serverless_hourly_usd * seconds_per_request)


def serverless_estimate(
    pod_hourly_usd: float, serverless_hourly_usd: float, max_requests_per_second: float, single_request_latency: float
) -> ServerlessEstimate:
    """Best case batches like the Pod; worst case handles one request at a time."""
    best = 1 / max_requests_per_second
    return ServerlessEstimate(
        busy_fraction=pod_hourly_usd / serverless_hourly_usd,
        best_case_seconds_per_request=best,
        best_case_breakeven_rps=breakeven_rps(pod_hourly_usd, serverless_hourly_usd, best),
        worst_case_seconds_per_request=single_request_latency,
        worst_case_breakeven_rps=breakeven_rps(pod_hourly_usd, serverless_hourly_usd, single_request_latency),
    )
