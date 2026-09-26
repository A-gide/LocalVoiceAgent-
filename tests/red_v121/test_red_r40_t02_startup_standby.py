"""R40 T02 — startup must not implicitly open capture; it must start in Standby."""
from __future__ import annotations

import asyncio
import inspect

import pytest

pytestmark = pytest.mark.red_v121


def test_startup_enters_standby_and_does_not_open_the_mic(monkeypatch, tmp_path):
    """I19: boot must reach Standby with the mic device untouched."""
    from lva import config as C
    import lva.server as server
    from lva.contracts.enums import Mode

    monkeypatch.setattr(C, "DATA", tmp_path)
    monkeypatch.setattr(server, "_journal", None)
    monkeypatch.setattr(server, "_runtime", None)
    monkeypatch.setattr(server, "_core", None)

    mic_starts = {"count": 0}

    class FakeMic:
        device_name = "fake-mic"

        def start(self):
            mic_starts["count"] += 1

        def stop(self):
            pass

    class FakeCore:
        asr_name = "fake-asr"
        tts = None
        mic = FakeMic()
        player = None

        def __init__(self):
            self.mode = None

        def start(self):
            pass

        def stop(self):
            pass

        def set_mode(self, mode):
            self.mode = mode

    fake_core = FakeCore()
    monkeypatch.setattr(server, "core", lambda: fake_core)
    # The boot path builds the runtime; keep the real one so the mode is real.
    runtime = server.get_runtime()

    async def _run_lifespan():
        async with server.lifespan(server.app):
            return runtime.mode

    mode_at_boot = asyncio.run(_run_lifespan())

    assert mode_at_boot == Mode.STANDBY, (
        f"startup did not enter Standby; it entered {mode_at_boot}"
    )
    assert mic_starts["count"] == 0, (
        "startup implicitly opened the microphone "
        f"({mic_starts['count']} start call(s)) before any user consent"
    )


def test_the_lifespan_source_does_not_hardcode_passive_or_recording():
    """Guard the specific regression: boot must not set Passive/RECORDING."""
    import lva.server as server

    source = inspect.getsource(server.lifespan)
    assert "Mode.PASSIVE" not in source, "lifespan still hardcodes Passive at startup"
    assert "PL.Mode.RECORDING" not in source, (
        "lifespan still puts the legacy pipeline into RECORDING at startup"
    )
