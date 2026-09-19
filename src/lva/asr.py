"""ASR engines.

All engines run on CPU on purpose: the 8 GB of VRAM is reserved for the LLM.
Every engine exposes the same two-line interface:

    rec = load("sensevoice")
    text, info = rec.transcribe(samples_16k_mono_float32)

`hotwords` is applied only for engines that actually implement contextual
biasing in this sherpa-onnx build; for the others the call is a no-op and we
rely on the terminology corrector in vocab.py instead of pretending it worked.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import sherpa_onnx as so

from . import config as C
from . import textutil


@dataclass
class Transcript:
    text: str
    engine: str
    decode_ms: float
    audio_s: float
    rtf: float
    extra: dict = field(default_factory=dict)


class BaseEngine:
    name = "base"
    supports_hotwords = False

    def __init__(self, threads: int = C.ASR_THREADS):
        self.threads = threads
        self._rec = None
        self.load_s = 0.0

    def _build(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def load(self) -> "BaseEngine":
        t0 = time.perf_counter()
        self._build()
        self.load_s = time.perf_counter() - t0
        return self

    def transcribe(self, samples: np.ndarray, hotwords: list[str] | None = None) -> Transcript:
        audio_s = len(samples) / C.ASR_RATE
        stream = self._rec.create_stream(hotwords=hotwords or None) if self.supports_hotwords \
            else self._rec.create_stream()
        stream.accept_waveform(C.ASR_RATE, samples)
        t0 = time.perf_counter()
        self._rec.decode_stream(stream)
        dt = (time.perf_counter() - t0) * 1000.0
        return Transcript(text=stream.result.text, engine=self.name, decode_ms=dt,
                          audio_s=audio_s, rtf=(dt / 1000.0) / audio_s if audio_s else 0.0)


class SenseVoice(BaseEngine):
    name = "sensevoice"
    supports_hotwords = False

    def _build(self):
        self._rec = so.OfflineRecognizer.from_sense_voice(
            model=str(C.SENSEVOICE_DIR / "model.int8.onnx"),
            tokens=str(C.SENSEVOICE_DIR / "tokens.txt"),
            num_threads=self.threads,
            use_itn=True,
            language="zh",
            provider="cpu",
        )


class Paraformer(BaseEngine):
    name = "paraformer"
    supports_hotwords = False

    def _build(self):
        self._rec = so.OfflineRecognizer.from_paraformer(
            paraformer=str(C.PARAFORMER_DIR / "model.int8.onnx"),
            tokens=str(C.PARAFORMER_DIR / "tokens.txt"),
            num_threads=self.threads,
            provider="cpu",
        )


class Qwen3ASR(BaseEngine):
    name = "qwen3asr"
    supports_hotwords = True

    def _build(self):
        self._rec = so.OfflineRecognizer.from_qwen3_asr(
            conv_frontend=str(C.QWEN3ASR_DIR / "conv_frontend.onnx"),
            encoder=str(C.QWEN3ASR_DIR / "encoder.int8.onnx"),
            decoder=str(C.QWEN3ASR_DIR / "decoder.int8.onnx"),
            tokenizer=str(C.QWEN3ASR_DIR / "tokenizer"),
            num_threads=self.threads,
            provider="cpu",
        )


REGISTRY: dict[str, Callable[[], BaseEngine]] = {
    "sensevoice": SenseVoice,
    "paraformer": Paraformer,
    "qwen3asr": Qwen3ASR,
}


def load(engine: str, threads: int = C.ASR_THREADS) -> BaseEngine:
    if engine not in REGISTRY:
        raise KeyError(f"unknown ASR engine {engine!r}; have {sorted(REGISTRY)}")
    return REGISTRY[engine]().load()


def clean(text: str) -> str:
    """Strip SenseVoice-style tags; keep the wording otherwise untouched."""
    return textutil.strip_tags(text).strip()
