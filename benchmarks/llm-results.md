# LLM benchmark

Machine: i9-13980HX / RTX 4060 Laptop 8 GB / 32 GB RAM / Windows 11

Endpoint: `http://127.0.0.1:1234/v1` (loopback), served by the llama.cpp runtime that ships with LM Studio, started through `scripts/llm_serve.py` with `-c 8192` and `-ngl 99`.

| model | served as | FAST TTFT median | FAST TTFT min | chars/s | VRAM MB | DEEP TTFT | DEEP total |
|---|---|---|---|---|---|---|---|
| ornith-1.5-9b-q6-k-2 | local-live-llm | 249.2 ms | 237.5 ms | 25.8 | 7704.0 | 44132.0 ms | 66782.0 ms |
| spark-x2.5-4b-q8-0 | local-live-llm | 122.3 ms | 105.9 ms | 59.8 | 6388.0 | 28120.0 ms | 42844.0 ms |

## What the numbers say

* **Spark-X2.5-4B Q8_0 is the live model.** ~100-130 ms to first token and 60-70 characters/s, using ~6.4 GB of the 8 GB card. A spoken answer's first sentence is on screen (and in the speaker) well inside the latency budget.

* **Ornith-1.5-9B Q6_K is the quality fallback.** Roughly half the speed (24-44 chars/s) and twice the TTFT (~240 ms), and it pushes VRAM to 7.7 GB - close enough to the ceiling that anything else on the GPU becomes a risk.

* The 27B and the 20 GB coder model were dropped at the user's request: on an 8 GB card they need partial CPU offload, and the measured deep-reasoning latency made them unusable for a conversation.

## FAST / DEEP routing

A normal turn must not pay for a long reasoning pass. The client sends `chat_template_kwargs.enable_thinking=false` for FAST turns; the models here honour it and emit no reasoning at all (measured: 0 reasoning characters in FAST mode).

DEEP turns (explicit 推导/证明/仔细分析/为什么 requests) leave thinking on and get a larger token budget, because most of it is consumed before the answer starts. This was a real bug found during benchmarking: with the FAST budget applied to a DEEP turn the model produced an empty answer, which is why `bench_llm.py` now lets the mode choose the budget.

Thinking text is streamed on its own channel (`reasoning_content`) and is never sent to the synthesiser - it only drives the UI "thinking" state.

## Context

8192 tokens, which is what the brief asks for as a starting point. Long-term history is never loaded wholesale: only the handful of archive snippets that the deterministic router retrieved for the current question are added, and only for questions that are actually about the past.
