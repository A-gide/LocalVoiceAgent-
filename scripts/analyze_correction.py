"""Score the terminology corrector against the saved ASR benchmark rows.

Re-decoding is unnecessary: the raw transcripts are already in
benchmarks/asr-*.json, so this replays them through vocab.py and reports what
correction buys for each engine.  That matters because the engine that wins on
raw accuracy is not always the one that wins after correction.

Run:  python scripts/analyze_correction.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lva import config as C  # noqa: E402
from lva import textutil as TX  # noqa: E402
from lva import vocab as VO  # noqa: E402

TERMS_OF_INTEREST = ["络合", "配体", "配位数", "晶场分裂", "螯合", "哈密顿量", "厄米",
                     "布里渊区", "糖异生", "泛素化", "EDTA", "Hammett", "GPCR",
                     "MAPK", "PI3K", "JAK-STAT", "Levi-Civita", "Minkowski",
                     "Favorskii", "Michaelis-Menten", "狄拉克", "拉格朗日量"]


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def main() -> None:
    t = VO.default()
    files = sorted(f for f in C.BENCH.glob("asr-*.json")
                   if f.name not in {"asr-correction-effect.json"})
    if not files:
        raise SystemExit("no asr-*.json found; run scripts/bench_asr.py first")

    report: dict[str, dict] = {}
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        eng = d["engine"]
        rows = {r["id"]: r for r in d["rows_sci"]}
        real = d["rows_real"]

        # --- scientific set, per renderer
        per_variant: dict[str, dict] = {}
        for variant in ("melotts", "sapi"):
            sel = [r for r in d["rows_sci"] if r["variant"] == variant]
            if not sel:
                continue
            before, after = [], []
            for r in sel:
                res = t.correct(r["text"])
                before.append(TX.cer(r["ref"], r["text"]))
                after.append(TX.cer(r["ref"], res.corrected))
            # A CER regression is not automatically a correction mistake.  When
            # the recogniser splits an unknown term into two dictionary words
            # (`Cannizzaro` -> `cannice zero`), rewriting the first fragment
            # recovers the term but leaves the second behind, and the leftover
            # costs more edits than the mangled form happened to.  Those are
            # counted separately: the term the brief cares about is now right.
            worsen_but_recovered = 0
            worsened = 0
            for r, a, b in zip(sel, after, before):
                if a <= b + 1e-9:
                    continue
                res = t.correct(r["text"])
                refs = [w.lower() for w in r.get("terms") or []]
                if refs and any(w in res.corrected.lower() for w in refs):
                    worsen_but_recovered += 1
                else:
                    worsened += 1
            per_variant[variant] = {
                "n": len(sel),
                "cer_raw": round(mean(before), 4),
                "cer_corrected": round(mean(after), 4),
                "improved": sum(1 for a, b in zip(after, before) if a < b - 1e-9),
                "worsened": worsened,
                "worsened_but_term_recovered": worsen_but_recovered,
            }

        # --- targeted term recovery on the reference sentences that contain them
        term_stats: dict[str, dict] = {}
        for term in TERMS_OF_INTEREST:
            raw_hit = cor_hit = total = 0
            for r in d["rows_sci"]:
                if term.lower() not in r["ref"].lower():
                    continue
                total += 1
                res = t.correct(r["text"])
                raw_hit += int(term.lower() in r["text"].lower())
                cor_hit += int(term.lower() in res.corrected.lower())
            if total:
                term_stats[term] = {"n": total, "raw": raw_hit, "corrected": cor_hit}

        # --- real speech must not be harmed
        real_before = [r["cer"] for r in real]
        real_after = []
        touched = 0
        for r in real:
            res = t.correct(r["text"])
            real_after.append(TX.cer(r["ref"], res.corrected))
            touched += int(bool(res.applied))
        real_stats = {
            "n": len(real),
            "cer_raw": round(mean(real_before), 4),
            "cer_corrected": round(mean(real_after), 4),
            "utterances_modified": touched,
        }

        report[eng] = {"sci_by_renderer": per_variant, "terms": term_stats,
                       "real": real_stats, "load_s": d["load_s"],
                       "rss_delta_mb": d["rss_mb"]["delta"],
                       "rtf_real": d["real"]["rtf_mean"],
                       "first_call_ms": d["first_call_ms"][0]}

    out = C.BENCH / "asr-correction-effect.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    for eng, r in report.items():
        print(f"\n=== {eng} (load {r['load_s']}s, rss+{r['rss_delta_mb']:.0f}MB, "
              f"RTF {r['rtf_real']:.4f}) ===")
        for v, s in r["sci_by_renderer"].items():
            extra = (f", {s['worsened_but_term_recovered']} CER-worse but term recovered"
                     if s.get("worsened_but_term_recovered") else "")
            print(f"  sci/{v:8s} CER {s['cer_raw']:.4f} -> {s['cer_corrected']:.4f} "
                  f"({s['improved']} improved, {s['worsened']} worsened of {s['n']}{extra})")
        rr = r["real"]
        print(f"  real        CER {rr['cer_raw']:.4f} -> {rr['cer_corrected']:.4f} "
              f"({rr['utterances_modified']}/{rr['n']} utterances modified)")
        hits = {k: v for k, v in r["terms"].items() if v["raw"] < v["n"]}
        if hits:
            print("  term recovery (raw -> corrected):")
            for k, v in sorted(hits.items(), key=lambda kv: kv[1]["raw"]):
                print(f"      {k:20s} {v['raw']}/{v['n']} -> {v['corrected']}/{v['n']}")
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
