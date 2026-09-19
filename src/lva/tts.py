"""Speech synthesis.

Primary engine: MeloTTS zh_en through sherpa-onnx (VITS, CPU, 44.1 kHz).
It is not the newest model available, but it loads in ~3 s, needs 0 MB of VRAM,
and streams in ~150-300 ms - which is what an always-on assistant actually
needs.  A torch/GPU voice (GPT-SoVITS class) would compete with the LLM for the
same 8 GB, so it is evaluated but not the default; see DEPLOYMENT_REPORT.md.

`SapiTTS` drives the built-in Windows synthesiser.  It is never used in the live
loop (latency is high and it is not streamable) but it is an offline, entirely
independent voice which makes it useful as a second synthesiser when generating
test audio.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sherpa_onnx as so

from . import audio as A
from . import config as C


# ------------------------------------------------------------------ chunking
_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*|(?<=[，,])\s*(?=.{12,})")


def split_sentences(text: str, min_chars: int = 8) -> list[str]:
    """Split streamed LLM text into TTS-sized pieces.

    Small pieces start speaking sooner; too small and the prosody breaks.  The
    first piece is allowed to be short so the assistant answers fast.
    """
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p and p.strip()]
    out: list[str] = []
    buf = ""
    for i, p in enumerate(parts):
        buf = f"{buf}{p}" if not buf else f"{buf} {p}"
        long_enough = len(buf) >= (min_chars if i else max(4, min_chars // 2))
        if long_enough or p.endswith(("。", "！", "？", "!", "?")):
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


class SentenceChunker:
    """Incremental splitter for token-by-token LLM output."""

    def __init__(self, min_chars: int = 8, on_sentence=None):
        self.min_chars = min_chars
        self.on_sentence = on_sentence
        self._buf = ""

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        out: list[str] = []
        # Only emit on a hard boundary; commas wait for more text.
        while True:
            m = re.search(r"[。！？!?；;\n]", self._buf)
            if not m:
                break
            idx = m.end()
            piece, self._buf = self._buf[:idx].strip(), self._buf[idx:]
            if piece:
                out.append(piece)
        if len(self._buf) >= 40:            # runaway clause: do not wait forever
            cut = self._buf.rfind("，")
            if cut > 0:
                piece, self._buf = self._buf[: cut + 1].strip(), self._buf[cut + 1:]
                if piece:
                    out.append(piece)
        for s in out:
            if self.on_sentence:
                self.on_sentence(s)
        return out

    def flush(self) -> list[str]:
        rest = self._buf.strip()
        self._buf = ""
        if rest:
            if self.on_sentence:
                self.on_sentence(rest)
            return [rest]
        return []


# ------------------------------------------------------------------- MeloTTS
@dataclass
class Synthesis:
    samples: np.ndarray
    sample_rate: int
    ttfa_ms: float
    gen_s: float

    @property
    def audio_s(self) -> float:
        return len(self.samples) / float(self.sample_rate)

    @property
    def rtf(self) -> float:
        return self.gen_s / self.audio_s if self.audio_s else 0.0


class MeloTTS:
    name = "melotts"

    def __init__(self, threads: int = C.TTS_THREADS, int8: bool = False, on_chunk=None):
        self.threads = threads
        self.on_chunk = on_chunk
        self._int8 = int8
        self.load_s = 0.0
        self.speed = 1.0

    def _build(self):
        d = C.MELOTTS_INT8_DIR if self._int8 else C.MELOTTS_DIR
        model = d / ("model.int8.onnx" if self._int8 else "model.onnx")
        cfg = so.OfflineTtsConfig()
        m = cfg.model
        m.vits.model = str(model)
        m.vits.lexicon = str(d / "lexicon.txt")
        m.vits.tokens = str(d / "tokens.txt")
        m.num_threads = self.threads
        m.provider = "cpu"
        cfg.max_num_sentences = 1          # stream sentences, not paragraphs
        fsts = [d / n for n in ("date.fst", "number.fst", "phone.fst", "new_heteronym.fst")]
        cfg.rule_fsts = ",".join(str(p) for p in fsts if p.exists())
        self._tts = so.OfflineTts(cfg)

    def load(self) -> "MeloTTS":
        t0 = time.perf_counter()
        self._build()
        self.load_s = time.perf_counter() - t0
        return self

    @property
    def sample_rate(self) -> int:
        return self._tts.sample_rate

    def synthesize(self, text: str) -> Synthesis:
        """Synthesise `text`, always via the streaming callback.

        Going through the callback even when the caller does not want chunks is
        what makes `ttfa_ms` an honest number: it is the time until the first
        audio actually exists, not the time to generate the whole utterance.
        """
        text = (text or "").strip()
        if not text:
            return Synthesis(np.zeros(0, dtype=np.float32), self.sample_rate, 0.0, 0.0)
        t0 = time.perf_counter()
        first = {"ms": None}
        chunks: list[np.ndarray] = []
        sink = self.on_chunk

        def cb(samples, progress):  # noqa: ANN001
            if first["ms"] is None:
                first["ms"] = (time.perf_counter() - t0) * 1000.0
            arr = np.array(samples, dtype=np.float32)
            chunks.append(arr)
            if sink is not None:
                return sink(arr, self.sample_rate)
            return 1

        self._tts.generate(text, 0, self.speed, cb)
        gen = time.perf_counter() - t0
        out = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        return Synthesis(out, self.sample_rate, first["ms"] or gen * 1000.0, gen)


# ------------------------------------------------------------- Windows SAPI
class SapiTTS:
    """Offline fallback / independent synthesiser via the Windows built-in voices.

    The desktop ships several voices and the default one is often en-US, which
    will happily "read" Chinese as gibberish.  The voice is therefore selected by
    culture rather than left to the default.  This machine has
    `Microsoft Huihui Desktop` (zh-CN).
    """

    name = "sapi"

    def __init__(self, voice: str | None = None, culture: str = "zh-CN"):
        self.voice = voice
        self.culture = culture
        if self.voice is None:
            self.voice = self._find_voice()
            if self.voice is None:
                raise RuntimeError(f"no SAPI voice for culture {culture}")

    def _find_voice(self) -> str | None:
        ps = (
            "Add-Type -AssemblyName System.Speech;"
            "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
            ".GetInstalledVoices()|ForEach-Object{$_.VoiceInfo.Culture.Name+'|'+$_.VoiceInfo.Name}"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, encoding="utf-8")
        voices: list[tuple[str, str]] = []
        for line in (r.stdout or "").splitlines():
            if "|" in line:
                cult, name = line.split("|", 1)
                voices.append((cult.strip(), name.strip()))
        want = self.culture.lower()
        for cult, name in voices:
            if cult.lower() == want:
                return name
        for cult, name in voices:
            if cult.lower().startswith(want.split("-")[0]):
                return name
        return None

    def synthesize(self, text: str) -> Synthesis:
        t0 = time.perf_counter()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sapi.wav"
            txt = Path(td) / "sapi.txt"
            # Windows PowerShell decodes redirected stdin with the OEM code page,
            # which silently turns UTF-8 Chinese into different characters.  Pass
            # the text through a UTF-8 file and read it back explicitly.
            txt.write_text(text, encoding="utf-8")
            ps = (
                "Add-Type -AssemblyName System.Speech;"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                f"$s.SelectVoice('{self.voice}');"
                f"$s.SetOutputToWaveFile('{out}');"
                f"$t = [IO.File]::ReadAllText('{txt}', [Text.Encoding]::UTF8);"
                "$s.Speak($t);$s.Dispose()"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                text=True, encoding="utf-8", capture_output=True, check=False,
            )
            if not out.exists():
                raise RuntimeError(f"SAPI produced no audio: {(r.stderr or '')[:200]}")
            samples, sr = A.read_wav(out)
        gen = time.perf_counter() - t0
        return Synthesis(samples, sr, gen * 1000.0, gen)


def load(engine: str = C.TTS_ENGINE, **kw) -> MeloTTS | SapiTTS:
    if engine == "melotts":
        return MeloTTS(**kw).load()
    if engine == "melotts_int8":
        return MeloTTS(int8=True, **kw).load()
    if engine == "sapi":
        return SapiTTS(**kw)
    raise KeyError(f"unknown TTS engine {engine!r}")
