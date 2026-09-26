"""Regression tests for the R03b review blockers.

Behavioural where the artefact is executable; where it is not (TypeScript
running in a WebView), the source assertion is paired with a behavioural test
of the *envelope shape* against the real Core so the two cannot drift apart.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
from uuid import uuid4

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from lva.contracts import codegen  # noqa: E402
from lva.contracts.commands import (  # noqa: E402
    CommandEnvelope,
    HubBindModelPayload,
    RuntimeGetSnapshotPayload,
    RuntimeRestoreModePayload,
    RuntimeSetModePayload,
)
from lva.contracts.enums import ErrorCode  # noqa: E402
from lva.contracts.state import RuntimeState  # noqa: E402
from lva.core.runtime import RuntimeController  # noqa: E402

UI = REPO / "apps" / "desktop-ui" / "src"


def _git(*args: str) -> subprocess.CompletedProcess:
    repo = REPO.resolve()
    return subprocess.run(
        ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )


# ============================================================ blocker 1
# The frontend cannot be executed here, so the source assertion is kept but is
# paired with behavioural tests of the envelope it produces.
def test_bridge_envelope_uses_precondition_not_the_removed_field():
    src = (UI / "bridge" / "tauri-bridge.ts").read_text(encoding="utf-8")
    assert "expected_state_version" not in src
    assert re.search(r"precondition:\s*precondition\s*\?\?\s*null", src)


def test_every_cas_command_type_has_a_precondition_somewhere_in_the_ui():
    """Each CAS command the UI issues must be given a concrete aggregate."""
    required = {
        "runtime.set_mode": "runtime_control",
        "runtime.restore_mode": "runtime_control",
        "hub.bind_model": "hub_binding",
        "hub.sleep_bound_model": "hub_binding",
        "memory.correct": "memory_event",
        "memory.hard_delete": "memory_event",
    }
    blob = "\n".join(
        p.read_text(encoding="utf-8") for p in UI.rglob("*.ts")
    ) + "\n".join(p.read_text(encoding="utf-8") for p in UI.rglob("*.vue"))
    for command, aggregate in required.items():
        assert command in blob, f"{command} is never issued by the UI"
        assert f"aggregate: '{aggregate}'" in blob, (
            f"no caller passes a '{aggregate}' precondition for {command}"
        )


def test_core_accepts_the_envelope_shape_the_bridge_builds():
    """Behavioural counterpart: the exact envelope shape must actually apply."""
    rt = RuntimeController(runtime_instance_id=uuid4())
    result = rt.execute_command(
        CommandEnvelope(
            type="runtime.set_mode",
            precondition={
                "aggregate": "runtime_control",
                "revision": rt.runtime_control_revision,
            },
            payload=RuntimeSetModePayload(type="runtime.set_mode", mode="live"),
        )
    )
    assert result.status == "applied"


def test_two_consecutive_mode_commands_both_apply():
    """The store must adopt the returned revision, or the second call is stale.

    This mirrors the frontend: it sends `runtime_control_revision`, then folds
    the returned `revisions` back into its state before the next command.
    """
    rt = RuntimeController(runtime_instance_id=uuid4())
    revision = rt.runtime_control_revision

    first = rt.execute_command(
        CommandEnvelope(
            type="runtime.set_mode",
            precondition={"aggregate": "runtime_control", "revision": revision},
            payload=RuntimeSetModePayload(type="runtime.set_mode", mode="live"),
        )
    )
    assert first.status == "applied"
    # what applyResult() does with the result
    revision = first.revisions["runtime_control"]
    assert revision == 1

    second = rt.execute_command(
        CommandEnvelope(
            type="runtime.set_mode",
            precondition={"aggregate": "runtime_control", "revision": revision},
            payload=RuntimeSetModePayload(type="runtime.set_mode", mode="passive"),
        )
    )
    assert second.status == "applied", (
        "a second command using the returned revision must apply; "
        "a store that only tracks snapshot_version re-sends a stale revision"
    )
    assert second.revisions["runtime_control"] == 2
    assert rt.mode.value == "passive"


def test_frontend_store_adopts_the_returned_revision_vector():
    src = (UI / "stores" / "runtime.ts").read_text(encoding="utf-8")
    assert "result.revisions" in src, (
        "the store never reads the returned revision vector"
    )
    assert re.search(r"runtime_control_revision\s*=", src), (
        "the store never updates runtime_control_revision"
    )


def test_setmode_delegates_its_decision_to_the_reconciler():
    """The rollback/recovery decision must live in the executable reconciler.

    `modeTransition.js` is exercised for real in
    `test_mode_transition_recovery.py`; here we only assert the store routes
    through it instead of deciding inline.
    """
    src = (UI / "stores" / "runtime.ts").read_text(encoding="utf-8")
    body = src[src.index("async function setMode("):]
    body = body[: body.index("\n  async function ")]
    assert "reconcileSetMode(" in body, (
        "setMode must delegate the rollback decision to the reconciler"
    )
    assert "await fetchSnapshotState()" in body, (
        "setMode must read the authoritative snapshot before deciding"
    )
    assert "state.value.mode = prevMode" not in body, (
        "setMode must not roll back on its own; the reconciler owns that decision"
    )


def test_settings_cas_calls_adopt_the_returned_revision():
    src = (UI / "stores" / "settings.ts").read_text(encoding="utf-8")
    assert src.count("runtime.applyResult(res)") >= 2, (
        "bindHubModel and sleepBoundModel must both adopt the returned revisions"
    )


def test_runtime_store_exposes_applyResult():
    src = (UI / "stores" / "runtime.ts").read_text(encoding="utf-8")
    assert re.search(r"^\s*applyResult,\s*$", src, re.M), (
        "applyResult must be returned from the runtime store"
    )


def test_conflict_recovery_reads_the_flat_snapshot_shape():
    """Core returns `data` flat; `data.state` is undefined."""
    rt = RuntimeController(runtime_instance_id=uuid4())
    result = rt.execute_command(
        CommandEnvelope(
            type="runtime.get_snapshot",
            payload=RuntimeGetSnapshotPayload(type="runtime.get_snapshot"),
        )
    )
    assert result.status == "applied"
    assert "state" not in result.data, "Core must not nest the snapshot under `state`"
    # the flat payload must be a valid RuntimeState
    RuntimeState.model_validate(result.data)

    src = (UI / "stores" / "runtime.ts").read_text(encoding="utf-8")
    assert "as any).state" not in src, (
        "the store still reads `result.data.state`, which is always undefined"
    )


def test_recovery_after_a_stale_conflict_succeeds():
    """A stale command is rejected, then a refreshed revision applies."""
    rt = RuntimeController(runtime_instance_id=uuid4())
    rt.execute_command(
        CommandEnvelope(
            type="runtime.set_mode",
            precondition={"aggregate": "runtime_control", "revision": 0},
            payload=RuntimeSetModePayload(type="runtime.set_mode", mode="live"),
        )
    )

    stale = rt.execute_command(
        CommandEnvelope(
            type="runtime.set_mode",
            precondition={"aggregate": "runtime_control", "revision": 0},
            payload=RuntimeSetModePayload(type="runtime.set_mode", mode="passive"),
        )
    )
    assert stale.status == "rejected"
    assert stale.error.code is ErrorCode.STALE_REVISION

    snap = rt.execute_command(
        CommandEnvelope(
            type="runtime.get_snapshot",
            payload=RuntimeGetSnapshotPayload(type="runtime.get_snapshot"),
        )
    )
    fresh = RuntimeState.model_validate(snap.data).runtime_control_revision

    retry = rt.execute_command(
        CommandEnvelope(
            type="runtime.set_mode",
            precondition={"aggregate": "runtime_control", "revision": fresh},
            payload=RuntimeSetModePayload(type="runtime.set_mode", mode="passive"),
        )
    )
    assert retry.status == "applied"


def test_soak_sends_a_precondition_and_counts_rejections():
    src = (REPO / "scripts" / "soak.py").read_text(encoding="utf-8")
    assert '"aggregate": "runtime_control"' in src
    assert 'if mode_result.status == "applied":' in src
    assert "self.rejected_commands += 1" in src


def test_codegen_verify_reads_the_target_files(tmp_path, monkeypatch):
    monkeypatch.setattr(codegen, "SCHEMA_PATH", tmp_path / "missing-schema.json")
    monkeypatch.setattr(codegen, "TS_PATH", tmp_path / "missing.ts")
    monkeypatch.setattr(codegen, "RS_PATH", tmp_path / "missing.rs")
    with pytest.raises(codegen.CodegenError, match="stale"):
        codegen.run_codegen(verify_only=True)


def test_codegen_verify_detects_a_tampered_artifact(tmp_path, monkeypatch):
    """Isolated: every target is redirected, so no real artifact is touched."""
    monkeypatch.setattr(codegen, "SCHEMA_PATH", tmp_path / "s.json")
    monkeypatch.setattr(codegen, "TS_PATH", tmp_path / "t.ts")
    monkeypatch.setattr(codegen, "RS_PATH", tmp_path / "r.rs")

    real = {
        "schema": codegen.SCHEMA_PATH,
        "ts": codegen.TS_PATH,
        "rs": codegen.RS_PATH,
    }
    before = {k: p.read_bytes() for k, p in
              (("schema", REPO / "schemas" / "lva-ipc-v1.json"),
               ("ts", REPO / "apps/desktop-ui/src/generated/lva-ipc.ts"),
               ("rs", REPO / "apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs"))}

    codegen.run_codegen()  # writes into tmp_path only
    (tmp_path / "r.rs").write_text("// tampered\n", encoding="utf-8")
    with pytest.raises(codegen.CodegenError, match="stale"):
        codegen.run_codegen(verify_only=True)

    after = {k: p.read_bytes() for k, p in
             (("schema", REPO / "schemas" / "lva-ipc-v1.json"),
              ("ts", REPO / "apps/desktop-ui/src/generated/lva-ipc.ts"),
              ("rs", REPO / "apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs"))}
    assert before == after, "the tamper test must not rewrite the committed artifacts"


def test_codegen_verify_passes_on_a_clean_tree():
    codegen.run_codegen(verify_only=True)


# ============================================================ blocker 3
def test_generator_sources_are_not_gitignored():
    for rel in (
        "tools/codegen-rust/Cargo.toml",
        "tools/codegen-rust/Cargo.lock",
        "tools/codegen-rust/src/main.rs",
        "apps/desktop-ui/tools/generate-ipc.mjs",
    ):
        proc = _git("check-ignore", "--", rel)
        assert proc.returncode != 0, f"{rel} is still ignored and cannot ship"


def test_generator_build_output_stays_ignored():
    proc = _git("check-ignore", "--", "tools/codegen-rust/target/release/lva-codegen-rust.exe")
    assert proc.returncode == 0


# ============================================================ blocker 4
def test_duplicate_command_carries_the_first_revision_mapping():
    rt = RuntimeController(runtime_instance_id=uuid4())
    # PR-012: hub.bind_model now also requires a fresh VERIFIED_LOOPBACK bind
    # attestation (plan L665).  Grant one so this test keeps measuring the
    # duplicate/revision behaviour it is named for.
    from datetime import datetime, timedelta, timezone

    from lva.contracts.state import HubBindAttestation

    _now = datetime.now(timezone.utc)
    rt.set_hub_bind_attestation(
        HubBindAttestation(
            status="VERIFIED_LOOPBACK",
            reason_code=None,
            checked_at=_now,
            attestation_id="dup-test-loopback",
            revalidate_after=_now + timedelta(minutes=5),
        )
    )

    def envelope():
        return CommandEnvelope(
            type="hub.bind_model",
            idempotency_key="dup-key-1",
            precondition={"aggregate": "hub_binding", "revision": rt.hub_binding_revision},
            payload=HubBindModelPayload(type="hub.bind_model", model_id="m1"),
        )

    first = rt.execute_command(envelope())
    assert first.status == "applied"
    assert first.revisions == {"hub_binding": 1}

    duplicate = rt.execute_command(envelope())
    assert duplicate.status == "duplicate"
    assert duplicate.revisions == first.revisions


# ============================================================ spec boundary
def test_python_core_does_not_own_a_settings_cas():
    """Spec §3.4: settings CAS is not the Python Core's responsibility."""
    rt = RuntimeController(runtime_instance_id=uuid4())
    assert not hasattr(rt, "_settings_revision"), (
        "the Python Core must not keep a private settings revision"
    )
    assert "settings" not in rt.CAS_REQUIRED_AGGREGATE.values(), (
        "settings commands must not be forced through the Core CAS matrix"
    )
    assert "settings" not in rt._revision_vector(), (
        "the Core must not report a settings aggregate revision"
    )


def test_settings_commands_are_not_gated_by_a_core_precondition():
    """A settings command without a precondition must not be rejected by CAS."""
    rt = RuntimeController(runtime_instance_id=uuid4())
    result = rt.execute_command(
        CommandEnvelope(
            type="settings.update_public",
            payload={"type": "settings.update_public", "autostart": True},
        )
    )
    assert result.error is None or result.error.code is not ErrorCode.STALE_REVISION
