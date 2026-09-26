"""Core-owned turn orchestration (v1.2.1 PR-010 remainder).

Why this exists: I22 says every conversation entry goes through the
dispatcher/TurnController and must not call providers, playback or Journal
directly.  R10 got ``/api/ask`` to *open* its turn through ``turn.send_text``, but
the actual orchestration -- prompt build, LLM stream, TTS synthesis, Journal
commit -- still lived in the route body.  This module is where that work belongs.

Design constraint: ``core/`` deliberately does not import the concrete clients
(``lva.llm``, ``lva.tts``, ``lva.pipeline``).  The executor therefore receives
**narrow callables** and a journal handle from its owner (``server.py``), which is
the same shape the provider registry uses.  Core stays the state authority; the
concrete clients stay where they are.

The three stale gates are applied *here*, not by the caller: a new entry point
that forgets a gate would otherwise be able to emit a stale effect, which is the
exact failure the gates exist to prevent.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence
from uuid import uuid4

from .runtime import RuntimeController

log = logging.getLogger("lva.core.turn_executor")


@dataclass
class TurnOutcome:
    """Result of one text turn, shaped for the transport adapter to serialize."""

    raw_text: str = ""
    corrected_text: str = ""
    applied: bool = False
    domain: str = "auto"
    hits: list[dict] = field(default_factory=list)
    reply: str = ""
    llm_mode: str = "fast"
    ttft_ms: float | None = None
    total_ms: float = 0.0
    tts_ms: float | None = None
    audio_hex: str | None = None
    turn_id: Any = None
    provider_epoch: int = 0
    failed: str | None = None


class TurnExecutor:
    """Runs one text turn against the Core state machine.

    All collaborators are injected.  ``stream_reply`` and ``synthesize`` are the
    only ways this class touches a provider, so a test can drive a complete turn
    with the PR-011 contract mocks and no model.
    """

    def __init__(
        self,
        runtime: RuntimeController,
        journal: Any,
        correct_text: Callable[[str, str | None], Any],
        build_messages: Callable[[Any, str], list[dict[str, str]]],
        stream_reply: Callable[[list[dict[str, str]], str], Sequence[str]],
        synthesize: Callable[[str], Any] | None = None,
        to_wav_hex: Callable[[Any], str] | None = None,
        strip_for_speech: Callable[[str], str] | None = None,
        deep_hints: Sequence[str] = (),
        journal_limit: int = 5,
    ) -> None:
        self._runtime = runtime
        self._journal = journal
        self._correct_text = correct_text
        self._build_messages = build_messages
        self._stream_reply = stream_reply
        self._synthesize = synthesize
        self._to_wav_hex = to_wav_hex
        self._strip_for_speech = strip_for_speech or (lambda text: text)
        self._deep_hints = tuple(deep_hints)
        self._journal_limit = journal_limit

    def run_text_turn(self, text: str, domain: str | None = None, speak: bool = False) -> TurnOutcome:
        """Execute one text turn.

        The caller is expected to have opened the turn through the dispatcher
        (``turn.send_text``) already; this method does not allocate a turn, it
        performs the effects for the current one.
        """
        rt = self._runtime
        outcome = TurnOutcome()

        session_id = rt.session_controller.current_session_id
        turn_id = rt.turn_controller.current_turn
        epoch = rt.interrupt_controller.provider_epoch
        outcome.turn_id = turn_id
        outcome.provider_epoch = epoch

        corrected = self._correct_text(text, domain)
        outcome.raw_text = getattr(corrected, "raw", text)
        outcome.corrected_text = getattr(corrected, "corrected", text)
        outcome.applied = bool(getattr(corrected, "applied", False))
        outcome.domain = getattr(corrected, "domain", domain or "auto")

        t0 = time.perf_counter()

        # Journal recall is a read; it needs no gate because it has no effect.
        hits = self._journal.search(outcome.corrected_text, limit=self._journal_limit)
        outcome.hits = hits
        block = "\n".join(
            f"[{h.get('occurred_at_utc_us', 0)}] {h.get('current_text', '')}" for h in hits
        )

        messages = self._build_messages(corrected, block)
        llm_mode = "deep" if any(k in outcome.corrected_text for k in self._deep_hints) else "fast"
        outcome.llm_mode = llm_mode

        parts: list[str] = []
        try:
            for piece in self._stream_reply(messages, llm_mode):
                # Gate 2: between tokens, so a superseded turn stops mid-stream.
                if not rt.stale_gate.check_gate2_in_stream(turn_id, epoch):
                    break
                if outcome.ttft_ms is None:
                    outcome.ttft_ms = (time.perf_counter() - t0) * 1000
                parts.append(piece)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a failure
            rt.turn_controller.cancel_turn(turn_id, reason="provider_error")
            outcome.failed = str(exc)
            return outcome

        outcome.reply = "".join(parts)
        outcome.total_ms = (time.perf_counter() - t0) * 1000

        # Gate 3 before the playback side effect.
        if (
            speak
            and self._synthesize is not None
            and rt.stale_gate.check_gate3_pre_side_effect(turn_id, epoch, "tts_playback")
        ):
            try:
                t1 = time.perf_counter()
                synthesis = self._synthesize(self._strip_for_speech(outcome.reply))
                outcome.tts_ms = (time.perf_counter() - t1) * 1000
                if self._to_wav_hex is not None:
                    outcome.audio_hex = self._to_wav_hex(synthesis)
            except Exception as exc:  # noqa: BLE001
                log.warning("TTS synthesis failed for turn %s: %s", turn_id, exc)

        # Gate 3 before the Journal side effect.
        if rt.stale_gate.check_gate3_pre_side_effect(turn_id, epoch, "journal_commit"):
            self._journal.append_event(
                event_id=uuid4(),
                raw_text=text,
                session_id=session_id,
                turn_sequence=turn_id.sequence,
                speaker="user",
                source="text",
                domain=outcome.domain,
            )
            # T04: record the reply before completing the turn, so the
            # `turn.completed` event (emitted from `complete_turn`) carries the
            # text the caller expects to render.
            rt.reply_text = outcome.reply
            rt.turn_controller.complete_turn(turn_id)

        return outcome
