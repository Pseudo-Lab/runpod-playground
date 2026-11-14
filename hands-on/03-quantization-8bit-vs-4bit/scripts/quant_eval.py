"""양자화 실험 평가 도구 (P35, PLAN P35–P37). tollgate gateway 를 거쳐 부른다.

질문: "8비트(FP8) → 4비트(AWQ) 는 손해인가, 몇 B부터 4비트가 괜찮은가".

과제 (thinking 끔, temperature 0 — 같은 문제를 모든 조합에 똑같이)
- gsm8k: 수학 1,319문항 전부 (MIT). 4비트 손실이 가장 잘 드러나는 다단계 계산
- kmmlu: 한국어 지식 45과목 × 23문항 = 1,035문항 (CC-BY-ND, 저장소에 올리지 않고 받아 쓴다)

짝지은 비교: 같은 문항을 두 조합이 풀었을 때 한쪽만 맞힌 문항 수(b, c)로
McNemar 정확 검정 · 정확도 차이 95% 신뢰구간. 1,000문항이면 약 ±2%p 를 구분한다.

    uv run python scripts/quant_eval.py prepare
    TOLLGATE_EXP_KEY=... uv run python scripts/quant_eval.py run --model exp-q3-8b-fp8-l40s \\
        --task gsm8k,kmmlu [--wait 1800] [--concurrency 32] [--limit N]
    uv run python scripts/quant_eval.py summary [--json]
    uv run python scripts/quant_eval.py compare exp-q3-8b-fp8-l40s exp-q3-8b-awq-l40s --task gsm8k

원장에는 키의 서비스(runpod-exp)와 tags exp:quant · combo:<모델> · task:<과제> 로 남는다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import math
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "exp"
RESULTS = DATA / "results"
LOGS = DATA / "logs"  # quant_run 이 모은 Pod 의 vLLM 로그 (<조합>-vllm.log)
CONFIG = ROOT / "config" / "runpod_exp.yaml"
GATEWAY = os.environ.get("TOLLGATE_GATEWAY_URL", "http://127.0.0.1:4000")

GSM8K_ROWS = (
    "https://datasets-server.huggingface.co/rows?dataset=openai/gsm8k&config=main&split=test"
)
KMMLU_REV = "d61b3f19e552c576bf5960dd24289763edc36a88"  # 2026-11-06 확인
KMMLU_CSV = "https://huggingface.co/datasets/HAERAE-HUB/KMMLU/resolve/{rev}/data/{subject}-test.csv"
KMMLU_PER_SUBJECT = 23
SEED = 35

TASKS: dict[str, dict[str, Any]] = {
    "gsm8k": {"max_tokens": 768},
    # 작은 모델은 "알파벳만" 이라고 해도 설명부터 한다 → 16토큰이면 답 전에 잘린다 (2B 에서 10%)
    "kmmlu": {"max_tokens": 128},
}
GSM8K_SUFFIX = "\n\nSolve step by step, briefly. End with a final line: 'Answer: <number>'."
KMMLU_SUFFIX = "\n\n정답 알파벳(A, B, C, D) 하나만 답하세요."
LETTERS = "ABCD"


# --- 문제 세트 -------------------------------------------------------------------------


def gsm8k_gold(answer: str) -> str:
    return norm_number(answer.split("####")[-1])


def gsm8k_prompt(item: dict[str, Any]) -> str:
    return item["question"] + GSM8K_SUFFIX


def kmmlu_prompt(item: dict[str, Any]) -> str:
    opts = "\n".join(f"{k}. {item['choices'][i]}" for i, k in enumerate(LETTERS))
    return f"다음 문제의 정답을 고르세요.\n\n{item['question']}\n{opts}{KMMLU_SUFFIX}"


def prompt_for(task: str, item: dict[str, Any]) -> str:
    return gsm8k_prompt(item) if task == "gsm8k" else kmmlu_prompt(item)


def sample_kmmlu(rows_by_subject: dict[str, list[dict[str, Any]]], per: int, seed: int) -> list:
    rng = random.Random(seed)
    out = []
    for subject in sorted(rows_by_subject):
        rows = rows_by_subject[subject]
        for i in sorted(rng.sample(range(len(rows)), min(per, len(rows)))):
            r = rows[i]
            out.append(
                {
                    "id": f"{subject}-{i}",
                    "subject": subject,
                    "question": r["question"],
                    "choices": [r[k] for k in LETTERS],
                    "gold": LETTERS[int(r["answer"]) - 1],
                }
            )
    return out


async def prepare(out: Path) -> None:
    os.makedirs(out, exist_ok=True)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        items, offset = [], 0
        while True:
            r = await client.get(f"{GSM8K_ROWS}&offset={offset}&length=100")
            r.raise_for_status()
            d = r.json()
            for x in d["rows"]:
                q, a = x["row"]["question"], x["row"]["answer"]
                items.append({"id": f"gsm8k-{x['row_idx']}", "question": q, "gold": gsm8k_gold(a)})
            offset += 100
            if offset >= d["num_rows_total"]:
                break
        _write_jsonl(out / "gsm8k.jsonl", items)
        print(f"gsm8k {len(items)}문항")

        tree = await client.get(
            f"https://huggingface.co/api/datasets/HAERAE-HUB/KMMLU/tree/{KMMLU_REV}/data"
        )
        tree.raise_for_status()
        subjects = sorted(
            p["path"].removeprefix("data/").removesuffix("-test.csv")
            for p in tree.json()
            if p["path"].endswith("-test.csv")
        )
        by_subject = {}
        for s in subjects:
            r = await client.get(KMMLU_CSV.format(rev=KMMLU_REV, subject=s))
            r.raise_for_status()
            by_subject[s] = list(csv.DictReader(io.StringIO(r.text)))
        items = sample_kmmlu(by_subject, KMMLU_PER_SUBJECT, SEED)
        _write_jsonl(out / "kmmlu.jsonl", items)
        print(f"kmmlu {len(subjects)}과목 {len(items)}문항 (리비전 {KMMLU_REV[:8]})")


# --- 채점 -----------------------------------------------------------------------------

_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+")
_ANSWER = re.compile(r"answer\s*[:：]\s*\**\s*\$?\s*(-?[\d,]*\.?\d+)", re.IGNORECASE)
_LETTER = re.compile(r"(?<![A-Za-z])([ABCD])(?![A-Za-z])")


def norm_number(s: str) -> str:
    s = s.strip().replace(",", "").replace("$", "").rstrip(".")
    try:
        v = float(s)
    except ValueError:
        return s
    return str(int(v)) if v == int(v) else f"{v:g}"


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


def grade_gsm8k(text: str, gold: str) -> tuple[str | None, bool]:
    text = strip_think(text)
    m = _ANSWER.findall(text)
    if m:
        pred = norm_number(m[-1])
    else:
        nums = _NUM.findall(text)
        pred = norm_number(nums[-1]) if nums else None
    return pred, pred is not None and pred == gold


_KO_ANSWER = re.compile(r"(?:정답|답)\s*(?:은|는|:|：)?\s*\**\s*\(?([ABCD])(?![A-Za-z])")


def grade_kmmlu(text: str, gold: str) -> tuple[str | None, bool]:
    """ "정답은 B" · "Answer: B" 가 먼저, 없으면 첫 글자 알파벳, 그다음 처음 나온 알파벳."""
    t = strip_think(text)
    m = _KO_ANSWER.search(t)
    m = m or re.search(r"answer\s*[:：]\s*\**\(?([ABCD])(?![A-Za-z])", t, re.IGNORECASE)
    m = m or re.match(r"\s*\**\(?([ABCD])(?![A-Za-z])", t) or _LETTER.search(t)
    pred = m.group(1) if m else None
    return pred, pred == gold


def grade(task: str, text: str, gold: str) -> tuple[str | None, bool]:
    return grade_gsm8k(text, gold) if task == "gsm8k" else grade_kmmlu(text, gold)


# --- 짝지은 비교 통계 ------------------------------------------------------------------


def _binom_cdf(k: int, n: int) -> float:
    return sum(math.comb(n, i) for i in range(k + 1)) / 2**n


def paired(a: dict[str, bool], b: dict[str, bool]) -> dict[str, Any]:
    """같은 문항끼리. b - a 정확도 차이(%p) · 95% 신뢰구간 · McNemar 정확 검정 p."""
    ids = sorted(set(a) & set(b))
    n = len(ids)
    if not n:
        return {"n": 0}
    only_a = sum(1 for i in ids if a[i] and not b[i])
    only_b = sum(1 for i in ids if b[i] and not a[i])
    d = [(1 if b[i] else 0) - (1 if a[i] else 0) for i in ids]
    mean = sum(d) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
    half = 1.96 * sd / math.sqrt(n)
    k = only_a + only_b
    p = min(1.0, 2 * _binom_cdf(min(only_a, only_b), k)) if k else 1.0
    return {
        "n": n,
        "acc_a": round(100 * sum(a[i] for i in ids) / n, 2),
        "acc_b": round(100 * sum(b[i] for i in ids) / n, 2),
        "diff_pp": round(100 * mean, 2),
        "ci95_pp": [round(100 * (mean - half), 2), round(100 * (mean + half), 2)],
        "only_a": only_a,
        "only_b": only_b,
        "p_mcnemar": round(p, 4),
    }


# --- 실행 -----------------------------------------------------------------------------


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def request_body(model: str, task: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": TASKS[task]["max_tokens"],
        "messages": [{"role": "user", "content": prompt_for(task, item)}],
        "chat_template_kwargs": {"enable_thinking": False},
        "metadata": {"tags": ["exp:quant", f"combo:{model}", f"task:{task}"]},
    }


async def ask(client: httpx.AsyncClient, body: dict[str, Any], tries: int = 3) -> dict[str, Any]:
    err = None
    for attempt in range(tries):
        t0 = time.perf_counter()
        try:
            r = await client.post("/v1/chat/completions", json=body, timeout=300)
            if r.status_code == 200:
                d = r.json()
                ch = (d.get("choices") or [{}])[0]
                usage = d.get("usage") or {}
                return {
                    "text": (ch.get("message") or {}).get("content") or "",
                    "finish": ch.get("finish_reason"),
                    "input_tokens": usage.get("prompt_tokens"),
                    "output_tokens": usage.get("completion_tokens"),
                    "latency_s": round(time.perf_counter() - t0, 3),
                }
            err = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (400, 401, 403, 404):
                break
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:160]}"
        await asyncio.sleep(2 * (attempt + 1))
    return {"error": err}


async def wait_ready(client: httpx.AsyncClient, model: str, timeout_s: float) -> None:
    """gateway 에 모델이 등록되고(worker, vLLM 응답 뒤) 한 번 답할 때까지."""
    t0 = time.monotonic()
    body = {"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
    body["metadata"] = {"tags": ["exp:quant", f"combo:{model}", "task:ready"]}
    while True:
        try:
            r = await client.post("/v1/chat/completions", json=body, timeout=60)
            if r.status_code == 200:
                print(f"  준비됨 ({time.monotonic() - t0:.0f}초 기다림)")
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() - t0 > timeout_s:
            sys.exit(f"{model}: {timeout_s:.0f}초 안에 준비되지 않았습니다")
        await asyncio.sleep(20)


async def run_task(
    client: httpx.AsyncClient, model: str, task: str, items: list, out: Path, conc: int
) -> dict[str, Any]:
    done = {r["id"] for r in read_jsonl(out) if "error" not in r}
    todo = [it for it in items if it["id"] not in done]
    kept = [r for r in read_jsonl(out) if "error" not in r]  # 실패한 문항은 다시
    _write_jsonl(out, kept)
    print(f"  {task}: {len(done)}문항 끝남, {len(todo)}문항 남음 (동시 {conc})")
    sem, t0, n = asyncio.Semaphore(conc), time.perf_counter(), 0
    with out.open("a") as f:

        async def one(it: dict[str, Any]) -> None:
            nonlocal n
            async with sem:
                res = await ask(client, request_body(model, task, it))
            row: dict[str, Any] = {"id": it["id"], "gold": it["gold"]}
            if "error" in res:
                row["error"] = res["error"]
            else:
                pred, ok = grade(task, res["text"], it["gold"])
                meta = {k: v for k, v in res.items() if k != "text"}
                row |= {"pred": pred, "correct": ok, **meta}
                row["text"] = res["text"][-400:]  # 실패 분석용 끝부분
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n += 1
            if n % 200 == 0:
                print(f"    {n}/{len(todo)} ({time.perf_counter() - t0:.0f}초)")

        await asyncio.gather(*[one(it) for it in todo])
    return score(read_jsonl(out))


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if "error" not in r]
    n = len(ok)
    return {
        "n": n,
        "errors": len(rows) - n,
        "acc": round(100 * sum(r["correct"] for r in ok) / n, 2) if n else None,
        "truncated": sum(1 for r in ok if r.get("finish") == "length"),
        "mean_output_tokens": round(sum(r.get("output_tokens") or 0 for r in ok) / n, 1)
        if n
        else None,
    }


_STATS = {
    "weights_gib": r"Model loading took ([\d.]+) GiB",
    "kv_gib": r"Available KV cache memory: ([\d.]+) GiB",
    "kv_tokens": r"GPU KV cache size: ([\d,]+) tokens",
    "download_s": r"Time spent downloading weights for .*?: ([\d.]+) seconds",
    "load_s": r"Model loading took [\d.]+ GiB memory and ([\d.]+) seconds",
    "init_s": r"init engine .*? took ([\d.]+) s",
}


def vllm_stats(text: str) -> dict[str, float]:
    """vLLM 기동 로그 → 실제 가중치 메모리 · KV 캐시 · 다운로드 · 로딩 시간 (마지막 기동 기준)."""
    out = {}
    for k, pat in _STATS.items():
        m = re.findall(pat, text)
        if m:
            out[k] = float(m[-1].replace(",", ""))
    return out


def combo_meta(name: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """exp-<모델>-<gpu> → 설정의 모델 정보 + gpu."""
    for gpu in cfg["gpus"]:
        model = name.removeprefix("exp-").removesuffix(f"-{gpu}")
        if name.endswith(f"-{gpu}") and model in cfg["models"]:
            return {**cfg["models"][model], "model": model, "gpu": gpu}
    return None


def load_results(results: Path) -> dict[str, dict[str, dict[str, bool]]]:
    """조합 → 과제 → {문항 id: 맞음}."""
    out: dict[str, dict[str, dict[str, bool]]] = {}
    for d in sorted(p for p in results.glob("*") if p.is_dir()):
        for task in TASKS:
            rows = [r for r in read_jsonl(d / f"{task}.jsonl") if "error" not in r]
            if rows:
                out.setdefault(d.name, {})[task] = {r["id"]: bool(r["correct"]) for r in rows}
    return out


def summarize(results: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    res = load_results(results)
    combos = []
    for name in res:
        meta = combo_meta(name, cfg) or {}
        log = LOGS / f"{name}-vllm.log"
        combos.append(
            {
                "name": name,
                "vllm": vllm_stats(log.read_text(errors="replace")) if log.exists() else {},
                **{k: meta.get(k) for k in ("size_b", "precision", "gpu")},
                **{t: score(read_jsonl(results / name / f"{t}.jsonl")) for t in res[name]},
            }
        )
    # 1) 같은 크기 · 같은 GPU 에서 정밀도를 낮췄을 때: bf16 → FP8, FP8 → AWQ, bf16 → AWQ
    drops = []
    by_key = {(c["size_b"], c["gpu"], c["precision"]): c["name"] for c in combos}
    steps = (("bf16", "fp8"), ("fp8", "awq"), ("bf16", "awq"))
    for size, gpu in sorted({(k[0], k[1]) for k in by_key}, key=lambda x: (x[0] or 0, x[1])):
        for hi, lo in steps:
            ref, name = by_key.get((size, gpu, hi)), by_key.get((size, gpu, lo))
            if not (ref and name):
                continue
            for task in TASKS:
                if task in res[ref] and task in res[name]:
                    drops.append(
                        {"size_b": size, "gpu": gpu, "from": ref, "to": name, "task": task}
                        | paired(res[ref][task], res[name][task])
                    )

    # 2) 같은 메모리: 작은 모델(원본 · 8비트) vs 큰 모델 4비트, 가중치 크기 기준
    #    - 가중치 차이 15% 안이면 "같은 메모리" (match = True)
    #    - 작은 모델 8비트 중 가장 가까운 것도 함께 (크기가 다르면 그대로 보여 준다)
    measured = all(c["vllm"].get("weights_gib") for c in combos)

    def weight(c: dict[str, Any]) -> float:
        """실제 가중치 메모리(vLLM 로그, GiB → GB)가 모두 있으면 그것, 아니면 설정의 파일 크기."""
        if measured:
            return round(c["vllm"]["weights_gib"] * 1.073741824, 2)
        return float(cfg["models"][combo_meta(c["name"], cfg)["model"]]["weight_gb"])

    same_mem, seen = [], set()
    for big in (c for c in combos if c["precision"] == "awq"):
        small = [
            o for o in combos
            if o["gpu"] == big["gpu"] and (o["size_b"] or 0) < (big["size_b"] or 0)
            and o["precision"] in ("bf16", "fp8")
        ]  # fmt: skip
        pick = [
            o for o in small if abs(weight(o) - weight(big)) <= 0.15 * max(weight(o), weight(big))
        ]
        fp8 = [o for o in small if o["precision"] == "fp8"]
        if fp8:
            pick.append(min(fp8, key=lambda o: abs(weight(o) - weight(big))))
        for o in pick:
            if (o["name"], big["name"]) in seen:
                continue
            seen.add((o["name"], big["name"]))
            match = abs(weight(o) - weight(big)) <= 0.15 * max(weight(o), weight(big))
            for task in TASKS:
                if task in res[o["name"]] and task in res[big["name"]]:
                    same_mem.append(
                        {
                            "small": o["name"],
                            "big": big["name"],
                            "task": task,
                            "small_gb": weight(o),
                            "big_gb": weight(big),
                            "match": match,
                        }
                        | paired(res[o["name"]][task], res[big["name"]][task])
                    )
    return {"combos": combos, "drops": drops, "same_memory": same_mem, "measured_memory": measured}


def render(s: dict[str, Any]) -> str:
    lines = ["## 조합별 정확도", ""]
    lines += ["| 조합 | 크기 | 정밀도 | GSM8K | KMMLU | 잘림 · 오류 | 가중치 GiB | KV GiB |"]
    lines += ["|---|---|---|---|---|---|---|---|"]

    for c in s["combos"]:
        cells = []
        for t in TASKS:
            sc = c.get(t)
            cells.append(f"{sc['acc']}% (n={sc['n']})" if sc else "-")
        cut = sum((c.get(t) or {}).get("truncated", 0) for t in TASKS)
        err = sum((c.get(t) or {}).get("errors", 0) for t in TASKS)
        lines.append(
            f"| {c['name']} | {c['size_b'] or '-'}B | {c['precision'] or '-'} "
            f"| {cells[0]} | {cells[1]} | {cut} · {err} "
            f"| {c['vllm'].get('weights_gib', '-')} | {c['vllm'].get('kv_gib', '-')} |"
        )
    sep = "|---|---|---|---|---|---|---|"
    lines += ["", "## 정밀도를 낮췄을 때 (같은 문항 짝지어 비교)", ""]
    lines += ["| 크기 | 과제 | 비교 | 앞 → 뒤 | 차이(%p) | 95% 구간 | p |", sep]
    for d in s["drops"]:
        pa, pb = d["from"].split("-")[3], d["to"].split("-")[3]
        lines.append(
            f"| {d['size_b']}B | {d['task']} | {pa} → {pb} | {d['acc_a']} → {d['acc_b']} "
            f"| {d['diff_pp']:+} | {d['ci95_pp']} | {d['p_mcnemar']} |"
        )
    src = "vLLM 실측" if s.get("measured_memory") else "파일 크기"
    lines += ["", f"## 같은 메모리라면: 작은 모델 vs 큰 모델 4비트 (가중치 GB, {src})", ""]
    head = "| 과제 | 작은 모델 | 큰 모델 4비트 | 같은 메모리 | 정확도 | 차이(%p) | 95% 구간 | p |"
    lines += [head, sep + "---|"]
    for d in s["same_memory"]:
        mem = f"{d['small_gb']} vs {d['big_gb']}GB" + (" ✓" if d["match"] else "")
        lines.append(
            f"| {d['task']} | {d['small']} | {d['big']} | {mem} | {d['acc_a']} → {d['acc_b']} "
            f"| {d['diff_pp']:+} | {d['ci95_pp']} | {d['p_mcnemar']} |"
        )
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> None:
    key = os.environ.get("TOLLGATE_EXP_KEY") or sys.exit("TOLLGATE_EXP_KEY 가 없습니다")
    headers = {"Authorization": f"Bearer {key}"}
    limits = httpx.Limits(max_connections=args.concurrency + 4)
    async with httpx.AsyncClient(base_url=args.gateway, headers=headers, limits=limits) as client:
        if args.wait:
            await wait_ready(client, args.model, args.wait)
        for task in args.task.split(","):
            items = read_jsonl(DATA / f"{task}.jsonl")
            if not items:
                sys.exit(f"{DATA / task}.jsonl 가 없습니다 (prepare 먼저)")
            if args.limit:
                items = items[: args.limit]
            out = RESULTS / args.model / f"{task}.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            print(json.dumps({task: await run_task(client, args.model, task, items, out,
                                                   args.concurrency)}))  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--task", default="gsm8k,kmmlu")
    r.add_argument("--concurrency", type=int, default=32)
    r.add_argument("--limit", type=int)
    r.add_argument("--wait", type=float, default=0, help="모델이 준비될 때까지 최대 몇 초")
    r.add_argument("--gateway", default=GATEWAY)
    s = sub.add_parser("summary")
    s.add_argument("--json", action="store_true")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--task", default="gsm8k")
    args = ap.parse_args()
    if args.cmd == "prepare":
        asyncio.run(prepare(DATA))
    elif args.cmd == "run":
        asyncio.run(run(args))
    elif args.cmd == "summary":
        s = summarize(RESULTS, yaml.safe_load(CONFIG.read_text()))
        print(json.dumps(s, ensure_ascii=False, indent=2) if args.json else render(s))
    elif args.cmd == "compare":
        res = load_results(RESULTS)
        print(json.dumps(paired(res[args.a][args.task], res[args.b][args.task]), indent=2))


if __name__ == "__main__":
    main()
