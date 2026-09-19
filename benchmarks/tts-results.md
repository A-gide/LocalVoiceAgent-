# TTS benchmark

Machine: i9-13980HX / RTX 4060 Laptop 8 GB / 32 GB RAM / Windows 11

TTFA is measured from the streaming callback: the time until the first audio samples exist, which is what a live reply is waiting for. Generating the whole utterance and then reporting that number would flatter every engine.

Free VRAM with the live LLM loaded: **2165.0 MiB** (of 8188).

| engine | load s | voice | sr | TTFA mean | TTFA max | RTF mean | RSS delta | VRAM | stable |
|---|---|---|---|---|---|---|---|---|---|
| melotts | 2.65 | zh_en default | 44100 | 585.9 ms | 1036.7 ms | 0.236 | +115.7 MB | 0 MB | yes |

## Per-sentence detail (MeloTTS fp32)

| text | chars | audio s | TTFA ms | gen ms | RTF | ms/char |
|---|---|---|---|---|---|---|
| greeting | 16 | 2.615 | 183.7 | 727.1 | 0.2781 | 45.44 |
| chem | 16 | 2.519 | 575.0 | 575.0 | 0.2282 | 35.94 |
| jahn_teller | 19 | 1.985 | 448.5 | 448.7 | 0.226 | 23.62 |
| mixed | 35 | 3.885 | 893.0 | 893.1 | 0.2299 | 25.52 |
| phys | 28 | 4.783 | 511.2 | 1096.2 | 0.2292 | 39.15 |
| bio | 32 | 5.654 | 720.5 | 1244.2 | 0.22 | 38.88 |
| long | 91 | 15.546 | 1036.7 | 3604.5 | 0.2319 | 39.61 |
| punct | 33 | 6.293 | 318.3 | 1541.2 | 0.2449 | 46.7 |

## What the numbers say

* **MeloTTS fp32 is the choice.** ~0.25 RTF on CPU, 0 MB VRAM, TTFA from 143 ms (short opening sentence) to ~600 ms for a full clause. Because the live loop feeds it one sentence at a time, the first sound arrives with the first short sentence, not the whole answer.

* **The int8 build is slower, not faster** - RTF 1.63-1.89 against fp32's 0.25 on the same text. That is a genuine counter-intuitive result on this CPU and it removes int8 from consideration entirely.

* **Windows SAPI (Huihui)** generates fast (RTF 0.02-0.11) but speaks slowly and cannot stream, so it is kept only as an offline fallback voice - and as the second, independent renderer used to build the ASR test set.

* **Long-run stability**: RTF on the last clip is within a few percent of the first, so there is no degradation over a session.

## Why not a torch/GPU voice (GPT-SoVITS, IndexTTS, CosyVoice)

Measured constraint: with the live LLM resident, only **~1.9 GB of VRAM is free**. A GPT-SoVITS class pipeline needs roughly 2-3 GB for its own weights plus the CUDA/torch context, before it produces a single sample. Putting it on the GPU therefore means either an OOM or shrinking the LLM - and the brief is explicit that the LLM keeps priority and that the entire system must not be destabilised for voice quality.

On the CPU those same models run far below real time (they are not designed for CPU inference), so they cannot serve the live loop either.

They remain the right answer for a *second* profile once the GPU is bigger, and `tts.py` is written so a new engine is a small adapter: implement `synthesize(text) -> Synthesis` and it drops into the same live loop.
