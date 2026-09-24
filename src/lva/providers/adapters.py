"""Thin adapters over the existing concrete clients (v1.2.1 PR-011).

The frozen step is "wrap the existing ASR/TTS/OpenAI clients in thin adapters".
These classes implement the three protocols from :mod:`lva.providers.base` by
**delegating** to the clients that already exist -- they do not reimplement
decoding, synthesis or HTTP.  The concrete clients stay in place, which is what
the rollback note requires ("concrete implementation is not deleted; the old
factory is removed after PR-037").

Sync-to-async note: the underlying clients are blocking.  The adapters keep the
protocol's async shape by running the blocking call in a worker thread, so a
caller cannot accidentally block the event loop.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Callable

import numpy as np

from ..contracts.ids import TurnId


class ASREngineAdapter:
    """Adapt an ``lva.asr`` engine (SenseVoice/Paraformer/...) to ``ASRProvider``."""

    def __init__(self, engine: object, engine_name: str | None = None) -> None:
        self._engine = engine
        self._name = engine_name or getattr(engine, "name", "asr-adapter")

    @property
    def name(self) -> str:
        return str(self._name)

    async def transcribe(
        self,
        audio_pcm: bytes,
        sample_rate: int = 16000,
    ) -> tuple[str, str, float | None]:
        samples = np.frombuffer(audio_pcm, dtype=np.int16).astype(np.float32) / 32768.0

        def _run() -> str:
            result = self._engine.transcribe(samples)  # type: ignore[attr-defined]
            return getattr(result, "text", "")

        text = await asyncio.to_thread(_run)
        # The concrete engine does not report a confidence; ``None`` means
        # "not reported" rather than "zero confidence".
        return (text, text, None)


class LLMStreamAdapter:
    """Adapt ``lva.llm.stream`` to ``LLMProvider``.

    ``is_cancelled`` is checked between tokens so a stale turn stops mid-stream
    instead of running to completion.
    """

    def __init__(self, stream_fn: Callable[..., object] | None = None, model: str | None = None) -> None:
        if stream_fn is None:
            from .. import llm as LLM

            stream_fn = LLM.stream
        self._stream_fn = stream_fn
        self._model = model
        self.name = "llm-adapter"

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        turn_id: TurnId,
        provider_epoch: int,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> AsyncIterator[str]:
        kwargs: dict[str, object] = {}
        if self._model:
            kwargs["model"] = self._model
        iterator = iter(await asyncio.to_thread(lambda: list(self._stream_fn(messages, **kwargs))))
        for chunk in iterator:
            if is_cancelled is not None and is_cancelled():
                return
            yield str(chunk)


class TTSEngineAdapter:
    """Adapt an ``lva.tts`` engine (MeloTTS/SapiTTS) to ``TTSProvider``."""

    def __init__(self, engine: object, engine_name: str | None = None) -> None:
        self._engine = engine
        self._name = engine_name or getattr(engine, "name", "tts-adapter")

    @property
    def name(self) -> str:
        return str(self._name)

    async def stream_speech(
        self,
        text: str,
        turn_id: TurnId,
        provider_epoch: int,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> AsyncIterator[bytes]:
        if is_cancelled is not None and is_cancelled():
            return

        def _run() -> bytes:
            syn = self._engine.synthesize(text)  # type: ignore[attr-defined]
            samples = getattr(syn, "samples", None)
            if samples is None:
                return b""
            return np.asarray(samples, dtype=np.int16).tobytes()

        pcm = await asyncio.to_thread(_run)
        if is_cancelled is not None and is_cancelled():
            return
        # A single chunk: the concrete engines synthesize whole utterances, so a
        # thin adapter must not invent a chunking policy of its own.
        if pcm:
            yield pcm
