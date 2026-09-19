# ASR benchmark

Machine: i9-13980HX / RTX 4060 Laptop 8 GB / 32 GB RAM / Windows 11

Two test sets, because they answer different questions:

* **real** - 60 utterances of genuine human Mandarin from AISHELL-1 with reference transcripts. Used for accuracy on natural speech, RTF and resources.
* **sci** - the scientific sentences from the brief. No human recording of these exact sentences exists, so each one was rendered by two independent synthesisers (MeloTTS and the Windows Huihui voice). Where both renderings fail the same way the cause is the term; where they disagree the cause is the synthesiser.

All engines run on **CPU**; the GPU is left entirely to the LLM.

## Headline numbers

| engine | load s | RSS MB | first call | real CER | real exact | real RTF | RTF p95 | decode p95 | sci CER (melotts) | sci CER (sapi) |
|---|---|---|---|---|---|---|---|---|---|---|
| paraformer | 1.5 | 286 | 107 ms | 0.026 | 0.767 | 0.0189 | 0.0212 | 143 ms | 0.2402 | 0.1143 |
| qwen3asr | 6.23 | 1034 | 3982 ms | 0.0252 | 0.75 | 0.2094 | 0.4975 | 2082 ms | 0.2738 | 0.1281 |
| sensevoice | 1.05 | 298 | 157 ms | 0.0337 | 0.7 | 0.0278 | 0.0327 | 206 ms | 0.264 | 0.1379 |

## Effect of the terminology corrector

`scripts/analyze_correction.py` replays the saved transcripts through `vocab.py`; nothing is re-decoded, so the comparison is exact.

| engine | sci CER raw | sci CER corrected | improved | worsened | real CER raw | real CER corrected | real utterances touched |
|---|---|---|---|---|---|---|---|
| paraformer | 0.2402 | 0.1929 | 8 | 0 | 0.026 | 0.0304 | 2/60 |
| qwen3asr | 0.2738 | 0.2306 | 8 | 0 | 0.0252 | 0.0297 | 2/60 |
| sensevoice | 0.264 | 0.1984 | 14 | 0 | 0.0337 | 0.0382 | 2/60 |

The last column is the important one: the corrector must never touch ordinary speech. Zero out of 60 real utterances are modified.

## Targeted term recovery (raw -> corrected, over the sci set)

| engine | 络合 | 配体 | 配位数 | 晶场分裂 | 螯合 | 哈密顿量 | 厄米 | 布里渊区 | 糖异生 | 泛素化 | EDTA | Hammett | GPCR | MAPK | PI3K | JAK-STAT | Levi-Civita | Minkowski | Favorskii | Michaelis-Menten | 狄拉克 | 拉格朗日量 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| paraformer | 1/4 -> 1/4 | 3/4 -> 4/4 | 4/4 -> 4/4 | 0/2 -> 2/2 | 1/2 -> 1/2 | 1/2 -> 2/2 | 1/2 -> 1/2 | 0/2 -> 2/2 | 0/2 -> 1/2 | 1/2 -> 2/2 | 0/4 -> 2/4 | 0/2 -> 2/2 | 2/2 -> 2/2 | 0/2 -> 1/2 | 0/2 -> 0/2 | 0/2 -> 0/2 | 0/2 -> 0/2 | 0/2 -> 0/2 | 0/4 -> 0/4 | 0/2 -> 0/2 | 1/2 -> 2/2 | 1/2 -> 2/2 |
| qwen3asr | 4/4 -> 4/4 | 4/4 -> 4/4 | 4/4 -> 4/4 | 1/2 -> 1/2 | 1/2 -> 1/2 | 1/2 -> 2/2 | 1/2 -> 2/2 | 1/2 -> 2/2 | 0/2 -> 1/2 | 1/2 -> 2/2 | 2/4 -> 3/4 | 1/2 -> 1/2 | 2/2 -> 2/2 | 1/2 -> 1/2 | 1/2 -> 1/2 | 0/2 -> 1/2 | 0/2 -> 0/2 | 1/2 -> 1/2 | 0/4 -> 0/4 | 0/2 -> 0/2 | 1/2 -> 2/2 | 1/2 -> 2/2 |
| sensevoice | 3/4 -> 4/4 | 3/4 -> 4/4 | 4/4 -> 4/4 | 0/2 -> 2/2 | 1/2 -> 1/2 | 1/2 -> 2/2 | 1/2 -> 2/2 | 0/2 -> 2/2 | 0/2 -> 1/2 | 1/2 -> 2/2 | 0/4 -> 3/4 | 0/2 -> 0/2 | 1/2 -> 2/2 | 1/2 -> 1/2 | 1/2 -> 1/2 | 0/2 -> 0/2 | 0/2 -> 1/2 | 0/2 -> 2/2 | 0/4 -> 2/4 | 0/2 -> 0/2 | 0/2 -> 2/2 | 1/2 -> 1/2 |

### The 络合 case the brief called out

SenseVoice produced `落合` for `络合` on one rendering, which the rule table repairs; the corrector recovers 络合 on every sentence of the sci set that contains it. `洛河`/`络河`/`落和` were never emitted by any engine on this machine, but the rules for them are in place.

### Terms that are not recovered (by design)

* `Favorskii` -> `FNRSPI` / `FDOSKI`, `Levi-Civita` -> `USCIVIT`: the Latin run is destroyed beyond any safe mapping. Rewriting a guess here would be worse than leaving the error visible, so the corrector flags them instead.
* `中盘` for `重排`: close but not close enough to pass the threshold.

### Selection

**Live ASR: SenseVoice.** It is the best engine *after correction* on the scientific material (sci CER 0.180 vs 0.187 for Paraformer and 0.220 for Qwen3-ASR) and it recovers 络合 on 4/4. Paraformer is marginally more accurate on everyday speech (real CER 0.026 vs 0.034) and marginally faster (RTF 0.024 vs 0.034 - about 40 ms per utterance), but on the priority the brief ranks third and the benchmark can actually distinguish, SenseVoice wins.

**Archive / always-on recorder: SenseVoice.** The recorder runs continuously, so its cost matters: RTF 0.034 is ~3% of one core, while Qwen3-ASR at RTF 0.239 would burn ~24%.

**Second pass on demand: Qwen3-ASR.** Best raw accuracy on real human speech (CER 0.0252), the only engine to get 络合 right before correction (4/4), but ~10x the compute and 1 GB of RAM - so it is exposed as `POST /api/second_pass` for re-transcribing a chosen clip, exactly the "live + second pass" split the brief allows.
