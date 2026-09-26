"""R41 FIX-004 - a normal new turn's audio must not be dropped as stale."""
from __future__ import annotations

import queue
import threading
from types import SimpleNamespace

import numpy as np
import pytest

pytestmark = pytest.mark.red_v121


def _real_player():
    """A real Player with the audio device replaced by a manual callback."""
    from lva.audio import Player

    p = object.__new__(Player)
    p._q = queue.Queue()
    p._paused = threading.Event()
    p._muted = threading.Event()
    p._finished = threading.Event()
    p._lock = threading.Lock()
    p.playing = threading.Event()
    p._generation = 0
    p.stale_dropped = 0
    p.rate = 44100
    p.reference = SimpleNamespace(push=lambda *a: None)
    # The real player's queue drains only from the audio callback, which this
    # fixture drives manually.  `_run_turn` waits on `pending()` at the end, so it
    # is reported empty: the test renders explicitly to observe the stale-drop.
    p.pending = lambda: 0
    return p


def _voice(tmp_path, player):
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
    v.player = player
    v.tts = SimpleNamespace(synthesize=lambda text: SimpleNamespace(
        samples=np.ones(16, dtype=np.float32), sample_rate=44100))
    v.core_effect_epoch = None
    v.core_effect_gate = None
    return v


def _render(player, frames=16):
    out = np.zeros((frames, 1), dtype=np.float32)
    player._callback(out, frames, None, None)
    return out


def test_a_normal_new_turn_audio_is_rendered_not_dropped(monkeypatch, tmp_path):
    """F-004: the turn's own audio must reach the output, not be filtered out."""
    import lva.pipeline as pipeline

    player = _real_player()
    v = _voice(tmp_path, player)
    monkeypatch.setattr(pipeline.LLM, "stream", lambda *a, **kw: iter(["hello there."]))
    try:
        v._run_turn(SimpleNamespace(raw="q", corrected="q", domain="general"), 0)
        rendered = _render(player)
        assert player.stale_dropped == 0, (
            f"a normal new turn was dropped as stale (stale_dropped={player.stale_dropped})"
        )
        assert np.any(rendered), (
            "the current turn produced no audible samples: the Player rejected its "
            "own turn as stale"
        )
    finally:
        v.memory._db.close()


def test_a_stale_packet_is_still_rejected_after_the_identity_moves(monkeypatch, tmp_path):
    """The fix must not weaken the stale-drop: an older packet is still refused."""
    import lva.pipeline as pipeline

    player = _real_player()
    v = _voice(tmp_path, player)
    monkeypatch.setattr(pipeline.LLM, "stream", lambda *a, **kw: iter(["first."]))
    try:
        v._run_turn(SimpleNamespace(raw="q", corrected="q", domain="general"), 0)
        # A newer turn owns playback now; a packet queued under the old identity
        # must be dropped at the point of use.
        stale_gen = player.generation
        player.set_generation(stale_gen + 1)
        player.play(np.ones(16, dtype=np.float32), 44100, gen=stale_gen)
        player.stale_dropped = 0
        rendered = _render(player)
        assert player.stale_dropped >= 1 and not np.any(rendered), (
            "a stale packet was rendered instead of dropped: "
            f"stale_dropped={player.stale_dropped}, rendered_nonzero={bool(np.any(rendered))}"
        )
    finally:
        v.memory._db.close()
