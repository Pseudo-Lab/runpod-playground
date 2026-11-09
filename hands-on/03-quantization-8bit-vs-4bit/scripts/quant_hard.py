"""양자화 실험 2차: 어려운 문항 · 금융 · 3번 반복 (P38). tollgate gateway 를 거쳐 부른다.

1차(P36)는 문제가 쉬워(GSM8K 4B 이상 90%+) 4비트 손실이 드러날 여지가 적었다. 그래서
- math_hard: 한국어 수학 MATH Level 5 (HRM8K, 가장 어려운 단계) 400문항, 숫자 답 (MIT)
- kmmlu_hard: KMMLU-HARD 금융 외 39과목 × 15문항 (강한 모델도 틀린 문항만 모은 판, CC-BY-ND)
- fin: 금융. KMMLU-HARD 회계 · 세무 · 경제 · 경영 · 마케팅 · 부동산 전부
  + 한국어 금융 MMLU (5지선다)
- 조합마다 같은 Pod 에서 3번 반복 (temperature 0.7 · top_p 0.8, 반복마다 seed 다름) → 평균 · 흔들림
- 8bit vs 4bit 비교는 문항별 3번 평균 정답률을 짝지어 (차이 · 95% 구간 · p)

    uv run python scripts/quant_hard.py prepare
    TOLLGATE_EXP_KEY=... uv run python scripts/quant_hard.py run --model exp-g4-12b-qat-ada48
    uv run python scripts/quant_hard.py summary [--json]

원장 tags: exp:hard · combo:<모델> · task:<과제> · run:<1~3>
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import os
import random
import re
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("quant_eval", ROOT / "scripts/quant_eval.py")
qe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qe)

DATA = ROOT / "data" / "exp"
HARD = DATA / "hard"
CONFIG = Path(os.environ.get("TOLLGATE_EXP_CONFIG") or ROOT / "config" / "runpod_exp.yaml")
GATEWAY = os.environ.get("TOLLGATE_GATEWAY_URL", "http://127.0.0.1:4000")
ROWS = "https://datasets-server.huggingface.co/rows?dataset={ds}&config={cfg}&split=test"
SEED = 38
REPEATS = 3
SAMPLING = {"temperature": 0.7, "top_p": 0.8}  # Qwen 권장(thinking 끔). 모든 모델 같은 값
FIN_SUBJECTS = ("accounting", "taxation", "economics", "management", "marketing", "real_estate")
TASKS: dict[str, dict[str, Any]] = {
    "math_hard": {"max_tokens": 1536, "label": "어려운 수학"},
    "kmmlu_hard": {"max_tokens": 128, "label": "어려운 한국어 지식"},
    "fin": {"max_tokens": 128, "label": "금융"},
    # P39 KV 캐시: 긴 문서(약 1만 토큰) 속 메모 5개 중 하나를 찾아 숫자로 답한다
    "needle": {"max_tokens": 32, "label": "긴 문서 찾기"},
}
NEEDLE_CHARS = 14000  # 한국어 약 1만 토큰 (max_model_len 16384 안)
LETTERS = "ABCDE"
MATH_SUFFIX = "\n\n단계별로 간단히 풀고, 마지막 줄에 '정답: <숫자>' 형식으로 답하세요."


# --- 문제 세트 -------------------------------------------------------------------------


async def _rows(client: httpx.AsyncClient, ds: str, cfg: str) -> list[dict[str, Any]]:
    cache = DATA / "cache" / f"{ds.replace('/', '__')}__{cfg}.json"  # 다시 받지 않게
    if cache.exists():
        return json.loads(cache.read_text())
    out, off = [], 0
    while True:
        for attempt in range(8):  # datasets-server 가 가끔 502 · 429 (요청 제한)
            r = await client.get(ROWS.format(ds=ds, cfg=cfg) + f"&offset={off}&length=100")
            if r.status_code == 200:
                break
            await asyncio.sleep(10 * (attempt + 1))
        r.raise_for_status()
        d = r.json()
        out += [x["row"] for x in d["rows"]]
        off += 100
        await asyncio.sleep(1.5)
        if off >= d["num_rows_total"]:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(out, ensure_ascii=False))
            return out


def mcq_item(iid: str, subject: str, question: str, choices: list[str], gold_idx: int) -> dict:
    return {
        "id": iid,
        "subject": subject,
        "question": question,
        "choices": choices,
        "gold": LETTERS[gold_idx],
    }


def parse_allganize(row: dict[str, Any], idx: int) -> dict[str, Any] | None:
    """'질문\\n1. 보기\\n2. 보기 …' + 답 '4' → 보기 목록 · 정답 글자."""
    conv = row["conversations"]
    text, ans = conv[0]["value"], conv[1]["value"].strip()
    parts = re.split(r"\n(?=[1-5]\.\s)", text)
    if len(parts) < 3 or not ans.isdigit():
        return None
    choices = [re.sub(r"^[1-5]\.\s*", "", p).strip() for p in parts[1:]]
    if not 1 <= int(ans) <= len(choices) <= 5:
        return None
    return mcq_item(f"fin-mmlu-{idx}", "financial-mmlu-ko", parts[0].strip(), choices, int(ans) - 1)


async def prepare(out: Path) -> None:
    os.makedirs(out, exist_ok=True)
    rng = random.Random(SEED)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        rows = await _rows(client, "HAERAE-HUB/HRM8K", "MATH")
        l5 = [(i, r) for i, r in enumerate(rows) if r.get("level") == "Level 5"]
        pick = sorted(rng.sample(range(len(l5)), 400))
        items = [
            {
                "id": f"math-{l5[k][0]}",
                "subject": l5[k][1].get("type"),
                "question": l5[k][1]["question"],
                "gold": float(l5[k][1]["answer"]),
            }
            for k in pick
        ]
        qe._write_jsonl(out / "math_hard.jsonl", items)
        print(f"math_hard {len(items)}문항 (MATH Level 5 {len(l5)}개 중)")

        sizes = (
            await client.get(
                "https://datasets-server.huggingface.co/size?dataset=HAERAE-HUB/KMMLU-HARD"
            )
        ).json()
        subjects = sorted({s["config"] for s in sizes["size"]["splits"] if s["split"] == "test"})
        hard, fin = [], []
        for s in subjects:
            rs = await _rows(client, "HAERAE-HUB/KMMLU-HARD", s)
            conv = [
                mcq_item(f"{s}-{i}", s, r["question"], [r[k] for k in "ABCD"], int(r["answer"]) - 1)
                for i, r in enumerate(rs)
            ]
            if s in FIN_SUBJECTS:
                fin += conv
            else:
                hard += [conv[i] for i in sorted(rng.sample(range(len(conv)), min(15, len(conv))))]
        qe._write_jsonl(out / "kmmlu_hard.jsonl", hard)
        rs = await _rows(client, "allganize/financial-mmlu-ko", "default")
        fin += [x for i, r in enumerate(rs) if (x := parse_allganize(r, i))]
        qe._write_jsonl(out / "fin.jsonl", fin)
        print(f"kmmlu_hard {len(hard)}문항 · fin {len(fin)}문항")


# --- 채점 -----------------------------------------------------------------------------

_FRAC = re.compile(r"\\[dt]?frac\{(-?[\d.]+)\}\{(-?[\d.]+)\}")
_BOXED = re.compile(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}")
_MATH_ANS = re.compile(r"(?:정답|답|answer)\s*[:：]?\s*(.+)", re.IGNORECASE)


def to_number(s: str) -> float | None:
    s = s.strip().strip("$").replace(",", "").replace("\\!", "").replace(" ", "")
    s = s.replace("\\left", "").replace("\\right", "").rstrip(".")
    m = _FRAC.search(s)
    if m:
        try:
            v = float(m.group(1)) / float(m.group(2))
            return -v if s.startswith("-\\") else v
        except ZeroDivisionError:
            return None
    m = re.fullmatch(r"\(?(-?[\d.]+)/(-?[\d.]+)\)?", s)
    if m:
        try:
            return float(m.group(1)) / float(m.group(2))
        except ZeroDivisionError:
            return None
    nums = qe._NUM.findall(s)
    try:
        return float(nums[0].replace(",", "")) if nums else None
    except ValueError:
        return None


def grade_math(text: str, gold: float) -> tuple[str | None, bool]:
    """'정답: X' (마지막) → \\boxed{X} → 마지막 숫자. 분수 · 소수는 값으로 비교."""
    t = qe.strip_think(text)
    cand = None
    lines = [m.group(1) for m in _MATH_ANS.finditer(t)]
    if lines:
        cand = lines[-1]
    elif b := _BOXED.findall(t):
        cand = b[-1]
    else:
        nums = qe._NUM.findall(t)
        cand = nums[-1] if nums else None
    if cand is None:
        return None, False
    v = to_number(cand)
    if v is None:
        return cand[:40], False
    ok = abs(v - gold) <= max(1e-6, 1e-4 * abs(gold))
    return f"{v:g}", ok


_KO = re.compile(r"(?:정답|답)\s*(?:은|는|:|：)?\s*\**\s*\(?([A-E])(?![A-Za-z])")
_EN = re.compile(r"answer\s*[:：]\s*\**\(?([A-E])(?![A-Za-z])", re.IGNORECASE)
_ANY = re.compile(r"(?<![A-Za-z])([A-E])(?![A-Za-z])")


def grade_mcq(text: str, gold: str, n: int) -> tuple[str | None, bool]:
    letters = LETTERS[:n]
    t = qe.strip_think(text)
    m = (
        _KO.search(t)
        or _EN.search(t)
        or re.match(r"\s*\**\(?([A-E])(?![A-Za-z])", t)
        or _ANY.search(t)
    )
    pred = m.group(1) if m and m.group(1) in letters else None
    return pred, pred == gold


def build_needles(filler: list[str], n: int, chars: int, seed: int) -> list[dict[str, Any]]:
    """긴 문서 찾기: 한국어 문장 더미 사이에 '프로젝트 코드 → 승인 번호' 메모 5개를
    무작위 위치에 넣고 그중 하나를 묻는다. 정답은 5자리 숫자 (그대로 일치해야 정답)."""
    rng = random.Random(seed)
    out = []
    for k in range(n):
        body, size = [], 0
        while size < chars:
            s = rng.choice(filler)
            body.append(s)
            size += len(s) + 1
        notes = []
        for _ in range(5):
            code = f"청람-{rng.randint(100, 999)}"
            num = str(rng.randint(10000, 99999))
            notes.append((code, num))
            body.insert(
                rng.randint(0, len(body)),
                f"[사내 메모] 프로젝트 '{code}'의 승인 번호는 {num}입니다.",
            )
        code, num = rng.choice(notes)
        doc = "\n".join(body)
        prompt = (
            f"다음 문서를 읽고 질문에 답하세요.\n\n<문서>\n{doc}\n</문서>\n\n"
            f"질문: 문서에서 프로젝트 '{code}'의 승인 번호는 무엇입니까? 숫자만 답하세요."
        )
        out.append({"id": f"needle-{k}", "prompt": prompt, "gold": num, "chars": len(doc)})
    return out


def prepare_needle(out: Path) -> None:
    filler = []
    for name in ("kmmlu.jsonl", "kmmlu_hard.jsonl", "fin.jsonl"):
        for it in qe.read_jsonl(out / name):
            filler.append(it["question"].strip().replace("\n", " "))
            filler += [c.strip().replace("\n", " ") for c in it["choices"] if len(c.strip()) > 10]
    items = build_needles([f for f in filler if f], 150, NEEDLE_CHARS, SEED + 1)
    qe._write_jsonl(out / "needle.jsonl", items)
    print(f"needle {len(items)}문항 (문서 약 {NEEDLE_CHARS:,}자)")


def grade_needle(text: str, gold: str) -> tuple[str | None, bool]:
    nums = re.findall(r"\d{5}", qe.strip_think(text).replace(",", ""))
    pred = nums[0] if nums else None
    return pred, pred == gold


def prompt_for(task: str, item: dict[str, Any]) -> str:
    if task == "needle":
        return item["prompt"]
    if task == "math_hard":
        return item["question"] + MATH_SUFFIX
    letters = LETTERS[: len(item["choices"])]
    opts = "\n".join(f"{k}. {c}" for k, c in zip(letters, item["choices"], strict=True))
    tail = ", ".join(letters)
    q = item["question"]
    return f"다음 문제의 정답을 고르세요.\n\n{q}\n{opts}\n\n정답 알파벳({tail}) 하나만 답하세요."


def grade(task: str, item: dict[str, Any], text: str) -> tuple[str | None, bool]:
    if task == "needle":
        return grade_needle(text, item["gold"])
    if task == "math_hard":
        return grade_math(text, item["gold"])
    return grade_mcq(text, item["gold"], len(item["choices"]))


def request_body(model: str, task: str, item: dict[str, Any], run: int) -> dict[str, Any]:
    return {
        "model": model,
        **SAMPLING,
        "seed": run,
        "max_tokens": TASKS[task]["max_tokens"],
        "messages": [{"role": "user", "content": prompt_for(task, item)}],
        "chat_template_kwargs": {"enable_thinking": False},
        "metadata": {"tags": ["exp:hard", f"combo:{model}", f"task:{task}", f"run:{run}"]},
    }


# --- 실행 -----------------------------------------------------------------------------


async def run_task(client, model: str, task: str, items: list, run: int, conc: int) -> dict:
    out = HARD / model / f"{task}.r{run}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    kept = [r for r in qe.read_jsonl(out) if "error" not in r]  # 실패한 문항은 다시
    qe._write_jsonl(out, kept)
    done = {r["id"] for r in kept}
    todo = [it for it in items if it["id"] not in done]
    print(f"  {task} 반복 {run}: {len(done)} 끝남, {len(todo)} 남음", flush=True)
    sem = asyncio.Semaphore(conc)
    with out.open("a") as f:

        async def one(it: dict[str, Any]) -> None:
            async with sem:
                res = await qe.ask(client, request_body(model, task, it, run))
            row: dict[str, Any] = {"id": it["id"], "gold": it["gold"]}
            if "error" in res:
                row["error"] = res["error"]
            else:
                pred, ok = grade(task, it, res["text"])
                row |= {
                    "pred": pred,
                    "correct": ok,
                    **{k: v for k, v in res.items() if k != "text"},
                }
                row["text"] = res["text"][-300:]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()

        await asyncio.gather(*[one(it) for it in todo])
    s = qe.score(qe.read_jsonl(out))
    print(json.dumps({"task": task, "run": run, **s}), flush=True)
    return s


async def run(args: argparse.Namespace) -> None:
    key = os.environ.get("TOLLGATE_EXP_KEY") or sys.exit("TOLLGATE_EXP_KEY 가 없습니다")
    headers = {"Authorization": f"Bearer {key}"}
    limits = httpx.Limits(max_connections=args.concurrency + 4)
    async with httpx.AsyncClient(base_url=args.gateway, headers=headers, limits=limits) as client:
        if args.wait:
            await qe.wait_ready(client, args.model, args.wait)
        for rep in range(1, args.repeats + 1):  # 같은 Pod 에서 반복 (기동 비용 한 번)
            for task in args.task.split(","):
                items = qe.read_jsonl(DATA / f"{task}.jsonl")
                if not items:
                    sys.exit(f"{task}.jsonl 가 없습니다 (prepare 먼저)")
                await run_task(
                    client, args.model, task, items[: args.limit or None], rep, args.concurrency
                )


# --- 요약 -----------------------------------------------------------------------------


def combo_meta(name: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    meta = qe.combo_meta(name, cfg)
    if not meta:
        return None
    model = meta["model"]
    bits = {"bf16": 16, "fp8": 8}.get(meta["precision"], 4)
    family = meta.get("family") or ("qwen3.5" if model.startswith("q35") else "gemma4")
    return meta | {
        "base": model.rsplit("-", 1)[0],
        "bits": bits,
        "family": family,
        "arch": meta.get("arch") or "dense",
    }


def load_runs(combo_dir: Path) -> dict[str, dict[int, dict[str, bool]]]:
    """과제 → 반복 → {문항: 맞음}."""
    out: dict[str, dict[int, dict[str, bool]]] = {}
    for p in sorted(combo_dir.glob("*.r*.jsonl")):
        task, r = p.name.removesuffix(".jsonl").rsplit(".r", 1)
        rows = [x for x in qe.read_jsonl(p) if "error" not in x]
        if rows:
            out.setdefault(task, {})[int(r)] = {x["id"]: bool(x["correct"]) for x in rows}
    return out


def item_means(runs: dict[int, dict[str, bool]]) -> dict[str, float]:
    ids = set.intersection(*(set(v) for v in runs.values())) if runs else set()
    return {i: sum(runs[r][i] for r in runs) / len(runs) for i in ids}


def paired_means(a: dict[str, float], b: dict[str, float]) -> dict[str, Any]:
    """문항별 평균 정답률(0 · ⅓ · ⅔ · 1)의 짝 차이 b − a: %p · 95% 구간 · 양측 p (정규 근사)."""
    ids = sorted(set(a) & set(b))
    n = len(ids)
    if n < 2:
        return {"n": n}
    d = [b[i] - a[i] for i in ids]
    mean = sum(d) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in d) / (n - 1))
    se = sd / math.sqrt(n)
    z = mean / se if se else 0.0
    p = math.erfc(abs(z) / math.sqrt(2)) if se else 1.0
    return {
        "n": n,
        "acc_a": round(100 * sum(a[i] for i in ids) / n, 2),
        "acc_b": round(100 * sum(b[i] for i in ids) / n, 2),
        "diff_pp": round(100 * mean, 2),
        "ci95_pp": [round(100 * (mean - 1.96 * se), 2), round(100 * (mean + 1.96 * se), 2)],
        "p": round(p, 4),
    }


def summarize(cfg: dict[str, Any], hard: Path = HARD) -> dict[str, Any]:
    combos: dict[str, dict[str, Any]] = {}
    for d in sorted(p for p in hard.glob("*") if p.is_dir()):
        meta = combo_meta(d.name, cfg)
        runs = load_runs(d)
        if not meta or not runs:
            continue
        tasks = {}
        for task, rr in runs.items():
            accs = [100 * sum(v.values()) / len(v) for _, v in sorted(rr.items())]
            tasks[task] = {
                "runs": len(rr),
                "acc_runs": [round(a, 2) for a in accs],
                "acc_mean": round(sum(accs) / len(accs), 2),
                "spread_pp": round(max(accs) - min(accs), 2),
                "n": len(item_means(rr)),
            }
        combos[d.name] = {
            "meta": meta,
            "tasks": tasks,
            "items": {t: item_means(r) for t, r in runs.items()},
        }
    pairs = []
    # 기본 모델 → 8bit 1개 · 4bit 여러 개 (P39: 같은 모델의 AWQ 와 NVFP4 를 모두 8bit 와 비교)
    by_base: dict[str, dict[str, Any]] = {}
    for name, c in sorted(combos.items()):
        slot = by_base.setdefault(c["meta"]["base"], {"8": None, "4": []})
        if c["meta"]["bits"] == 8:
            slot["8"] = name
        elif c["meta"]["bits"] == 4:
            slot["4"].append(name)
    for base, m in sorted(by_base.items()):
        if not m["8"]:
            continue
        a = combos[m["8"]]
        for w4 in m["4"]:
            b = combos[w4]
            meta = a["meta"]
            row = {
                "base": base,
                "family": meta["family"],
                "arch": meta["arch"],
                "size_b": meta["size_b"],
                "active_b": meta.get("active_b"),
                "fp8": m["8"],
                "w4": w4,
                "w4_method": b["meta"]["precision"],
                "tasks": {},
            }
            for task in TASKS:
                if task in a["items"] and task in b["items"]:
                    row["tasks"][task] = paired_means(a["items"][task], b["items"][task])
            pairs.append(row)
    for c in combos.values():
        c.pop("items")
    return {"combos": combos, "pairs": pairs, "sampling": SAMPLING, "repeats": REPEATS}


def render(s: dict[str, Any]) -> str:
    lines = [
        "| 모델 | 구조 | 4bit 방식 | 과제 | 8bit → 4bit (%, 3회 평균) | 차이 %p | 95% 구간 | p |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in sorted(s["pairs"], key=lambda x: (x["family"], x["arch"], x["size_b"])):
        for task, r in p["tasks"].items():
            if r.get("n", 0) < 2:
                continue
            lines.append(
                f"| {p['base']} | {p['arch']} | {p['w4_method']} | {TASKS[task]['label']} "
                f"| {r['acc_a']} → {r['acc_b']} | {r['diff_pp']:+} | {r['ci95_pp']} | {r['p']} |"
            )
    lines += ["", "| 조합 | 과제 | 반복별 정답률 | 흔들림(최대−최소) |", "|---|---|---|---|"]
    for name, c in s["combos"].items():
        for task, t in c["tasks"].items():
            lines.append(
                f"| {name} | {TASKS[task]['label']} | {t['acc_runs']} | {t['spread_pp']} |"
            )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    sub.add_parser("prepare-needle")
    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--task", default="math_hard,kmmlu_hard,fin")
    r.add_argument("--repeats", type=int, default=REPEATS)
    r.add_argument("--concurrency", type=int, default=64)
    r.add_argument("--limit", type=int)
    r.add_argument("--wait", type=float, default=0)
    r.add_argument("--gateway", default=GATEWAY)
    s = sub.add_parser("summary")
    s.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.cmd == "prepare":
        asyncio.run(prepare(DATA))
    elif args.cmd == "prepare-needle":
        prepare_needle(DATA)
    elif args.cmd == "run":
        asyncio.run(run(args))
    else:
        res = summarize(yaml.safe_load(CONFIG.read_text()))
        print(json.dumps(res, ensure_ascii=False, indent=2) if args.json else render(res))


if __name__ == "__main__":
    main()
