from __future__ import annotations

from typing import AsyncIterator, Callable, Protocol, runtime_checkable

from ..contracts.ids import TurnId


@runtime_checkable
class ASRProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def transcribe(
        self,
        audio_pcm: bytes,
        sample_rate: int = 16000,
    ) -> tuple[str, str, float | None]:
        """Transcribe PCM audio. Returns (raw_text, corrected_text, confidence)."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        turn_id: TurnId,
        provider_epoch: int,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> AsyncIterator[str]:
        """Stream response tokens for a turn. Drops or halts if is_cancelled() is True."""
        ...


@runtime_checkable
class TTSProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def stream_speech(
        self,
        text: str,
        turn_id: TurnId,
        provider_epoch: int,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> AsyncIterator[bytes]:
        """Stream raw audio PCM chunks for synthesized speech."""
        ...
