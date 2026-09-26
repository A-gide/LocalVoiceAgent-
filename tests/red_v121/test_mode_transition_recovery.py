"""Execute the real mode-transition reconciler (not a string match).

`apps/desktop-ui/src/stores/modeTransition.js` is plain ESM, so Node runs the
exact code the store imports.  The store's own `setMode` wiring is checked
separately by a source assertion.
"""
from __future__ import annotations

import json
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
MODULE = REPO / "apps" / "desktop-ui" / "src" / "stores" / "modeTransition.js"


def _run(script: str) -> dict:
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=str(MODULE.parent),
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _call(expr: str) -> dict:
    return _run(
        f"import {{ reconcileSetMode, foldRevisions }} from './modeTransition.js';\n"
        f"console.log(JSON.stringify({expr}));"
    )


def test_applied_result_keeps_mode_and_adopts_the_returned_revision():
    out = _call(
        "reconcileSetMode({"
        " state: { mode: 'live', runtime_control_revision: 0, hub_binding_revision: 0 },"
        " prevMode: 'standby',"
        " result: { status: 'applied', revisions: { runtime_control: 1 } } })"
    )
    assert out["mode"] == "live"
    assert out["runtime_control_revision"] == 1
    assert out["rolledBack"] is False
    assert out["source"] == "applied"


def test_conflict_then_flat_snapshot_keeps_the_new_mode_and_revision():
    """The case the review called out: recovery must not be undone."""
    out = _call(
        "reconcileSetMode({"
        " state: { mode: 'live', runtime_control_revision: 0, hub_binding_revision: 0 },"
        " prevMode: 'standby',"
        " result: { status: 'rejected', error: { code: 'STALE_REVISION' } },"
        " refreshed: { mode: 'live', runtime_control_revision: 4, hub_binding_revision: 2 } })"
    )
    assert out["rolledBack"] is False, "a successful recovery must not be rolled back"
    assert out["mode"] == "live", "the store must keep the refreshed mode"
    assert out["runtime_control_revision"] == 4, "the refreshed revision must be adopted"
    assert out["hub_binding_revision"] == 2
    assert out["source"] == "refreshed"


def test_conflict_without_a_successful_refresh_still_rolls_back():
    out = _call(
        "reconcileSetMode({"
        " state: { mode: 'live', runtime_control_revision: 0 },"
        " prevMode: 'standby',"
        " result: { status: 'rejected', error: { code: 'STALE_REVISION' } },"
        " refreshed: null })"
    )
    assert out["rolledBack"] is True
    assert out["mode"] == "standby"


def test_non_stale_rejection_rolls_back():
    out = _call(
        "reconcileSetMode({"
        " state: { mode: 'live', runtime_control_revision: 3 },"
        " prevMode: 'standby',"
        " result: { status: 'rejected', error: { code: 'INVALID_TRANSITION' } },"
        " refreshed: { mode: 'live', runtime_control_revision: 9 } })"
    )
    assert out["rolledBack"] is True, "only STALE_REVISION may recover via a refresh"
    assert out["mode"] == "standby"


def test_fold_revisions_only_touches_known_aggregates():
    out = _call(
        "(() => { const s = { runtime_control_revision: 0, hub_binding_revision: 0 };"
        " foldRevisions(s, { revisions: { runtime_control: 5, settings: 7 } });"
        " return s; })()"
    )
    assert out == {"runtime_control_revision": 5, "hub_binding_revision": 0}


def test_store_setmode_uses_the_reconciler_and_the_flat_snapshot():
    src = (MODULE.parent / "runtime.ts").read_text(encoding="utf-8")
    body = src[src.index("async function setMode("):]
    body = body[: body.index("\n  async function ")]
    assert "reconcileSetMode(" in body, "setMode must delegate to the reconciler"
    assert "await fetchSnapshotState()" in body, (
        "setMode must read the authoritative snapshot before deciding"
    )
    # the reconciler owns the decision, so setMode must not roll back on its own
    assert "state.value.mode = prevMode" not in body, (
        "setMode must not roll back outside the reconciler"
    )