"""Contract mocks for the ASR/LLM/TTS protocols (v1.2.1 PR-011).

The frozen acceptance line is "contract mocks can run a complete turn": these
implement the three protocols from :mod:`lva.providers.base` with no model, no
network and no audio device, so a turn can be driven end to end in a test or a
harness run.

They are also the doubles the quality harness uses, which is why they live in the
package rather than in a test module: PR-011 asks for them as a deliverable.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Callable

from ..contracts.ids import TurnId


class MockASRProvider:
    """Deterministic ASR double.

    Returns whatever ``scripted_text`` is set to, so a caller can assert on a known
    transcript without an audio pipeline.
    """

    def __init__(self, scripted_text: str = "mock transcript", confidence: float = 1.0) -> None:
        self.scripted_text = scripted_text
        self.confidence = confidence
        self.calls: int = 0

    @property
    def name(self) -> str:
        return "mock-asr"

    async def transcribe(
        self,
        audio_pcm: bytes,
        sample_rate: int = 16000,
    ) -> tuple[str, str, float | None]:
        self.calls += 1
        return (self.scripted_text, self.scripted_text, self.confidence)


class MockLLMProvider:
    """Deterministic LLM double with explicit stream/cancel semantics.

    ``is_cancelled`` is honoured between tokens, which is the behaviour the frozen
    step "make stream/cancel/errors explicit" is about.  ``fail_after`` injects an
    error mid-stream so fault paths are reachable.
    """

    def __init__(
        self,
        tokens: tuple[str, ...] = ("mock ", "reply"),
        fail_after: int | None = None,
    ) -> None:
        self.tokens = tokens
        self.fail_after = fail_after
        self.calls: int = 0
        self.cancelled_mid_stream: bool = False

    @property
    def name(self) -> str:
        return "mock-llm"

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        turn_id: TurnId,
        provider_epoch: int,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> AsyncIterator[str]:
        self.calls += 1
        for index, token in enumerate(self.tokens):
            if is_cancelled is not None and is_cancelled():
                self.cancelled_mid_stream = True
                return
            if self.fail_after is not None and index >= self.fail_after:
                raise RuntimeError("mock LLM failure injected")
            await asyncio.sleep(0)
            yield token


class MockTTSProvider:
    """Deterministic TTS double producing silent PCM chunks."""

    def __init__(self, chunk_count: int = 2, chunk_bytes: int = 320) -> None:
        self.chunk_count = chunk_count
        self.chunk_bytes = chunk_bytes
        self.calls: int = 0
        self.cancelled_mid_stream: bool = False

    @property
    def name(self) -> str:
        return "mock-tts"

    async def stream_speech(
        self,
        text: str,
        turn_id: TurnId,
        provider_epoch: int,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> AsyncIterator[bytes]:
        self.calls += 1
        for _ in range(self.chunk_count):
            if is_cancelled is not None and is_cancelled():
                self.cancelled_mid_stream = True
                return
            await asyncio.sleep(0)
            yield b"\x00" * self.chunk_bytes


def build_mock_registry(
    get_current_mode: Callable[[], object],
) -> "ProviderRegistry":  # noqa: F821 - forward ref keeps the import order simple
    """A registry pre-loaded with all three contract mocks.

    This is the "contract mocks can run a complete turn" entry point: callers get
    a ready registry without assembling doubles by hand.
    """
    from .registry import ProviderRegistry

    registry = ProviderRegistry(get_current_mode=get_current_mode)  # type: ignore[arg-type]
    registry.register_asr(MockASRProvider(), make_active=True)
    registry.register_llm(MockLLMProvider(), make_active=True)
    registry.register_tts(MockTTSProvider(), make_active=True)
    return registry
