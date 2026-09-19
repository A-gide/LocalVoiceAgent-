"""TTS benchmark.

    python scripts/bench_tts.py --engine melotts [--engine sapi]

Records the numbers the live loop depends on: time to first audio (TTFA, taken
from the streaming callback, not from the end of generation), real-time factor,
per-character cost, resource use and long-run stability.  Also measures the VRAM
headroom a GPU synthesiser would have to fit into, which is what decides whether
a GPT-SoVITS class voice is even possible on this machine.
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

from lva import audio as A  # noqa: E402
from lva import config as C  # noqa: E402
from lva import textutil as TX  # noqa: E402
from lva import tts as TTS  # noqa: E402

TEXTS: list[tuple[str, str]] = [
    ("greeting", "你好，我现在正在测试本地语音助手。"),
    ("chem", "铜离子与EDTA形成稳定的络合物。"),
    ("jahn_teller", "这里需要考虑Jahn-Teller效应。"),
    ("mixed", "Favorskii rearrangement是一种重要的有机重排反应。"),
    ("phys", "哈密顿量必须是厄米算符，拉格朗日量对时间的积分给出作用量。"),
    ("bio", "泛素化与磷酸化是两种常见的翻译后修饰，GPCR通过G蛋白传递信号。"),
    ("long", "配位数是指配合物中与中心离子直接成键的配体原子数目。"
             "在八面体配合物中，六个配体沿着坐标轴方向接近中心离子，"
             "d轨道在配体场的作用下发生分裂，形成能量较低的t2g轨道和能量较高的eg轨道。"),
    ("punct", "结果有三点：第一，反应速率提高；第二，选择性改善；第三，副产物减少。"),
]


def vram() -> float | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10)
        used, total = [int(x) for x in out.stdout.strip().split(",")]
        return float(total - used)
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", action="append", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    engines = a.engine or ["melotts"]

    report: dict = {"engines": {}, "notes": []}
    report["vram_free_mb_with_llm"] = vram()
    report["notes"].append(
        "TTFA comes from the streaming callback: it is the time until the first "
        "audio samples exist, which is what a live reply waits for.")

    for name in engines:
        try:
            t0 = time.perf_counter()
            eng = TTS.load(name)
            load_s = time.perf_counter() - t0
        except Exception as e:  # noqa: BLE001
            report["engines"][name] = {"error": f"{type(e).__name__}: {e}"}
            print(f"[{name}] UNAVAILABLE: {e}")
            continue

        import psutil
        proc = psutil.Process()
        rss0 = proc.memory_info().rss / 1024 / 1024
        rows = []
        outdir = C.BENCH / "tts"
        outdir.mkdir(parents=True, exist_ok=True)
        for label, text in TEXTS:
            spoken = TX.strip_for_speech(text)
            samples = []
            ttfa = {"ms": None}
            tt0 = time.perf_counter()

            def on_chunk(chunk, sr):  # noqa: ANN001
                if ttfa["ms"] is None:
                    ttfa["ms"] = (time.perf_counter() - tt0) * 1000
                samples.append(chunk)
                return 1

            if isinstance(eng, TTS.MeloTTS):
                eng.on_chunk = on_chunk
            t_gen = time.perf_counter()
            syn = eng.synthesize(spoken)
            gen = time.perf_counter() - t_gen
            if isinstance(eng, TTS.MeloTTS):
                eng.on_chunk = None
            wav = outdir / f"{name}_{label}.wav"
            A.write_wav(wav, syn.samples, syn.sample_rate)
            audio_s = syn.audio_s
            rows.append({
                "label": label, "chars": len(spoken), "audio_s": round(audio_s, 3),
                "ttfa_ms": round(ttfa["ms"] or syn.ttfa_ms, 1),
                "gen_ms": round(gen * 1000, 1),
                "rtf": round(gen / audio_s, 4) if audio_s else None,
                "ms_per_char": round(gen * 1000 / max(1, len(spoken)), 2),
                "wav": str(wav.relative_to(C.ROOT)),
            })
            print(f"  [{name}] {label:12s} {len(spoken):3d} chars -> {audio_s:5.2f}s  "
                  f"ttfa {rows[-1]['ttfa_ms']:6.1f}ms  gen {gen*1000:6.0f}ms  "
                  f"rtf {rows[-1]['rtf']:.3f}")

        # sustained-load check: does it stay stable, or degrade / leak?
        loop = [r for r in rows if r["rtf"]] or rows
        first = loop[0]["rtf"]
        last = loop[-1]["rtf"]
        rss1 = proc.memory_info().rss / 1024 / 1024
        report["engines"][name] = {
            "load_s": round(load_s, 2),
            "sample_rate": getattr(eng, "sample_rate", None),
            "voice": getattr(eng, "voice", None),
            "rss_mb": {"before": round(rss0, 1), "after": round(rss1, 1),
                       "delta": round(rss1 - rss0, 1)},
            "vram_mb": 0,
            "rows": rows,
            "summary": {
                "ttfa_ms_mean": round(statistics.fmean([r["ttfa_ms"] for r in rows]), 1),
                "ttfa_ms_max": max(r["ttfa_ms"] for r in rows),
                "rtf_mean": round(statistics.fmean([r["rtf"] for r in loop if r["rtf"]]), 4),
                "first_rtf": first, "last_rtf": last,
                "degrades": bool(first and last and last > first * 1.3),
            },
        }

    out = Path(a.out) if a.out else C.BENCH / "tts-results.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if report["vram_free_mb_with_llm"] is not None:
        print(f"\nfree VRAM with the LLM loaded: {report['vram_free_mb_with_llm']:.0f} MiB")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
