"""Empirical API probe: construct every candidate engine once and run a real clip.

This exists so the constructors are discovered from the installed sherpa-onnx
build instead of being assumed.  Run:  python scripts/probe_engines.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lva import config as C  # noqa: E402

import numpy as np  # noqa: E402
import sherpa_onnx as so  # noqa: E402


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    import wave

    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError(f"only 16-bit wav supported, got {sw*8}")
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a, sr


def resample(a: np.ndarray, sr: int, target: int) -> np.ndarray:
    if sr == target:
        return a
    n = int(round(len(a) * target / sr))
    x_old = np.linspace(0.0, 1.0, len(a), endpoint=False)
    x_new = np.linspace(0.0, 1.0, n, endpoint=False)
    return np.interp(x_new, x_old, a).astype(np.float32)


def build(engine: str):
    t0 = time.perf_counter()
    if engine == "sensevoice":
        r = so.OfflineRecognizer.from_sense_voice(
            model=str(C.SENSEVOICE_DIR / "model.int8.onnx"),
            tokens=str(C.SENSEVOICE_DIR / "tokens.txt"),
            num_threads=C.ASR_THREADS,
            use_itn=True,
            language="zh",
            provider="cpu",
        )
    elif engine == "paraformer":
        r = so.OfflineRecognizer.from_paraformer(
            paraformer=str(C.PARAFORMER_DIR / "model.int8.onnx"),
            tokens=str(C.PARAFORMER_DIR / "tokens.txt"),
            num_threads=C.ASR_THREADS,
            provider="cpu",
        )
    elif engine == "qwen3asr":
        r = so.OfflineRecognizer.from_qwen3_asr(
            conv_frontend=str(C.QWEN3ASR_DIR / "conv_frontend.onnx"),
            encoder=str(C.QWEN3ASR_DIR / "encoder.int8.onnx"),
            decoder=str(C.QWEN3ASR_DIR / "decoder.int8.onnx"),
            tokenizer=str(C.QWEN3ASR_DIR / "tokenizer"),
            num_threads=C.ASR_THREADS,
            provider="cpu",
        )
    else:
        raise SystemExit(f"unknown engine {engine}")
    return r, time.perf_counter() - t0


def build_tts():
    t0 = time.perf_counter()
    tts_cfg = so.OfflineTtsConfig()
    m = tts_cfg.model
    m.vits.model = str(C.MELOTTS_DIR / "model.onnx")
    m.vits.lexicon = str(C.MELOTTS_DIR / "lexicon.txt")
    m.vits.tokens = str(C.MELOTTS_DIR / "tokens.txt")
    m.num_threads = C.TTS_THREADS
    m.provider = "cpu"
    tts_cfg.max_num_sentences = 1
    fsts = [C.MELOTTS_DIR / n for n in ("date.fst", "number.fst", "phone.fst")]
    tts_cfg.rule_fsts = ",".join(str(p) for p in fsts if p.exists())
    return so.OfflineTts(tts_cfg), time.perf_counter() - t0


def main() -> None:
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else C.BENCH / "_work" / "real_zh.wav"
    audio, sr = read_wav(wav)
    audio16 = resample(audio, sr, C.ASR_RATE)
    print(f"clip: {wav.name}  {len(audio)/sr:.2f}s @{sr} -> {len(audio16)/C.ASR_RATE:.2f}s @16k")

    for eng in ("sensevoice", "paraformer", "qwen3asr"):
        try:
            rec, load_s = build(eng)
        except Exception as e:  # noqa: BLE001
            print(f"[{eng}] BUILD FAILED: {type(e).__name__}: {e}")
            continue
        s = rec.create_stream()
        s.accept_waveform(C.ASR_RATE, audio16)
        t0 = time.perf_counter()
        rec.decode_stream(s)
        dt = time.perf_counter() - t0
        print(f"[{eng}] load={load_s:.2f}s decode={dt*1000:.0f}ms "
              f"rtf={dt/(len(audio16)/C.ASR_RATE):.4f} text={s.result.text!r}")

    try:
        tts, load_s = build_tts()
        print(f"[melotts] load={load_s:.2f}s sr={tts.sample_rate} speakers={tts.num_speakers}")
        chunks: list[tuple[float, int]] = []
        t_start = time.perf_counter()

        def cb(samples, n, progress):  # noqa: ANN001
            chunks.append((time.perf_counter() - t_start, n))
            return 1

        t0 = time.perf_counter()
        audio_out = tts.generate("你好，我现在正在测试本地语音助手。", sid=0, speed=1.0,
                                 callback=cb)
        dt = time.perf_counter() - t0
        first = chunks[0][0] * 1000 if chunks else float("nan")
        total = len(audio_out.samples) / tts.sample_rate
        print(f"[melotts] ttfa={first:.0f}ms chunks={len(chunks)} audio={total:.2f}s "
              f"gen={dt:.2f}s rtf={dt/total:.3f}")
    except Exception as e:  # noqa: BLE001
        import traceback

        print(f"[melotts] FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
