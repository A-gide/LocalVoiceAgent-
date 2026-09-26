"""R41 FIX-002 - a transcript whose mode/epoch was superseded during ASR must not land."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np
import pytest

pytestmark = pytest.mark.red_v121


def _voice(tmp_path, mode):
    import lva.pipeline as pipeline
    from lva.memory import Memory

    v = object.__new__(pipeline.VoiceCore)
    v._cancel = threading.Event()
    v._speaking = threading.Event()
    v._generation = 0
    v._candidate_pending = False
    v._playback_level = 0.0
    v.mode = mode
    v.floor_owner = pipeline.FloorOwner.NONE
    v.history = []
    v.memory = Memory(tmp_path / "memory.db")
    v.on_event = lambda e: None
    v.stats = {"utterances": 0, "live_turns": 0, "barge_ins": 0,
               "duck_ignored": 0, "backchannels": 0}
    v.session_domain = None
    v.asr_name = "fake"
    v._asr = {}
    v.tts = None
    v.player = None
    v.core_effect_epoch = None
    v.core_effect_gate = None
    v._save_audio = lambda *a, **k: None
    return v


def _memory_rows(v):
    return v.memory._db.execute("SELECT COUNT(*) FROM utterances").fetchone()[0]


def test_a_mode_change_during_asr_drops_the_transcript(monkeypatch, tmp_path):
    """F-002: Privacy Pause / Standby during ASR must not persist the speech."""
    import lva.pipeline as pipeline

    v = _voice(tmp_path, pipeline.Mode.LIVE)
    events = []
    v.on_event = events.append

    class Engine:
        def transcribe(self, samples, hotwords=None):
            v.mode = pipeline.Mode.IDLE  # pause/standby lands mid-transcription
            return SimpleNamespace(text="private words")

    v.load_asr = lambda *a, **k: Engine()
    v.hotwords = lambda: None
    monkeypatch.setattr(pipeline.ASR, "clean", lambda t: t)
    v.vocab = SimpleNamespace(correct=lambda raw, domain=None: SimpleNamespace(
        corrected=raw, raw=raw, applied=False, flagged=False, domain="general"))

    try:
        v._handle_utterance(np.zeros(16000, dtype=np.float32))
        assert _memory_rows(v) == 0, (
            "a transcript transcribed before a mode change still reached the legacy "
            f"Memory: rows={_memory_rows(v)}"
        )
        assert not [e for e in events if getattr(e, "kind", None) == "transcript"], (
            "a superseded transcript was still emitted to the event stream"
        )
    finally:
        v.memory._db.close()


def test_an_epoch_bump_during_asr_drops_the_transcript(monkeypatch, tmp_path):
    """A Core interrupt during ASR invalidates the transcript at the sink."""
    import lva.pipeline as pipeline

    v = _voice(tmp_path, pipeline.Mode.LIVE)
    epoch = {"value": 0}
    v.core_effect_epoch = lambda: epoch["value"]
    v.core_effect_gate = lambda e: e == epoch["value"]

    class Engine:
        def transcribe(self, samples, hotwords=None):
            epoch["value"] += 1  # an interrupt supersedes the utterance
            return SimpleNamespace(text="late words")

    v.load_asr = lambda *a, **k: Engine()
    v.hotwords = lambda: None
    monkeypatch.setattr(pipeline.ASR, "clean", lambda t: t)
    v.vocab = SimpleNamespace(correct=lambda raw, domain=None: SimpleNamespace(
        corrected=raw, raw=raw, applied=False, flagged=False, domain="general"))

    try:
        v._handle_utterance(np.zeros(16000, dtype=np.float32))
        assert _memory_rows(v) == 0, (
            "a superseded-epoch transcript still reached the legacy Memory: "
            f"rows={_memory_rows(v)}"
        )
    finally:
        v.memory._db.close()


def test_a_normal_transcript_still_archives(monkeypatch, tmp_path):
    """The gate must not drop a legitimate transcript (no over-reach)."""
    import lva.pipeline as pipeline

    v = _voice(tmp_path, pipeline.Mode.RECORDING)
    epoch = {"value": 5}
    v.core_effect_epoch = lambda: epoch["value"]
    v.core_effect_gate = lambda e: e == epoch["value"]

    class Engine:
        def transcribe(self, samples, hotwords=None):
            return SimpleNamespace(text="normal words")

    v.load_asr = lambda *a, **k: Engine()
    v.hotwords = lambda: None
    monkeypatch.setattr(pipeline.ASR, "clean", lambda t: t)
    v.vocab = SimpleNamespace(correct=lambda raw, domain=None: SimpleNamespace(
        corrected=raw, raw=raw, applied=False, flagged=False, domain="general"))

    try:
        v._handle_utterance(np.zeros(16000, dtype=np.float32))
        assert _memory_rows(v) == 1, (
            "a legitimate Passive recording was wrongly dropped: "
            f"rows={_memory_rows(v)}"
        )
    finally:
        v.memory._db.close()
