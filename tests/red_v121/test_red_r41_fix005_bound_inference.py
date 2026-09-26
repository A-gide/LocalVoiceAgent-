"""R41 FIX-005 - inference must use the committed Hub binding, not the config default."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np
import pytest

pytestmark = pytest.mark.red_v121


def test_bound_inference_model_follows_the_committed_binding():
    """The runtime exposes the committed model, and None when nothing is bound."""
    from lva.contracts.state import HubBinding
    from lva.core.runtime import RuntimeController

    rt = RuntimeController()
    assert rt.bound_inference_model() is None, (
        "an unbound runtime must not claim a bound model"
    )
    rt.set_hub_binding(HubBinding(desired_model_id="chosen-B", active_model_id="chosen-B"))
    assert rt.bound_inference_model() == "chosen-B", (
        "the committed binding must drive inference, not the configured default"
    )


def test_the_live_turn_streams_with_the_bound_model(monkeypatch, tmp_path):
    """F-005: `_run_turn` must pass the committed model to the LLM stream."""
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
    v._prompt_messages = lambda *a: []
    v.on_event = lambda e: None
    v.player = None
    v.tts = None
    v.core_effect_epoch = None
    v.core_effect_gate = None
    v.bound_inference_model = lambda: "chosen-B"

    captured = {}

    def fake_stream(messages, **kw):
        captured.update(kw)
        return iter(["reply"])

    monkeypatch.setattr(pipeline.LLM, "stream", fake_stream)
    try:
        v._run_turn(SimpleNamespace(raw="q", corrected="q", domain="general"), 0)
        assert captured.get("model") == "chosen-B", (
            "the live turn streamed with the configured default instead of the "
            f"committed binding: model={captured.get('model')!r}"
        )
    finally:
        v.memory._db.close()


def test_an_unbound_turn_keeps_the_configured_default(monkeypatch, tmp_path):
    """No binding -> no forced model, so the non-Hub path still works."""
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
    v._prompt_messages = lambda *a: []
    v.on_event = lambda e: None
    v.player = None
    v.tts = None
    v.core_effect_epoch = None
    v.core_effect_gate = None
    v.bound_inference_model = lambda: None

    captured = {}
    monkeypatch.setattr(pipeline.LLM, "stream", lambda m, **kw: (captured.update(kw), iter(["r"]))[1])
    try:
        v._run_turn(SimpleNamespace(raw="q", corrected="q", domain="general"), 0)
        assert captured.get("model") is None, (
            "an unbound turn forced a model instead of using the configured default: "
            f"model={captured.get('model')!r}"
        )
    finally:
        v.memory._db.close()
