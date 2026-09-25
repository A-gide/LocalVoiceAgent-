"""RED: the capability must grant what the UI actually calls (PR-023 / R11).

S-UI-01 (docs/S-UI-01-Tauri-Window-Capability-Report-2026-09-23.md) found the
blocking defect: `capabilities/default.json` granted only `core:default`, and
`core:window:default` contains **read-only** permissions.  Every window write the
UI performs was therefore denied by the ACL, and each call site caught the
rejection and only `console.warn`-ed, so click-through, dragging and
reset-position silently did nothing.

The report also noted the label list held only `main`, while `tray.rs` creates
settings / chat / memory windows.  Under the Tauri 2 capability model an unlisted
window has no capability at all, so those windows would be refused even once the
permission exists for another window.

What these tests pin down:

1. every window the shell creates is covered by the capability;
2. every window operation the UI calls is granted;
3. the file is valid JSON the Tauri build accepts -- a trailing comma is enough to
   fail the whole build, which is how the first version of this fix was caught;
4. the grants stay *scoped*: the capability must not simply enumerate every
   permission, because "grant everything" is not the same claim as "grant what
   the UI needs".
"""
from __future__ import annotations

import json
import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

Tauri = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri"
CAPABILITY = Tauri / "capabilities" / "default.json"
TRAY = Tauri / "src" / "tray.rs"
GEOMETRY = REPO_ROOT / "apps" / "desktop-ui" / "src" / "composables" / "window" / "useWindowGeometry.ts"


def _capability() -> dict:
    return json.loads(read_text(CAPABILITY))


def test_every_window_the_shell_creates_is_covered() -> None:
    """An unlisted window has no capability, so its calls are refused."""
    tray = read_text(TRAY)
    created = set(re.findall(r"WebviewWindowBuilder::new\(", tray))
    assert created, "tray.rs must create windows; the probe found none"

    labels = set(re.findall(r'\bWebviewWindowBuilder::new\([^,]+,\s*"([a-z_]+)"', tray))
    assert labels, "no window labels were found to check"

    covered = set(_capability().get("windows", []))
    missing = labels - covered
    assert not missing, (
        f"these windows are created but not covered by the capability: {sorted(missing)}; "
        "under the Tauri 2 model they get no capability at all"
    )


def test_the_window_writes_the_ui_calls_are_granted() -> None:
    """Each call site in the geometry composable must have its permission."""
    geometry = read_text(GEOMETRY)
    calls = {
        "setIgnoreCursorEvents": "core:window:allow-set-ignore-cursor-events",
        "startDragging": "core:window:allow-start-dragging",
        "setPosition": "core:window:allow-set-position",
    }
    granted = set(_capability().get("permissions", []))

    called = [name for name in calls if name in geometry]
    assert called, "the geometry composable must call window APIs to inspect"

    missing = [calls[name] for name in called if calls[name] not in granted]
    assert not missing, (
        f"the UI calls these APIs but the capability does not grant them: {missing}; "
        "the ACL denies the call and the catch only warns, so the feature silently fails"
    )


def test_the_capability_is_valid_json_without_trailing_commas() -> None:
    """A trailing comma fails the Tauri build, not just this test."""
    raw = read_text(CAPABILITY)
    assert not re.search(r",\s*[\]}]", raw), (
        "the capability contains a trailing comma; Tauri rejects the file and the "
        "whole build fails (PowerShell's ConvertFrom-Json accepts it, so it is easy "
        "to miss locally)"
    )
    parsed = json.loads(raw)
    assert parsed.get("identifier") == "default"


def test_monitor_probes_are_granted_for_the_clamp() -> None:
    """PR-030 clamps to the current monitor work area, which needs read access."""
    granted = set(_capability().get("permissions", []))
    for permission in (
        "core:window:allow-current-monitor",
        "core:window:allow-available-monitors",
        "core:window:allow-scale-factor",
    ):
        assert permission in granted, (
            f"{permission} is missing; monitor clamping cannot compute a work area "
            "without it"
        )


def test_the_grants_stay_scoped_rather_than_granting_everything() -> None:
    """A wildcard grant would be a different, weaker claim than this one."""
    permissions = _capability().get("permissions", [])
    assert "core:window:default" not in permissions or len(permissions) < 40, (
        "the capability looks like a blanket grant; it should list the operations "
        "the UI actually performs"
    )
    assert len(permissions) < 40, (
        f"{len(permissions)} permissions is broad enough that the file no longer "
        "documents what the UI needs"
    )

