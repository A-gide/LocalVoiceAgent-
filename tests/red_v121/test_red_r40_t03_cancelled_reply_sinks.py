"""R40 T03 — a cancelled reply must not reach history or the legacy Memory."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.red_v121


def _voice(tmp_path):
    import lva.pipeline as pipeline
    from lva.memory import Memory

    v = object.__new__(pipeline.VoiceCore)
    v._cancel = threading.Event()
    v._speaking = threading.Event()
    v._generation = 0
    v._candidate_pending = False
    v._playback_level = 0.0
    v.mode = pipeline.Mode.LIVE
    v.floor_owner = pipeline.FloorOwner.NONE
    v.history = []
    v.memory = Memory(tmp_path / "memory.db")
    v._prompt_messages = lambda *args: []
    v.on_event = lambda e: None
    v.player = None
    v.tts = None
    v.core_effect_epoch = None
    v.core_effect_gate = None
    return v


def test_a_cancelled_reply_does_not_write_history_or_memory(monkeypatch, tmp_path):
    """The reply is a side effect; cancellation must gate the point of write."""
    import lva.pipeline as pipeline

    v = _voice(tmp_path)
    events = []
    v.on_event = events.append

    def stream(*a, **kw):
        yield "synthetic partial"
        v.cancel_turn()
        yield "late rejected"

    monkeypatch.setattr(pipeline.LLM, "stream", stream)
    try:
        v._run_turn(
            SimpleNamespace(raw="q", corrected="q", domain="general"), 0
        )
        rows = v.memory._db.execute("SELECT COUNT(*) FROM utterances").fetchone()[0]
        replies = [e for e in events if getattr(e, "kind", None) == "reply"]
        assert v.last_turn.cancelled is True
        assert len(v.history) == 0, (
            f"a cancelled reply reached history: {v.history!r}"
        )
        assert rows == 0, (
            f"a cancelled reply was persisted to the legacy Memory: rows={rows}"
        )
    finally:
        v.memory._db.close()


def test_a_reply_under_a_superseded_core_epoch_is_dropped(monkeypatch, tmp_path):
    """An interrupt that bumps the Core epoch must invalidate an in-flight reply."""
    import lva.pipeline as pipeline

    v = _voice(tmp_path)
    epoch = {"value": 0}
    v.core_effect_epoch = lambda: epoch["value"]
    v.core_effect_gate = lambda e: e == epoch["value"]

    def stream(*a, **kw):
        epoch["value"] += 1  # an interrupt supersedes this turn mid-stream
        yield "reply produced while superseded"

    monkeypatch.setattr(pipeline.LLM, "stream", stream)
    try:
        v._run_turn(
            SimpleNamespace(raw="q", corrected="q", domain="general"), 0
        )
        rows = v.memory._db.execute("SELECT COUNT(*) FROM utterances").fetchone()[0]
        assert len(v.history) == 0 and rows == 0, (
            "a superseded-epoch reply reached the sinks: "
            f"history={v.history!r}, memory_rows={rows}"
        )
    finally:
        v.memory._db.close()


def test_a_normal_reply_still_writes_history_and_memory(monkeypatch, tmp_path):
    """The gate must not silence a legitimate reply (no over-reach)."""
    import lva.pipeline as pipeline

    v = _voice(tmp_path)
    epoch = {"value": 7}
    v.core_effect_epoch = lambda: epoch["value"]
    v.core_effect_gate = lambda e: e == epoch["value"]
    monkeypatch.setattr(pipeline.LLM, "stream", lambda *a, **kw: iter(["a real reply"]))
    try:
        v._run_turn(
            SimpleNamespace(raw="q", corrected="q", domain="general"), 0
        )
        rows = v.memory._db.execute("SELECT COUNT(*) FROM utterances").fetchone()[0]
        assert len(v.history) == 2 and rows == 1, (
            "an un-interrupted reply was wrongly dropped: "
            f"history={v.history!r}, memory_rows={rows}"
        )
    finally:
        v.memory._db.close()
