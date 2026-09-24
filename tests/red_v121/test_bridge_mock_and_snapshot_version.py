"""The two paths the review called out: mock shape and snapshot_version.

`setMode` no longer writes `snapshot_version` directly; the reconciler owns it,
so the propagation is asserted by executing the reconciler, and the store's
assignment line is asserted structurally.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess

REPO = pathlib.Path(r"E:\AI\LocalVoiceAgent")
UI = REPO / "apps" / "desktop-ui" / "src"
MODULE = UI / "stores" / "modeTransition.js"


def _call(expr: str) -> dict:
    proc = subprocess.run(
        ["node", "--input-type=module", "-e",
         "import { reconcileSetMode } from './modeTransition.js';\n"
         f"console.log(JSON.stringify({expr}));"],
        capture_output=True, text=True, cwd=str(MODULE.parent),
    )
    assert proc.returncode == 0, proc.stderr[-600:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ------------------------------------------------- snapshot_version plumbing
def test_applied_result_propagates_the_returned_snapshot_version():
    out = _call(
        "reconcileSetMode({"
        " state: { mode: 'live', snapshot_version: 3, runtime_control_revision: 0 },"
        " prevMode: 'standby',"
        " result: { status: 'applied', snapshot_version: 4, revisions: { runtime_control: 1 } } })"
    )
    assert out["snapshot_version"] == 4, (
        "the returned snapshot_version must not be dropped"
    )
    assert out["runtime_control_revision"] == 1


def test_refreshed_path_propagates_the_snapshot_version():
    out = _call(
        "reconcileSetMode({"
        " state: { mode: 'live', snapshot_version: 3, runtime_control_revision: 0 },"
        " prevMode: 'standby',"
        " result: { status: 'rejected', error: { code: 'STALE_REVISION' } },"
        " refreshed: { mode: 'live', snapshot_version: 9, runtime_control_revision: 4 } })"
    )
    assert out["snapshot_version"] == 9


def test_rollback_keeps_the_previous_snapshot_version():
    out = _call(
        "reconcileSetMode({"
        " state: { mode: 'live', snapshot_version: 3, runtime_control_revision: 2 },"
        " prevMode: 'standby',"
        " result: { status: 'rejected', error: { code: 'INVALID_TRANSITION' } },"
        " refreshed: null })"
    )
    assert out["rolledBack"] is True
    assert out["snapshot_version"] == 3


def test_store_writes_the_reconciled_snapshot_version_back():
    src = (UI / "stores" / "runtime.ts").read_text(encoding="utf-8")
    body = src[src.index("async function setMode("):]
    body = body[: body.index("\n  async function ")]
    assert "state.value.snapshot_version = next.snapshot_version;" in body, (
        "setMode must write the reconciled snapshot_version back into the store"
    )


# ---------------------------------------------------------------- mock shape
def test_dev_mock_returns_a_flat_snapshot_and_real_field_names():
    src = (UI / "bridge" / "tauri-bridge.ts").read_text(encoding="utf-8")
    assert "data: { state: mockState }" not in src, (
        "the mock still nests the snapshot under `data.state`; the store reads it flat"
    )
    assert "state_version: mockState.snapshot_version" not in src, (
        "the mock still returns the removed `state_version` field"
    )
    assert re.search(r"^\s*data: mockState,\s*$", src, re.M), (
        "the mock must return the serialized state flat, as Core does"
    )
    assert "snapshot_version: mockState.snapshot_version," in src
    assert "revisions: {" in src, "the mock must return a revision vector"


def test_dev_mock_shape_matches_what_the_store_reads():
    """The store treats `result.data` as the RuntimeState itself."""
    store = (UI / "stores" / "runtime.ts").read_text(encoding="utf-8")
    assert "as unknown) as WireState" in store, (
        "the store must read `data` directly as the state"
    )
    assert "as any).state" not in store, (
        "the store must not read a nested `data.state`"
    )
    mock = (UI / "bridge" / "tauri-bridge.ts").read_text(encoding="utf-8")
    assert "data: mockState," in mock