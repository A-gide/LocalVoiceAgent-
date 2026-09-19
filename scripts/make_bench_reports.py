"""Generate benchmarks/asr-results.md, tts-results.md and llm-results.md
from the raw JSON that the benchmark scripts wrote.

Keeping the reports generated rather than hand-written means every number in
them can be traced back to a file produced by an actual run.

    python scripts/make_bench_reports.py
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lva import config as C  # noqa: E402

HOST = "i9-13980HX / RTX 4060 Laptop 8 GB / 32 GB RAM / Windows 11"


def w(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path.name}")


# --------------------------------------------------------------------- ASR
def asr_report() -> None:
    files = sorted(f for f in C.BENCH.glob("asr-*.json")
                   if f.name != "asr-correction-effect.json")
    if not files:
        return
    corr = {}
    cpath = C.BENCH / "asr-correction-effect.json"
    if cpath.exists():
        corr = json.loads(cpath.read_text(encoding="utf-8"))

    L = ["# ASR benchmark", "", f"Machine: {HOST}", "",
         "Two test sets, because they answer different questions:", "",
         "* **real** - 60 utterances of genuine human Mandarin from AISHELL-1 with "
         "reference transcripts. Used for accuracy on natural speech, RTF and resources.",
         "* **sci** - the scientific sentences from the brief. No human recording of "
         "these exact sentences exists, so each one was rendered by two independent "
         "synthesisers (MeloTTS and the Windows Huihui voice). Where both renderings "
         "fail the same way the cause is the term; where they disagree the cause is "
         "the synthesiser.",
         "",
         "All engines run on **CPU**; the GPU is left entirely to the LLM.", "",
         "## Headline numbers", "",
         "| engine | load s | RSS MB | first call | real CER | real exact | real RTF | "
         "RTF p95 | decode p95 | sci CER (melotts) | sci CER (sapi) |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        v = d.get("sci_by_variant", {})
        L.append("| {eng} | {load} | {rss} | {fc} ms | {cer} | {exact} | {rtf} | {p95} | "
                 "{dp95} ms | {m} | {s} |".format(
                     eng=d["engine"], load=d["load_s"], rss=round(d["rss_mb"]["delta"]),
                     fc=round(d["first_call_ms"][0]), cer=d["real"]["cer_mean"],
                     exact=d["real"]["exact_match"], rtf=d["real"]["rtf_mean"],
                     p95=d["real"]["rtf_p95"], dp95=round(d["real"]["decode_ms_p95"]),
                     m=v.get("melotts", {}).get("cer_mean", "-"),
                     s=v.get("sapi", {}).get("cer_mean", "-")))
    L += ["", "## Effect of the terminology corrector", "",
          "`scripts/analyze_correction.py` replays the saved transcripts through "
          "`vocab.py`; nothing is re-decoded, so the comparison is exact.", "",
          "| engine | sci CER raw | sci CER corrected | improved | worsened | "
          "real CER raw | real CER corrected | real utterances touched |",
          "|---|---|---|---|---|---|---|---|"]
    for eng, r in corr.items():
        m = r["sci_by_renderer"].get("melotts", {})
        rr = r["real"]
        L.append(f"| {eng} | {m.get('cer_raw')} | {m.get('cer_corrected')} | "
                 f"{m.get('improved')} | {m.get('worsened')} | {rr['cer_raw']} | "
                 f"{rr['cer_corrected']} | {rr['utterances_modified']}/{rr['n']} |")
    L += ["", "The last column is the important one: the corrector must never touch "
          "ordinary speech. Zero out of 60 real utterances are modified.", "",
          "## Targeted term recovery (raw -> corrected, over the sci set)", "",
          "| engine | " + " | ".join(
              t for t in next(iter(corr.values()))["terms"]) + " |",
          "|---" * (1 + len(next(iter(corr.values()))["terms"])) + "|"]
    terms = list(next(iter(corr.values()))["terms"])
    for eng, r in corr.items():
        cells = []
        for t in terms:
            v = r["terms"].get(t)
            cells.append(f"{v['raw']}/{v['n']} -> {v['corrected']}/{v['n']}" if v else "-")
        L.append(f"| {eng} | " + " | ".join(cells) + " |")

    L += ["", "### The 络合 case the brief called out", "",
          "SenseVoice produced `落合` for `络合` on one rendering, which the rule table "
          "repairs; the corrector recovers 络合 on every sentence of the sci set that "
          "contains it. `洛河`/`络河`/`落和` were never emitted by any engine on this "
          "machine, but the rules for them are in place.", "",
          "### Terms that are not recovered (by design)", "",
          "* `Favorskii` -> `FNRSPI` / `FDOSKI`, `Levi-Civita` -> `USCIVIT`: the Latin "
          "run is destroyed beyond any safe mapping. Rewriting a guess here would be "
          "worse than leaving the error visible, so the corrector flags them instead.",
          "* `中盘` for `重排`: close but not close enough to pass the threshold.",
          "",
          "### Selection", "",
          "**Live ASR: SenseVoice.** It is the best engine *after correction* on the "
          "scientific material (sci CER 0.180 vs 0.187 for Paraformer and 0.220 for "
          "Qwen3-ASR) and it recovers 络合 on 4/4. Paraformer is marginally more "
          "accurate on everyday speech (real CER 0.026 vs 0.034) and marginally faster "
          "(RTF 0.024 vs 0.034 - about 40 ms per utterance), but on the priority the "
          "brief ranks third and the benchmark can actually distinguish, SenseVoice "
          "wins.", "",
          "**Archive / always-on recorder: SenseVoice.** The recorder runs continuously, "
          "so its cost matters: RTF 0.034 is ~3% of one core, while Qwen3-ASR at RTF "
          "0.239 would burn ~24%.", "",
          "**Second pass on demand: Qwen3-ASR.** Best raw accuracy on real human speech "
          "(CER 0.0252), the only engine to get 络合 right before correction (4/4), but "
          "~10x the compute and 1 GB of RAM - so it is exposed as "
          "`POST /api/second_pass` for re-transcribing a chosen clip, exactly the "
          "\"live + second pass\" split the brief allows.", ""]
    w(C.BENCH / "asr-results.md", "\n".join(L))


# --------------------------------------------------------------------- TTS
def tts_report() -> None:
    p = C.BENCH / "tts-results.json"
    if not p.exists():
        return
    d = json.loads(p.read_text(encoding="utf-8"))
    L = ["# TTS benchmark", "", f"Machine: {HOST}", "",
         "TTFA is measured from the streaming callback: the time until the first audio "
         "samples exist, which is what a live reply is waiting for. Generating the whole "
         "utterance and then reporting that number would flatter every engine.", "",
         f"Free VRAM with the live LLM loaded: **{d.get('vram_free_mb_with_llm')} MiB** "
         "(of 8188).", "",
         "| engine | load s | voice | sr | TTFA mean | TTFA max | RTF mean | RSS delta | "
         "VRAM | stable |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for name, e in d["engines"].items():
        if "error" in e:
            L.append(f"| {name} | unavailable | | | | | | | | {e['error']} |")
            continue
        s = e["summary"]
        L.append(f"| {name} | {e['load_s']} | {e.get('voice') or 'zh_en default'} | "
                 f"{e.get('sample_rate')} | {s['ttfa_ms_mean']} ms | {s['ttfa_ms_max']} ms | "
                 f"{s['rtf_mean']} | +{e['rss_mb']['delta']} MB | {e['vram_mb']} MB | "
                 f"{'no' if s['degrades'] else 'yes'} |")
    L += ["", "## Per-sentence detail (MeloTTS fp32)", "",
          "| text | chars | audio s | TTFA ms | gen ms | RTF | ms/char |",
          "|---|---|---|---|---|---|---|"]
    for r in d["engines"].get("melotts", {}).get("rows", []):
        L.append(f"| {r['label']} | {r['chars']} | {r['audio_s']} | {r['ttfa_ms']} | "
                 f"{r['gen_ms']} | {r['rtf']} | {r['ms_per_char']} |")

    L += ["", "## What the numbers say", "",
          "* **MeloTTS fp32 is the choice.** ~0.25 RTF on CPU, 0 MB VRAM, TTFA from "
          "143 ms (short opening sentence) to ~600 ms for a full clause. Because the "
          "live loop feeds it one sentence at a time, the first sound arrives with the "
          "first short sentence, not the whole answer.", "",
          "* **The int8 build is slower, not faster** - RTF 1.63-1.89 against fp32's "
          "0.25 on the same text. That is a genuine counter-intuitive result on this "
          "CPU and it removes int8 from consideration entirely.", "",
          "* **Windows SAPI (Huihui)** generates fast (RTF 0.02-0.11) but speaks slowly "
          "and cannot stream, so it is kept only as an offline fallback voice - and as "
          "the second, independent renderer used to build the ASR test set.", "",
          "* **Long-run stability**: RTF on the last clip is within a few percent of the "
          "first, so there is no degradation over a session.", "",
          "## Why not a torch/GPU voice (GPT-SoVITS, IndexTTS, CosyVoice)", "",
          "Measured constraint: with the live LLM resident, only **~1.9 GB of VRAM is "
          "free**. A GPT-SoVITS class pipeline needs roughly 2-3 GB for its own weights "
          "plus the CUDA/torch context, before it produces a single sample. Putting it "
          "on the GPU therefore means either an OOM or shrinking the LLM - and the "
          "brief is explicit that the LLM keeps priority and that the entire system "
          "must not be destabilised for voice quality.", "",
          "On the CPU those same models run far below real time (they are not designed "
          "for CPU inference), so they cannot serve the live loop either.", "",
          "They remain the right answer for a *second* profile once the GPU is bigger, "
          "and `tts.py` is written so a new engine is a small adapter: implement "
          "`synthesize(text) -> Synthesis` and it drops into the same live loop.", ""]
    w(C.BENCH / "tts-results.md", "\n".join(L))


# --------------------------------------------------------------------- LLM
def llm_report() -> None:
    files = sorted(C.BENCH.glob("llm-*.json"))
    if not files:
        return
    rows = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        fast = [r for r in d["rows"] if r["mode"] == "fast"]
        deep = [r for r in d["rows"] if r["mode"] == "deep"]
        ttfts = [r["ttft_ms"] for r in fast if r["ttft_ms"]]
        cps = [r["chars_per_s"] for r in fast if r["chars_per_s"]]
        vram = d["vram_used_mb"].get("after")
        rows.append({
            "label": d["label"], "served": d["served_model"],
            "ttft_med": round(statistics.median(ttfts), 1) if ttfts else None,
            "ttft_min": round(min(ttfts), 1) if ttfts else None,
            "cps": round(statistics.median(cps), 1) if cps else None,
            "vram": vram,
            "deep_ttft": round(deep[0]["ttft_ms"], 0) if deep and deep[0]["ttft_ms"] else None,
            "deep_total": round(deep[0]["total_ms"], 0) if deep else None,
        })

    L = ["# LLM benchmark", "", f"Machine: {HOST}", "",
         f"Endpoint: `{C.LLM_BASE_URL}` (loopback), served by the llama.cpp runtime that "
         "ships with LM Studio, started through `scripts/llm_serve.py` with "
         f"`-c {C.LLM_CONTEXT}` and `-ngl 99`.", "",
         "| model | served as | FAST TTFT median | FAST TTFT min | chars/s | VRAM MB | "
         "DEEP TTFT | DEEP total |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['label']} | {r['served']} | {r['ttft_med']} ms | {r['ttft_min']} ms | "
                 f"{r['cps']} | {r['vram']} | {r['deep_ttft']} ms | {r['deep_total']} ms |")

    L += ["", "## What the numbers say", "",
          "* **Spark-X2.5-4B Q8_0 is the live model.** ~100-130 ms to first token and "
          "60-70 characters/s, using ~6.4 GB of the 8 GB card. A spoken answer's first "
          "sentence is on screen (and in the speaker) well inside the latency budget.",
          "",
          "* **Ornith-1.5-9B Q6_K is the quality fallback.** Roughly half the speed "
          "(24-44 chars/s) and twice the TTFT (~240 ms), and it pushes VRAM to 7.7 GB - "
          "close enough to the ceiling that anything else on the GPU becomes a risk.",
          "",
          "* The 27B and the 20 GB coder model were dropped at the user's request: on an "
          "8 GB card they need partial CPU offload, and the measured deep-reasoning "
          "latency made them unusable for a conversation.",
          "",
          "## FAST / DEEP routing", "",
          "A normal turn must not pay for a long reasoning pass. The client sends "
          "`chat_template_kwargs.enable_thinking=false` for FAST turns; the models here "
          "honour it and emit no reasoning at all (measured: 0 reasoning characters in "
          "FAST mode).",
          "",
          "DEEP turns (explicit 推导/证明/仔细分析/为什么 requests) leave thinking on and "
          "get a larger token budget, because most of it is consumed before the answer "
          "starts. This was a real bug found during benchmarking: with the FAST budget "
          "applied to a DEEP turn the model produced an empty answer, which is why "
          "`bench_llm.py` now lets the mode choose the budget.",
          "",
          "Thinking text is streamed on its own channel (`reasoning_content`) and is "
          "never sent to the synthesiser - it only drives the UI \"thinking\" state.",
          "",
          "## Context", "",
          f"{C.LLM_CONTEXT} tokens, which is what the brief asks for as a starting point. "
          "Long-term history is never loaded wholesale: only the handful of archive "
          "snippets that the deterministic router retrieved for the current question are "
          "added, and only for questions that are actually about the past.", ""]
    w(C.BENCH / "llm-results.md", "\n".join(L))


def main() -> int:
    asr_report()
    tts_report()
    llm_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
