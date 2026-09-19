"""ASR benchmark for one engine, in its own process so memory numbers are clean.

    python scripts/bench_asr.py --engine sensevoice [--threads 6]

Writes benchmarks/asr-<engine>.json and prints a short summary.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lva import asr as ASR  # noqa: E402
from lva import audio as A  # noqa: E402
from lva import config as C  # noqa: E402
from lva import textutil as TX  # noqa: E402

try:
    import psutil
except Exception:  # noqa: BLE001
    psutil = None

# Homophone confusions this project specifically cares about.
CONFUSIONS = ["洛河", "落合", "络河", "络和", "落和"]


def rss_mb() -> float:
    if psutil is None:
        return float("nan")
    return psutil.Process().memory_info().rss / 1024 / 1024


def run_set(engine, manifest: dict, hotwords: list[str] | None = None) -> dict:
    rows = []
    for it in manifest["items"]:
        samples, sr = A.read_wav(it["wav"])
        if sr != C.ASR_RATE:
            samples = A.resample(samples, sr, C.ASR_RATE)
        # real files are already 16k; sci clips come from TTS at their own rate
        res = engine.transcribe(samples, hotwords=hotwords)
        text = ASR.clean(res.text)
        row = {
            "id": it["id"],
            "ref": it["ref"],
            "text": text,
            "domain": it.get("domain", "general"),
            "variant": it.get("variant", ""),
            "terms": it.get("terms", []),
            "cer": TX.cer(it["ref"], text),
            "audio_s": round(res.audio_s, 3),
            "decode_ms": round(res.decode_ms, 1),
            "rtf": round(res.rtf, 4),
        }
        if it.get("terms"):
            hit, total = TX.contains_terms(text, it["terms"])
            row["term_hit"] = f"{hit}/{total}"
        rows.append(row)
    return {"rows": rows}


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {}
    cers = [r["cer"] for r in rows]
    rtfs = sorted(r["rtf"] for r in rows)
    lat = sorted(r["decode_ms"] for r in rows)
    p95 = rtfs[min(len(rtfs) - 1, int(round(0.95 * (len(rtfs) - 1))))]
    return {
        "n": len(rows),
        "cer_mean": round(statistics.fmean(cers), 4),
        "cer_median": round(statistics.median(cers), 4),
        "rtf_mean": round(statistics.fmean(rtfs), 4),
        "rtf_p95": round(p95, 4),
        "decode_ms_mean": round(statistics.fmean(lat), 1),
        "decode_ms_p95": round(lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))], 1),
        "exact_match": round(sum(1 for r in rows if r["cer"] == 0) / len(rows), 3),
    }


def confusion_report(rows: list[dict]) -> dict:
    """Did '络合' survive, and which wrong forms turned up instead?"""
    good = 0
    bad_forms: dict[str, int] = {}
    for r in rows:
        if "络合" in r["ref"]:
            if "络合" in r["text"]:
                good += 1
            for form in CONFUSIONS:
                if form in r["text"]:
                    bad_forms[form] = bad_forms.get(form, 0) + 1
    total = sum(1 for r in rows if "络合" in r["ref"])
    return {"expected": total, "correct": good, "wrong_forms": bad_forms}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--threads", type=int, default=C.ASR_THREADS)
    ap.add_argument("--cold-repeats", type=int, default=3,
                    help="re-run the first clip to estimate first-call latency")
    args = ap.parse_args()

    base_rss = rss_mb()
    t0 = time.perf_counter()
    engine = ASR.load(args.engine, threads=args.threads)
    load_s = time.perf_counter() - t0
    loaded_rss = rss_mb()

    real = json.loads((C.BENCH / "manifest_real.json").read_text(encoding="utf-8"))
    sci = json.loads((C.BENCH / "manifest_sci.json").read_text(encoding="utf-8"))

    # First-call latency (cold caches) measured before the bulk runs.
    first = real["items"][0]
    s, sr = A.read_wav(first["wav"])
    cold = []
    for _ in range(args.cold_repeats):
        t = time.perf_counter()
        engine.transcribe(s)
        cold.append((time.perf_counter() - t) * 1000.0)

    real_res = run_set(engine, real)
    sci_res = run_set(engine, sci)

    result = {
        "engine": args.engine,
        "backend": "sherpa-onnx",
        "device": "cpu",
        "threads": args.threads,
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "load_s": round(load_s, 2),
        "rss_mb": {"baseline": round(base_rss, 1), "after_load": round(loaded_rss, 1),
                   "delta": round(loaded_rss - base_rss, 1)},
        "vram_mb": 0,
        "first_call_ms": [round(x, 1) for x in cold],
        "real": summarize(real_res["rows"]),
        "sci": summarize(sci_res["rows"]),
        "sci_by_variant": {
            v: summarize([r for r in sci_res["rows"] if r["variant"] == v])
            for v in sorted({r["variant"] for r in sci_res["rows"]})
        },
        "confusion": confusion_report(sci_res["rows"]),
        "rows_real": real_res["rows"],
        "rows_sci": sci_res["rows"],
    }

    out = C.BENCH / f"asr-{args.engine}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"[{args.engine}] load={load_s:.2f}s rss+={loaded_rss - base_rss:.0f}MB "
          f"first_call={cold[0]:.0f}ms")
    print(f"  real: CER={result['real']['cer_mean']:.4f} exact={result['real']['exact_match']} "
          f"RTF={result['real']['rtf_mean']:.4f} p95={result['real']['rtf_p95']:.4f} "
          f"decode_p95={result['real']['decode_ms_p95']:.0f}ms")
    print(f"  sci:  CER={result['sci']['cer_mean']:.4f} RTF={result['sci']['rtf_mean']:.4f}")
    for v, s in result["sci_by_variant"].items():
        print(f"        {v:9s} CER={s['cer_mean']:.4f} exact={s['exact_match']}")
    print(f"  络合: {result['confusion']['correct']}/{result['confusion']['expected']} correct, "
          f"wrong forms={result['confusion']['wrong_forms'] or '{}'}")
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
