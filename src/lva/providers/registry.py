from __future__ import annotations

import logging
from typing import AsyncIterator, Callable

from ..contracts.enums import ErrorCode, Mode, ProviderState
from ..contracts.ids import TurnId
from ..contracts.state import ProviderStatus
from .base import ASRProvider, LLMProvider, TTSProvider

log = logging.getLogger("lva.providers.registry")


class ProviderRegistry:
    def __init__(self, get_current_mode: Callable[[], Mode]) -> None:
        self._get_current_mode = get_current_mode
        self._asr_providers: dict[str, ASRProvider] = {}
        self._llm_providers: dict[str, LLMProvider] = {}
        self._tts_providers: dict[str, TTSProvider] = {}
        self._active_asr: str | None = None
        self._active_llm: str | None = None
        self._active_tts: str | None = None

    # ------------------------------------------------- capability / state
    # PR-011 asks for a "capability/state registry", not just a name lookup: the
    # Core publishes `RuntimeState.providers`, and this is what feeds it.

    def active_provider_ids(self) -> dict[str, str | None]:
        """The currently selected provider id per kind."""
        return {
            "asr": self._active_asr,
            "llm": self._active_llm,
            "tts": self._active_tts,
        }

    def registered_ids(self) -> dict[str, tuple[str, ...]]:
        """Every registered provider id per kind, sorted for stable output."""
        return {
            "asr": tuple(sorted(self._asr_providers)),
            "llm": tuple(sorted(self._llm_providers)),
            "tts": tuple(sorted(self._tts_providers)),
        }

    def provider_statuses(self) -> dict[str, ProviderStatus]:
        """Typed status for every registered provider, keyed by provider id.

        An active provider is reported READY because registration is what makes it
        usable; a registered-but-inactive provider is reported UNINITIALIZED rather
        than pretending to be warm.  Nothing here inspects a model or a socket, so
        the state is an honest statement about the registry, not about the network.
        """
        active = self.active_provider_ids()
        out: dict[str, ProviderStatus] = {}
        for kind, providers in (
            ("asr", self._asr_providers),
            ("llm", self._llm_providers),
            ("tts", self._tts_providers),
        ):
            for provider_id in providers:
                is_active = active[kind] == provider_id
                out[provider_id] = ProviderStatus(
                    provider_id=provider_id,
                    kind=kind,  # type: ignore[arg-type]
                    state=ProviderState.READY if is_active else ProviderState.UNINITIALIZED,
                    current_model=provider_id if is_active else None,
                )
        return out

    def register_asr(self, provider: ASRProvider, make_active: bool = False) -> None:
        self._asr_providers[provider.name] = provider
        if make_active or self._active_asr is None:
            self._active_asr = provider.name

    def register_llm(self, provider: LLMProvider, make_active: bool = False) -> None:
        self._llm_providers[provider.name] = provider
        if make_active or self._active_llm is None:
            self._active_llm = provider.name

    def register_tts(self, provider: TTSProvider, make_active: bool = False) -> None:
        self._tts_providers[provider.name] = provider
        if make_active or self._active_tts is None:
            self._active_tts = provider.name

    async def transcribe(
        self,
        audio_pcm: bytes,
        sample_rate: int = 16000,
        provider_name: str | None = None,
    ) -> tuple[str, str, float | None]:
        name = provider_name or self._active_asr
        if not name or name not in self._asr_providers:
            raise RuntimeError(f"ASR provider '{name}' not found")
        return await self._asr_providers[name].transcribe(audio_pcm, sample_rate)

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        turn_id: TurnId,
        provider_epoch: int,
        is_cancelled: Callable[[], bool] | None = None,
        provider_name: str | None = None,
    ) -> AsyncIterator[str]:
        # Guard: In Passive or Standby mode, LLM scheduling is strictly forbidden (I07)
        mode = self._get_current_mode()
        if mode in (Mode.PASSIVE, Mode.STANDBY, Mode.PRIVACY_PAUSE):
            raise RuntimeError(
                f"LLM scheduling forbidden in {mode.value} mode ({ErrorCode.PASSIVE_PROVIDER_FORBIDDEN})"
            )

        name = provider_name or self._active_llm
        if not name or name not in self._llm_providers:
            raise RuntimeError(f"LLM provider '{name}' not found")

        async for chunk in self._llm_providers[name].stream_chat(
            messages, turn_id, provider_epoch, is_cancelled
        ):
            yield chunk

    async def stream_speech(
        self,
        text: str,
        turn_id: TurnId,
        provider_epoch: int,
        is_cancelled: Callable[[], bool] | None = None,
        provider_name: str | None = None,
    ) -> AsyncIterator[bytes]:
        # Guard: In Passive or Standby mode, TTS scheduling is strictly forbidden (I08)
        mode = self._get_current_mode()
        if mode in (Mode.PASSIVE, Mode.STANDBY, Mode.PRIVACY_PAUSE):
            raise RuntimeError(
                f"TTS scheduling forbidden in {mode.value} mode ({ErrorCode.PASSIVE_PROVIDER_FORBIDDEN})"
            )

        name = provider_name or self._active_tts
        if not name or name not in self._tts_providers:
            raise RuntimeError(f"TTS provider '{name}' not found")

        async for chunk in self._tts_providers[name].stream_speech(
            text, turn_id, provider_epoch, is_cancelled
        ):
            yield chunk
