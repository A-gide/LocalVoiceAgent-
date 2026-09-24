"""RED: v1.2.1 snapshot DTO consistency (feeds R08).

Frozen rule (v1.2.1 §8.1 + PR-008):
* Core, the Rust bridge, the Vue store and the dev mock must agree on ONE
  snapshot shape.
* The mock must not invent a special structure.

Current state: Core returns ``data = <state dict>`` while the store reads
``data.state`` and the mock returns ``data = {state: ...}`` - a real mismatch.
"""
from __future__ import annotations

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

STORE = REPO_ROOT / "apps" / "desktop-ui" / "src" / "stores" / "runtime.ts"
BRIDGE = REPO_ROOT / "apps" / "desktop-ui" / "src" / "bridge" / "tauri-bridge.ts"


def _snapshot_data_from_core() -> dict:
    from lva.contracts.commands import CommandEnvelope, RuntimeGetSnapshotPayload
    from lva.core.runtime import RuntimeController

    rt = RuntimeController()
    cmd = CommandEnvelope(type="runtime.get_snapshot", payload=RuntimeGetSnapshotPayload(type="runtime.get_snapshot"))
    res = rt.execute_command(cmd)
    assert res.status == "applied", f"get_snapshot must apply, got {res.status}"
    return res.data


def test_core_snapshot_data_is_the_state_itself():
    data = _snapshot_data_from_core()
    assert isinstance(data, dict)
    assert "runtime_instance_id" in data, (
        "Core snapshot payload must expose the runtime state directly; "
        f"got keys: {sorted(data)[:8]}"
    )


def test_store_reads_snapshot_without_extra_wrapper():
    src = read_text(STORE)
    assert "(result.data as any).state" not in src, (
        "stores/runtime.ts unwraps `result.data.state`, but Core returns the state "
        "as `data` directly - the two sides disagree on the snapshot DTO"
    )
    assert "result.data as RuntimeState" in src, (
        "stores/runtime.ts must consume `result.data` as RuntimeState directly"
    )


def test_mock_does_not_invent_a_special_snapshot_shape():
    src = read_text(BRIDGE)
    assert "data: { state: mockState }" not in src, (
        "the dev mock wraps the snapshot in {state: ...}; per v1.2.1 §8.1 the mock "
        "must expose exactly the same shape as the real Core"
    )