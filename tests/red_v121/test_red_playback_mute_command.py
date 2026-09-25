"""RED: Output Mute must actually stop and suppress playback (PR-024).

Frozen rule (§8.4 L989, §3.3 L321, PR-024 acceptance L1377):

* the control is "Output Mute / 静音播放";
* it **immediately stops and suppresses speaker playback**;
* it must NOT change capture state -- not the Core mic, VAD/ASR, Journal or
  reality capture;
* stopping capture is Privacy Pause's job, not this one.

What the shipped code did: the island handler called `runtime.setMuted()`, which
only assigned a local ref in the Pinia store.  No command carried the intent, the
Core had no mute path, and `pipeline.py`'s `self.muted` was fixed at construction
from an environment variable.  So the icon changed and the audio kept playing.

The existing output-mute RED was green throughout, because it asserted the
handler does not call `setMode` and that the labels are right -- it never
asserted that sound stops.  That is the fourth time in this project a test
passed while bypassing the behaviour it was supposed to protect.

These tests drive the real dispatcher and the real player object.
"""
from __future__ import annotations

import pytest

from harness import REPO_ROOT, new_dispatcher, read_text
from lva.contracts.commands import CommandEnvelope, PlaybackSetMutedPayload
from lva.contracts.enums import Mode

pytestmark = pytest.mark.red_v121


def _mute_cmd(muted: bool) -> CommandEnvelope:
    return CommandEnvelope(
        type="playback.set_muted",
        payload=PlaybackSetMutedPayload(type="playback.set_muted", muted=muted),
    )


# ------------------------------------------------------------------ the intent
def test_the_mute_intent_is_a_command_not_a_local_ref():
    """A local ref cannot stop audio that a different process is playing."""
    rt = new_dispatcher()
    res = rt.execute_command(_mute_cmd(True))
    assert res.status == "applied", (
        f"the mute intent must reach the Core dispatcher; got {res.status} "
        f"({res.error.code if res.error else 'no error'})"
    )


def test_muting_is_reflected_in_the_published_state():
    """The UI reads `playback.muted`; it must be the Core's own answer."""
    rt = new_dispatcher()
    assert rt.get_state().playback.muted is False
    rt.execute_command(_mute_cmd(True))
    assert rt.get_state().playback.muted is True
    rt.execute_command(_mute_cmd(False))
    assert rt.get_state().playback.muted is False


def test_muting_is_idempotent():
    rt = new_dispatcher()
    assert rt.execute_command(_mute_cmd(True)).status == "applied"
    assert rt.execute_command(_mute_cmd(True)).status == "applied"
    assert rt.get_state().playback.muted is True


# ------------------------------------------------------- capture must not move
def test_muting_does_not_change_capture_state():
    """§3.3: Output Mute is not a capture control; Privacy Pause is."""
    rt = new_dispatcher()
    rt.set_mode(Mode.LIVE)
    before = rt.get_state()
    assert before.mic_capture.active is True

    rt.execute_command(_mute_cmd(True))
    after = rt.get_state()

    assert after.mode == before.mode, "muting output must not change the mode"
    assert after.mic_capture.active is True, (
        "muting output must not stop the microphone; that is Privacy Pause"
    )
    assert after.privacy_scope == before.privacy_scope, (
        "muting output must not touch the privacy scope"
    )
    assert after.managed_capture == before.managed_capture, (
        "muting output must not touch reality capture"
    )


def test_muting_works_in_every_mode_including_privacy_pause():
    """It is an output control, so no mode may forbid it."""
    for mode in (Mode.STANDBY, Mode.PASSIVE, Mode.LIVE, Mode.PRIVACY_PAUSE):
        rt = new_dispatcher()
        rt.set_mode(mode)
        res = rt.execute_command(_mute_cmd(True))
        assert res.status == "applied", (
            f"Output Mute was refused in {mode.value}: {res.status}"
        )
        assert rt.get_state().playback.muted is True


# ----------------------------------------------------- the audio actually stops
def test_muting_flushes_queued_audio_immediately():
    """`flush()` is what stops sound; a flag alone would let the tail play out."""
    from lva.audio import NullPlayer

    player = NullPlayer()
    player.set_muted(True)
    assert player.muted is True, "the player must expose the mute it accepted"

    # A muted player must not accumulate audio: queueing while muted would let a
    # later unmute replay speech the user already silenced.
    import numpy as np

    player.play(np.zeros(1600, dtype=np.float32), 16000)
    assert player.pending() == 0, (
        "audio queued while muted must be dropped, not held for later"
    )


def test_unmuting_does_not_replay_what_was_silenced():
    from lva.audio import NullPlayer

    player = NullPlayer()
    player.set_muted(True)
    import numpy as np

    player.play(np.zeros(1600, dtype=np.float32), 16000)
    player.set_muted(False)
    assert player.pending() == 0, (
        "unmuting must not release speech the user silenced"
    )


def test_the_core_tells_its_owner_to_mute():
    """Core holds no player reference, so it must ask its owner (PR-010 shape)."""
    seen: list[bool] = []
    from lva.core.runtime import RuntimeController

    rt = RuntimeController(on_playback_mute=seen.append)
    rt.execute_command(_mute_cmd(True))
    rt.execute_command(_mute_cmd(False))
    assert seen == [True, False], (
        f"the owner must be told about each mute change in order; got {seen}"
    )


def test_a_failing_mute_callback_does_not_report_success():
    """L1338 in spirit: never report a state the device did not reach."""
    def broken(_muted: bool) -> None:
        raise RuntimeError("audio device refused")

    from lva.core.runtime import RuntimeController

    rt = RuntimeController(on_playback_mute=broken)
    res = rt.execute_command(_mute_cmd(True))
    assert res.status == "rejected", (
        "a mute that the audio device refused must not be reported as applied"
    )
    assert rt.get_state().playback.muted is False, (
        "the published state must not claim a mute that did not happen"
    )


# ------------------------------------------------------------ the UI sends it
def test_the_store_sends_the_command():
    """The island's handler must reach the Core, not just a local ref."""
    src = read_text(REPO_ROOT / "apps" / "desktop-ui" / "src" / "stores" / "runtime.ts")
    m = __import__("re").search(r"function setMuted\(.*?\n  \}", src, __import__("re").S)
    assert m, "the runtime store must expose a setMuted action"
    body = m.group(0)
    assert "sendCoreCommand" in body, (
        "setMuted must send `playback.set_muted` to the Core; assigning a local "
        "ref changes the icon and leaves the speakers playing"
    )
    assert "playback.set_muted" in body

