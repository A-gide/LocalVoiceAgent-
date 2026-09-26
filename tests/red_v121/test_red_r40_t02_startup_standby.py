"""R40 T02 - startup must not open the microphone; entering capture must."""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.red_v121


def _stub_vad(monkeypatch, pipeline):
    """Replace the Silero VAD so the test does not need the model file.

    The pipeline constructor loads `silero_vad.onnx`; the gate harness isolates
    the model directory, so the behaviour under test (device opening) must not
    depend on that file being present.
    """

    class FakeVad:
        def __init__(self, *args, **kwargs):
            self.speech_detected = False

        def accept(self, block):
            return []

        def reset(self):
            pass

    monkeypatch.setattr(pipeline, "Vad", FakeVad)


def test_real_voicecore_start_does_not_open_the_microphone(monkeypatch, tmp_path):
    """I19: the real `VoiceCore.start(open_devices=False)` must not start the mic."""
    import lva.pipeline as pipeline

    _stub_vad(monkeypatch, pipeline)

    opened = {"mic": 0, "player": 0}

    class FakeMic:
        device_name = "fake-mic"

        def __init__(self, cb, device=None):
            pass

        def start(self):
            opened["mic"] += 1

        def stop(self):
            pass

        def enable_aec(self, *a, **k):
            pass

    monkeypatch.setattr(pipeline.A, "Microphone", FakeMic)
    monkeypatch.setattr(pipeline.A, "make_player", lambda **k: SimpleNamespace(
        device_name="fake-out", start=lambda: opened.__setitem__("player", opened["player"] + 1),
        stop=lambda: None, play=lambda *a, **k: None, pending=lambda: 0,
        mark_end=lambda: None, flush=lambda: None, set_muted=lambda m: None,
    ))

    v = pipeline.VoiceCore(use_player=True, muted=True, tts_engine="none")
    monkeypatch.setattr(v, "load_asr", lambda *a, **k: SimpleNamespace(transcribe=lambda *a, **k: None))
    monkeypatch.setattr(pipeline, "ASR", pipeline.ASR)
    v.start(open_devices=False)
    try:
        assert opened["mic"] == 0, (
            "startup opened the microphone (real VoiceCore entry): "
            f"mic_starts={opened['mic']}"
        )
        assert v.mic is None, "startup created a microphone before any consent"
    finally:
        v._running = False
        v._frame_q.put(None)
        v._turn_q.put(None)
        for t in (v._frame_thread, v._turn_thread):
            if t:
                t.join(timeout=2)


def test_entering_a_capture_mode_opens_the_microphone(monkeypatch, tmp_path):
    """The other direction: an explicit capture mode must actually open the mic."""
    import lva.pipeline as pipeline

    _stub_vad(monkeypatch, pipeline)

    opened = {"mic": 0}

    class FakeMic:
        device_name = "fake-mic"

        def __init__(self, cb, device=None):
            self._cb = cb
            self.started = False

        def start(self):
            if not self.started:
                opened["mic"] += 1
                self.started = True

        def stop(self):
            self.started = False

        def enable_aec(self, *a, **k):
            pass

    monkeypatch.setattr(pipeline.A, "Microphone", FakeMic)
    monkeypatch.setattr(pipeline.A, "make_player", lambda **k: SimpleNamespace(
        device_name="fake-out", start=lambda: None, stop=lambda: None,
        play=lambda *a, **k: None, pending=lambda: 0, mark_end=lambda: None,
        flush=lambda: None, set_muted=lambda m: None,
    ))

    v = pipeline.VoiceCore(use_player=True, muted=True, tts_engine="none")
    monkeypatch.setattr(v, "load_asr", lambda *a, **k: SimpleNamespace(transcribe=lambda *a, **k: None))

    assert opened["mic"] == 0
    v.ensure_devices()
    assert opened["mic"] == 1, "entering capture did not open the microphone"
    assert v.mic is not None
    # Idempotent: a second transition must not create a second device.
    v.ensure_devices()
    assert opened["mic"] == 1


def test_startup_lifespan_passes_open_devices_false():
    """Guard the specific regression: boot must not call the default start()."""
    import lva.server as server
    from lva.contracts.enums import Mode

    src = inspect.getsource(server.lifespan)
    assert "open_devices=False" in src, (
        "lifespan must start the pipeline without opening the audio devices"
    )
    assert "Mode.PASSIVE" not in src and "PL.Mode.RECORDING" not in src
