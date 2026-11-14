"""양자화 실험 속도 · 비용 (P37). "4비트로 내리면 실제로 빠르고 싼가".

tollgate gateway 를 거쳐 스트리밍으로 부른다. 원장: runpod-exp, tags exp:speed · task:c<동시>.
문항은 GSM8K 앞부분(서로 다른 질문 → 반복 차단 · 접두사 캐시 영향 없음),
출력 길이는 256토큰으로 고정(min_tokens = max_tokens)해 조합끼리 같은 일을 시킨다.

- 동시 1: 사용자 한 명이 느끼는 속도 (첫 토큰 · 초당 토큰)
- 동시 16 · 48: 한꺼번에 받을 때 처리량 → 100만 토큰당 비용 = 시간당 단가 / (처리량 × 3600) × 1e6

    TOLLGATE_EXP_KEY=... uv run python scripts/quant_bench.py run --model exp-q35-9b-awq-4090 \\
        --cost-per-hr 0.89 [--levels 1,16,48]
    uv run python scripts/quant_bench.py summary
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "exp"
OUT = DATA / "bench"
GATEWAY = os.environ.get("TOLLGATE_GATEWAY_URL", "http://127.0.0.1:4000")
OUT_TOKENS = 256
LEVELS = {1: 8, 16: 64, 48: 144}  # 동시성 → 요청 수 (동시성마다 몇 바퀴)


def prompts() -> list[str]:
    rows = [json.loads(x) for x in (DATA / "gsm8k.jsonl").read_text().splitlines() if x.strip()]
    return [r["question"] for r in rows]


def body(model: str, prompt: str, level: int) -> dict[str, Any]:
    return {
        "model": model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0,
        "max_tokens": OUT_TOKENS,
        "min_tokens": OUT_TOKENS,  # vLLM: 출력 길이를 고정해 조합끼리 같은 일을 시킨다
        "messages": [{"role": "user", "content": prompt}],
        "chat_template_kwargs": {"enable_thinking": False},
        "metadata": {"tags": ["exp:speed", f"combo:{model}", f"task:c{level}"]},
    }


async def one(client: httpx.AsyncClient, b: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    ttft, usage, err = None, {}, None
    try:
        async with client.stream("POST", "/v1/chat/completions", json=b, timeout=600) as r:
            if r.status_code != 200:
                err = f"HTTP {r.status_code}: {(await r.aread()).decode(errors='replace')[:200]}"
            else:
                async for line in r.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    chunk = json.loads(line[6:])
                    delta = ((chunk.get("choices") or [{}])[0] or {}).get("delta") or {}
                    if ttft is None and (delta.get("content") or delta.get("reasoning_content")):
                        ttft = time.perf_counter() - t0
                    if chunk.get("usage"):
                        usage = chunk["usage"]
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:160]}"
    total = time.perf_counter() - t0
    out = int(usage.get("completion_tokens") or 0)
    return {
        "ok": err is None and ttft is not None,
        "error": err,
        "ttft_s": round(ttft, 3) if ttft else None,
        "total_s": round(total, 3),
        "output_tokens": out,
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        # 첫 토큰 뒤 초당 토큰 (사용자가 느끼는 글 쓰는 속도)
        "decode_tps": round((out - 1) / (total - ttft), 1) if ttft and out > 1 else None,
    }


async def level_run(client, model: str, qs: list[str], level: int, offset: int) -> dict[str, Any]:
    n = LEVELS[level]
    sem = asyncio.Semaphore(level)

    async def run(i: int) -> dict[str, Any]:
        async with sem:
            return await one(client, body(model, qs[(offset + i) % len(qs)], level))

    t0 = time.perf_counter()
    rows = await asyncio.gather(*[run(i) for i in range(n)])
    wall = time.perf_counter() - t0
    return {"level": level, "wall_s": round(wall, 2), "rows": rows}


def summarize_level(res: dict[str, Any], cost_per_hr: float | None) -> dict[str, Any]:
    ok = [r for r in res["rows"] if r["ok"]]
    out = sum(r["output_tokens"] for r in ok)
    tps = out / res["wall_s"] if res["wall_s"] else 0.0

    def med(key: str) -> float | None:
        v = [r[key] for r in ok if r[key] is not None]
        return round(statistics.median(v), 3) if v else None

    def p95(key: str) -> float | None:
        v = sorted(r[key] for r in ok if r[key] is not None)
        return round(v[min(len(v) - 1, int(0.95 * len(v)))], 3) if v else None

    return {
        "level": res["level"],
        "n": len(res["rows"]),
        "errors": len(res["rows"]) - len(ok),
        "throughput_tps": round(tps, 1),
        "ttft_p50_s": med("ttft_s"),
        "ttft_p95_s": p95("ttft_s"),
        "decode_tps_p50": med("decode_tps"),
        "mean_output_tokens": round(out / len(ok), 1) if ok else None,
        # 그 처리량으로 GPU 를 쉬지 않고 쓸 때 100만 출력 토큰 비용
        "usd_per_1m_output": round(cost_per_hr / (tps * 3600) * 1e6, 3)
        if cost_per_hr and tps
        else None,
    }


async def wait_ready(client: httpx.AsyncClient, model: str, timeout_s: float) -> None:
    t0 = time.monotonic()
    b = {"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
    b["metadata"] = {"tags": ["exp:speed", f"combo:{model}", "task:ready"]}
    while True:
        try:
            r = await client.post("/v1/chat/completions", json=b, timeout=60)
            if r.status_code == 200:
                print(f"  준비됨 ({time.monotonic() - t0:.0f}초 기다림)", flush=True)
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() - t0 > timeout_s:
            sys.exit(f"{model}: {timeout_s:.0f}초 안에 준비되지 않았습니다")
        await asyncio.sleep(20)


async def run(args: argparse.Namespace) -> None:
    key = os.environ.get("TOLLGATE_EXP_KEY") or sys.exit("TOLLGATE_EXP_KEY 가 없습니다")
    qs = prompts()
    levels = [int(x) for x in args.levels.split(",")]
    limits = httpx.Limits(max_connections=max(levels) + 8)
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(base_url=args.gateway, headers=headers, limits=limits) as client:
        if args.wait:
            await wait_ready(client, args.model, args.wait)
        # 데우기: 첫 요청의 그래프 준비 · 캐시가 측정에 섞이지 않게 (원장 task:warmup)
        warm = body(args.model, qs[-1], 1)
        warm["metadata"]["tags"][-1] = "task:warmup"
        await one(client, warm)
        out: dict[str, Any] = {"model": args.model, "cost_per_hr": args.cost_per_hr, "levels": []}
        offset = 0
        for level in levels:
            res = await level_run(client, args.model, qs, level, offset)
            offset += LEVELS[level]
            s = summarize_level(res, args.cost_per_hr)
            print(json.dumps(s, ensure_ascii=False), flush=True)
            out["levels"].append(s | {"rows": res["rows"]})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.model}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


def render(results: list[dict[str, Any]]) -> str:
    lines = [
        "| 조합 | 단가/h | 동시 | 처리량 tok/s | 첫 토큰 p50 | 글 속도 tok/s | $/100만 출력 "
        "| 오류 |"
    ]
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in results:
        for lv in r["levels"]:
            lines.append(
                f"| {r['model']} | ${r['cost_per_hr']} | {lv['level']} | {lv['throughput_tps']} "
                f"| {lv['ttft_p50_s']}s | {lv['decode_tps_p50']} | {lv['usd_per_1m_output']} "
                f"| {lv['errors']} |"
            )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--cost-per-hr", type=float)
    r.add_argument("--levels", default="1,16,48")
    r.add_argument("--gateway", default=GATEWAY)
    r.add_argument("--wait", type=float, default=0, help="모델이 준비될 때까지 최대 몇 초")
    s = sub.add_parser("summary")
    s.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.cmd == "run":
        asyncio.run(run(args))
    else:
        res = [json.loads(p.read_text()) for p in sorted(OUT.glob("*.json"))]
        for x in res:
            for lv in x["levels"]:
                lv.pop("rows", None)
        print(json.dumps(res, ensure_ascii=False, indent=2) if args.json else render(res))


if __name__ == "__main__":
    main()
