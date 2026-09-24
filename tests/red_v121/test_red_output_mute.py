"""RED: v1.2.1 patch #6 - Output Mute semantics (feeds R14).

Frozen rule (v1.2.1 §3.3 + §8.4 + PR-024 acceptance):
* The control is named "Output Mute / 静音播放".
* It immediately stops and suppresses speaker playback ONLY.
* It must NOT stop the Core mic, VAD/ASR, Journal, or reality capture.
* The tooltip must state that mic and recording keep their current mode.
* An undirected "Mute / 静音" label is forbidden.

Current state: the island renders a "Mute Mic Button" whose handler calls
``runtime.setMode('standby')`` / ``setMode('live')`` - i.e. muting switches the
whole product mode and stops capture. This directly contradicts the frozen rule.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

ISLAND = REPO_ROOT / "apps" / "desktop-ui" / "src" / "features" / "character" / "ControlsIsland.vue"
STORE = REPO_ROOT / "apps" / "desktop-ui" / "src" / "stores" / "runtime.ts"


def _mute_handler_body() -> str:
    src = read_text(ISLAND)
    m = re.search(r"(?:async\s+)?function\s+toggleMute\s*\([^)]*\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "ControlsIsland.vue must expose a mute handler to inspect"
    return m.group(1)


def test_mute_does_not_change_mode():
    body = _mute_handler_body()
    assert "setMode" not in body, (
        "Output Mute must not call setMode(); muting output is not a mode change "
        "and must leave mic/VAD/ASR/Journal/reality capture untouched "
        f"(handler body: {body.strip()[:160]!r})"
    )


def test_mute_does_not_touch_capture_state():
    body = _mute_handler_body()
    forbidden = [t for t in ("set_mode", "privacy", "capture", "stop_core_mic") if t in body.lower()]
    assert not forbidden, (
        f"Output Mute handler must not touch capture/recording state: {forbidden}"
    )


def test_label_is_output_mute_not_bare_mute():
    src = read_text(ISLAND)
    assert "Mute Mic" not in src, (
        "the island still labels the control 'Mute Mic'; v1.2.1 §8.4 requires "
        "'Output Mute / 静音播放' and forbids an undirected mute label"
    )
    assert ("Output Mute" in src) or ("静音播放" in src), (
        "the control must be labelled 'Output Mute / 静音播放' (v1.2.1 §8.4)"
    )


def test_tooltip_states_capture_is_unchanged():
    src = read_text(ISLAND)
    has_note = ("麦克风和录制" in src) or ("mic and recording" in src.lower())
    assert has_note, (
        "v1.2.1 §8.4 requires the Output Mute tooltip to state that the "
        "microphone and recording keep their current mode"
    )


def test_playback_mute_is_a_separate_command_from_mode():
    """The mute intent must exist as its own command/state, not as a mode."""
    src = read_text(STORE)
    assert "setMuted" in src or "playback.muted" in src or "mutePlayback" in src, (
        "there is no playback-mute action in the runtime store; mute currently "
        "has no representation other than a mode switch"
    )