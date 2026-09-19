"""LLM benchmark for whatever model the local llama.cpp server is serving.

    python scripts/bench_llm.py --label spark-x2.5-4b

Measures what a live voice loop actually depends on: time to first token, tokens
per second, whether the thinking pass can be switched off, and how much VRAM the
model holds.  Run scripts/llm_serve.py --start <model> first.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lva import config as C  # noqa: E402
from lva import llm as LLM  # noqa: E402

TASKS: list[tuple[str, str, str]] = [
    ("chat", "fast", "你好，简单介绍一下你自己，一句话就好。"),
    ("short_cmd", "fast", "把“我需要整理实验数据”改得更正式一点。"),
    ("simple_chem", "fast", "铜离子和EDTA为什么会形成稳定的络合物？一句话回答。"),
    ("sci_terms", "fast", "用一句话解释什么是配位数，并提到螯合效应。"),
    ("deep_chem", "deep", "请逐步推导Michaelis-Menten方程的稳态近似过程。"),
    ("history_ish", "fast", "我刚才说过什么关于络合滴定的事情吗？如果没有记录就直接说没有。"),
]


def vram_used() -> float | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        return float(out.stdout.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return None


def run_task(label: str, mode: str, prompt: str) -> dict:
    msgs = [{"role": "system", "content": "你是本地语音助手，回答简短、口语化、简体中文。"},
            {"role": "user", "content": prompt}]
    t0 = time.perf_counter()
    ttft = None
    parts: list[str] = []
    err = None
    try:
        # No explicit max_tokens: the mode picks the budget.  Passing one here
        # would cap a deep question below its thinking pass and yield no answer.
        stream = LLM.stream(msgs, mode=mode)
        for piece in stream:
            if ttft is None:
                ttft = (time.perf_counter() - t0) * 1000
            parts.append(piece)
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    total = (time.perf_counter() - t0) * 1000
    text = "".join(parts)
    return {
        "task": label, "mode": mode, "ttft_ms": round(ttft, 1) if ttft else None,
        "total_ms": round(total, 1), "chars": len(text),
        "chars_per_s": round(len(text) / (total / 1000), 1) if total else 0.0,
        "reply": text[:400], "error": err,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=C.LLM_MODEL)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    health = LLM.health()
    if not health.get("ok"):
        print(f"LLM server not reachable: {health.get('error')}")
        return 2
    print(f"server ok, models={health['models']}")

    served = health["models"][0] if health["models"] else C.LLM_MODEL
    vram_before = vram_used()
    rows = []
    for label, mode, prompt in TASKS:
        best = None
        for _ in range(a.repeats):
            r = run_task(label, mode, prompt)
            if r["error"]:
                best = r
                break
            if best is None or (r["ttft_ms"] or 1e9) < (best["ttft_ms"] or 1e9):
                best = r
        rows.append(best)
        ttft = f"{best['ttft_ms']:.0f}ms" if best["ttft_ms"] else "n/a"
        print(f"  {label:12s} {mode:5s} ttft={ttft:>8s} total={best['total_ms']:>7.0f}ms "
              f"{best['chars_per_s']:>6.1f} ch/s" + (f"  ERR {best['error']}" if best["error"] else ""))

    fast = [r["ttft_ms"] for r in rows if r["mode"] == "fast" and r["ttft_ms"]]
    result = {
        "label": a.label,
        "served_model": served,
        "endpoint": C.LLM_BASE_URL,
        "vram_used_mb": {"before": vram_before, "after": vram_used()},
        "fast_ttft_ms": {"median": round(statistics.median(fast), 1) if fast else None,
                         "min": round(min(fast), 1) if fast else None,
                         "max": round(max(fast), 1) if fast else None},
        "rows": rows,
    }
    out = Path(a.out) if a.out else C.BENCH / f"llm-{a.label}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  VRAM used: {vram_before} -> {result['vram_used_mb']['after']} MB")
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
