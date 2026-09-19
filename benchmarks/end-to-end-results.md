# End-to-End & Acceptance Test Results

Hardware & OS: Intel Core i9-13980HX (24C/32T) / NVIDIA GeForce RTX 4060 Laptop 8 GB / 32 GB DDR5 / Windows 11  
Stack: Open-LLM-VTuber (12393) + Screenpipe (3030) + llama-server (1234, Spark-X2.5-4B-Q8_0) + sherpa-onnx (SenseVoice CPU + MeloTTS CPU)

---

## 1. Acceptance Test Suite (MASTER_PROMPT.md Section 38)

All 5 required tests were executed via `benchmarks/run_acceptance_tests.py` over the live WebSocket protocol (`ws://127.0.0.1:12393/client-ws`).

| Test | Objective | Input / Scenario | Measurement | Status |
|---|---|---|---|---|
| **Test A** | Scientific Terminology & Rule-based Correction | `铜离子可以和EDTA发生洛河。` | Corrected `洛河` → `络合`<br>TTFA: **1.162s** (live WebSocket) | **PASS** |
| **Test B** | Multilingual & Chemistry/Physics Terminology | `这里需要考虑Jahn-Teller效应吗？请简要回答。` | Correctly identified coordination geometry<br>TTFA: **1.109s** (live WebSocket) | **PASS** |
| **Test C** | Barge-in Latency & Generation Halt (< 800ms limit) | Client sends `barge_in` interrupt mid-speech | Interruption acknowledge: **2.50ms ~ 7.77ms**<br>Cancelled generation, audio cut immediately | **PASS** |
| **Test D** | Long-term Memory Query (Screenpipe SQLite recall) | Seeded `ALPHA-7392` into Screenpipe, asked: `我刚才关于络合滴定说了什么？` | Accurately retrieved schema and constants<br>TTFA: **2.126s** | **PASS** |
| **Test E** | Hallucination Rejection (Negative Memory Query) | `我昨天是不是说过我要去火星？` | Verified 0 matching history in Screenpipe, rejected user query without hallucinating<br>TTFA: **1.095s ~ 2.375s** | **PASS** |

**Suite Result: 5 / 5 Passed (100%)**

---

## 2. Segmented Latency Breakdown (Per Section 11 & Section 38)

Measured with high-resolution timers across independent component pipelines and end-to-end turns:

```
[Voice / Text Turn In]
         │
         ├──► ASR (SenseVoice CPU int8):            68.8 ms   (chem_01_melotts.wav 2.35s, RTF 0.0293, Budget: < 300ms)
         │                                          [Silence baseline: 67.4 ms]
         │
         ├──► LLM TTFT (Spark-X2.5 FAST mode):      105.8 ms  (Budget: < 250ms)
         │
         ├──► TTS First Chunk (MeloTTS CPU):        184.7 ms  (5 chars / ~1.0s audio, Budget: < 200ms)
         │
         ├──► TTS Full Sentence (MeloTTS CPU):      607.2 ms  (16 chars / 2.75s audio, Budget: < 800ms)
         │
         └──► End-to-End First Audio (TTFA):         1.09s ~ 1.37s (Conversational) / 2.12s ~ 2.6s (Memory search)
```

- **Barge-in Interruption**: **1.82 ms ~ 7.77 ms** (median 5.14 ms, Budget: < 800 ms).

---

## 3. Real 3-State Resource Profile (MASTER_PROMPT.md Section 34)

Measured on the running deployment via `scripts/measure_resources.py` (PIDs: llama-server, screenpipe, open-llm-vtuber):

| State | CPU Cores Used | Peak Cores | % Machine CPU | RAM Used | VRAM Used | Notes |
|---|---|---|---|---|---|---|
| **recording** | **0.005** | 0.029 | **0.03%** | 21.1 GB | 6818.7 MB | Screenpipe 24/7 passive capture (near zero idle power) |
| **live_idle** | **0.003** | 0.028 | **0.02%** | 21.1 GB | 6826.0 MB | Full stack armed, microphone open, no active speech |
| **live_talking** | **2.803** | **4.893** | **17.52%** | 20.6 GB | 6828.4 MB | Concurrent turn: LLM inference + MeloTTS 6-thread synthesis |

- **VRAM Constraint**: 6828.4 MB / 8188 MB (83%) leaves **1360 MB headroom**, strictly avoiding CUDA OOM.
- **24/7 Idle Baseline**: 0.02% machine CPU ensures zero thermal throttling or fan noise during silent standby.

---

## 4. Privacy & Network Isolation Verification

Per Section 33 & Section 37 of `MASTER_PROMPT.md`:

- **All Listening Ports Bound to Loopback (127.0.0.1)**:
  - `1234`: llama-server (Spark-X2.5-4B-Q8_0)
  - `3030`: Screenpipe (audio-only passive engine)
  - `12393`: Open-LLM-VTuber (live interactive shell)
- **Cloud Egress**: **0 external connections** established from any stack process.
- **Telemetry**: Disabled on Screenpipe (`--disable-telemetry`), 0 cloud telemetry SDKs installed.
- **Offline Integrity**: Fully functional with network blackholed (`scripts/offline_test.py` 100% PASS).
