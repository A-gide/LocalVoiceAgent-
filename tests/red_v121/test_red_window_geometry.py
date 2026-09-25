"""RED: window geometry must clamp and restore (PR-030 / PR-031).

Frozen plan §8.3 and risk L1704: when a monitor is unplugged, the resolution
changes or the DPI differs, a window restored from a stale position can land
off-screen.  The required behaviour is to clamp to the **current monitor work
area** before restoring, and to offer Reset Position -- not to switch frameworks.

S-UI-01 (docs/S-UI-01-Tauri-Window-Capability-Report-2026-09-23.md) recorded the
shipped state: no clamp anywhere in the repo, `setPosition` denied by the ACL
(fixed in R29), and no geometry persistence at all.

`geometry.js` is plain ESM so Node executes the real arithmetic rather than the
test string-matching the component.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from harness import REPO_ROOT

pytestmark = pytest.mark.red_v121

MODULE = REPO_ROOT / "apps" / "desktop-ui" / "src" / "composables" / "window" / "geometry.js"
COMPOSABLE = REPO_ROOT / "apps" / "desktop-ui" / "src" / "composables" / "window" / "useWindowGeometry.ts"


def _run(body: str) -> dict:
    """Execute the real module under Node and return its JSON answer."""
    # Windows requires a file:// URL for an absolute ESM specifier, and the
    # import must be relative to the module so the test runs from any cwd.
    script = (
        f"import * as g from {json.dumps(MODULE.as_uri())};\n"
        f"const out = (() => {{ {body} }})();\n"
        "console.log(JSON.stringify(out));\n"
    )
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr[:600]}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------------- clamp
def test_a_window_off_the_left_is_clamped_into_the_area() -> None:
    out = _run(
        "const p = g.clampToWorkArea({x:-500, y:-300}, {width:360, height:520},"
        " {x:0, y:0, width:1920, height:1080}); return p;"
    )
    assert out == {"x": 0, "y": 0}, (
        f"a window dragged off the top-left must come back to the origin, got {out}"
    )


def test_a_window_off_the_right_is_clamped_into_the_area() -> None:
    out = _run(
        "const p = g.clampToWorkArea({x:5000, y:5000}, {width:360, height:520},"
        " {x:0, y:0, width:1920, height:1080}); return p;"
    )
    assert out == {"x": 1560, "y": 560}, (
        f"the whole window must stay inside the area, got {out}"
    )


def test_a_position_inside_the_area_is_untouched() -> None:
    out = _run(
        "const p = g.clampToWorkArea({x:500, y:400}, {width:360, height:520},"
        " {x:0, y:0, width:1920, height:1080}); return p;"
    )
    assert out == {"x": 500, "y": 400}, "a valid position must not be nudged"


def test_a_window_on_a_secondary_monitor_keeps_its_offset() -> None:
    """Clamping is per monitor: a negative-x area is normal for a left monitor."""
    out = _run(
        "const p = g.clampToWorkArea({x:-1800, y:100}, {width:360, height:520},"
        " {x:-1920, y:0, width:1920, height:1080}); return p;"
    )
    assert out == {"x": -1800, "y": 100}, (
        f"a window on a monitor at negative coordinates must not be pushed to 0, got {out}"
    )


def test_a_window_larger_than_the_area_pins_to_its_origin() -> None:
    """Clamping both ends would oscillate; pin instead of guessing."""
    out = _run(
        "const p = g.clampToWorkArea({x:100, y:100}, {width:3000, height:2000},"
        " {x:0, y:0, width:1920, height:1080}); return p;"
    )
    assert out == {"x": 0, "y": 0}, f"an oversized window must pin to the origin, got {out}"


# ---------------------------------------------------------------- work area
def test_the_window_stays_on_the_monitor_it_was_on() -> None:
    out = _run(
        "const a = g.chooseWorkArea({x:-1800, y:100}, {width:360, height:520},"
        " [{x:0,y:0,width:1920,height:1080},{x:-1920,y:0,width:1920,height:1080}], null);"
        " return a;"
    )
    assert out == {"x": -1920, "y": 0, "width": 1920, "height": 1080}, (
        f"the monitor the window is on must win, got {out}"
    )


def test_a_vanished_monitor_falls_back_to_the_primary() -> None:
    """The exact unplug case the plan is about."""
    out = _run(
        "const r = g.resolveRestoredPosition("
        " {position:{x:3000,y:200}, size:{width:360,height:520}},"
        " [{x:0,y:0,width:1920,height:1080}], {x:0,y:0,width:1920,height:1080}, {x:100,y:100});"
        " return r;"
    )
    assert out["clamped"] is True
    assert out["position"] == {"x": 1560, "y": 200}, (
        f"the window must be clamped onto the remaining monitor, got {out}"
    )


def test_a_healthy_position_is_restored_unchanged() -> None:
    out = _run(
        "const r = g.resolveRestoredPosition("
        " {position:{x:500,y:400}, size:{width:360,height:520}},"
        " [{x:0,y:0,width:1920,height:1080}], null, {x:100,y:100});"
        " return r;"
    )
    assert out["clamped"] is False, "a valid saved position must not be adjusted"
    assert out["position"] == {"x": 500, "y": 400}


def test_no_saved_position_uses_the_fallback() -> None:
    out = _run(
        "const r = g.resolveRestoredPosition(null, [{x:0,y:0,width:1920,height:1080}], null,"
        " {x:100,y:100}); return r;"
    )
    assert out["position"] == {"x": 100, "y": 100}


# ---------------------------------------------------------- persistence input
def test_a_malformed_saved_record_degrades_instead_of_throwing() -> None:
    """A hand-edited or older settings file must not break startup."""
    out = _run(
        "const bad = [null, {}, {x:1}, {x:1,y:2,width:-5,height:10},"
        " {x:'a',y:2,width:10,height:10}, {x:NaN,y:2,width:10,height:10}];"
        " return bad.map((b) => g.parseSavedGeometry(b));"
    )
    assert out == [None, None, None, None, None, None], (
        f"every malformed record must degrade to null, got {out}"
    )


def test_a_valid_saved_record_is_accepted() -> None:
    out = _run(
        "return g.parseSavedGeometry({x:10,y:20,width:360,height:520});"
    )
    assert out == {"position": {"x": 10, "y": 20}, "size": {"width": 360, "height": 520}}


# -------------------------------------------------------------- composable use
def test_the_composable_uses_the_clamp_module() -> None:
    """The logic must be reachable from the component, not dead code."""
    src = COMPOSABLE.read_text(encoding="utf-8")
    assert "geometry.js" in src, (
        "useWindowGeometry must import the clamp module; otherwise the arithmetic "
        "is tested but never used"
    )
    assert "clampToWorkArea" in src or "resolveRestoredPosition" in src, (
        "the composable must call the clamp on restore"
    )
