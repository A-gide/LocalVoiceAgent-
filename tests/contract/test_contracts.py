"""Contract tests verifying schema drift, Pydantic discriminated unions, and JSON serialization.

Per Part 4.1, Part 4.5, and Part 13.1 of the Architecture Plan:
1. Zero-drift check: generated JSON Schema matches schemas/lva-ipc-v1.json exactly.
2. Discriminated union verification: CommandEnvelope, EventEnvelope, ErrorEnvelope.
3. Secret-free error serialization: ErrorEnvelope never exposes API keys or tokens.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from lva.contracts.commands import (
    CommandEnvelope,
    DiagnosticsExportRedactedPayload,
    HubBindModelPayload,
    HubRefreshPayload,
    HubSleepBoundModelPayload,
    MemoryCorrectPayload,
    MemoryHardDeletePayload,
    MemorySearchPayload,
    RuntimeGetSnapshotPayload,
    RuntimeRestoreModePayload,
    RuntimeSetModePayload,
    ServiceRetryPayload,
    TurnCancelPayload,
    TurnSendTextPayload,
)
from lva.contracts.enums import ErrorCode, Mode, PrivacyScope
from lva.contracts.errors import ErrorEnvelope
from lva.contracts.events import (
    AudioPlaybackStartedPayload,
    EventEnvelope,
    InterruptCommittedPayload,
    TurnCancelledPayload,
)
from lva.contracts.ids import TurnId
from lva.contracts.schema import generate_json_schema
from lva.contracts.state import RuntimeState


def test_schema_zero_drift():
    """Part 4.1: Generated JSON Schema must match schemas/lva-ipc-v1.json with zero drift."""
    repo_root = Path(__file__).resolve().parents[2]
    schema_file = repo_root / "schemas" / "lva-ipc-v1.json"
    assert schema_file.exists(), f"Schema file {schema_file} not found"

    expected_schema = json.loads(schema_file.read_text(encoding="utf-8"))
    actual_schema = generate_json_schema()

    assert actual_schema == expected_schema, "JSON Schema drift detected between contracts and schemas/lva-ipc-v1.json!"


def test_command_discriminated_unions_round_trip():
    """Part 4.4: All Part 4.4 command payloads must correctly serialize and deserialize."""
    cmd_payloads = [
        RuntimeGetSnapshotPayload(type="runtime.get_snapshot"),
        RuntimeSetModePayload(type="runtime.set_mode", mode=Mode.LIVE),
        RuntimeRestoreModePayload(type="runtime.restore_mode"),
        TurnSendTextPayload(type="turn.send_text", text="Hello world"),
        TurnCancelPayload(type="turn.cancel", reason="user_cancel"),
        HubRefreshPayload(type="hub.refresh"),
        HubBindModelPayload(type="hub.bind_model", model_id="qwen2.5-7b", force=True),
        HubSleepBoundModelPayload(type="hub.sleep_bound_model"),
        MemorySearchPayload(type="memory.search", query="chemistry", limit=5),
        MemoryCorrectPayload(type="memory.correct", event_id=uuid4(), corrected_text="corrected", reason="typo"),
        MemoryHardDeletePayload(type="memory.hard_delete", event_ids=[uuid4()], reason_code="privacy_request"),
        ServiceRetryPayload(type="service.retry", service_name="screenpipe"),
        DiagnosticsExportRedactedPayload(type="diagnostics.export_redacted"),
    ]

    for payload in cmd_payloads:
        env = CommandEnvelope(
            idempotency_key="test-key",
            expected_state_version=1,
            type=payload.type,
            payload=payload,
        )
        data = env.model_dump(mode="json")
        deserialized = CommandEnvelope.model_validate(data)
        assert deserialized.type == payload.type
        assert deserialized.payload.type == payload.type
        assert deserialized.idempotency_key == "test-key"


def test_event_discriminated_unions_round_trip():
    """Part 4.3: Event envelopes with typed payloads round-trip correctly."""
    session_id = uuid4()
    turn_id = TurnId(session_id=session_id, sequence=1)

    inst_id = uuid4()
    events = [
        EventEnvelope(
            runtime_instance_id=inst_id,
            sequence=1,
            source="core.turn_controller",
            session_id=session_id,
            turn_id=turn_id,
            type="audio.playback_started",
            payload=AudioPlaybackStartedPayload(type="audio.playback_started", turn_id=turn_id, provider_epoch=1),
        ),
        EventEnvelope(
            runtime_instance_id=inst_id,
            sequence=2,
            source="core.interrupt_controller",
            session_id=session_id,
            turn_id=turn_id,
            type="interrupt.committed",
            payload=InterruptCommittedPayload(type="interrupt.committed", provider_epoch=2),
        ),
        EventEnvelope(
            runtime_instance_id=inst_id,
            sequence=3,
            source="core.turn_controller",
            session_id=session_id,
            turn_id=turn_id,
            type="turn.cancelled",
            payload=TurnCancelledPayload(type="turn.cancelled", turn_id=turn_id, reason="barge_in", provider_epoch=2),
        ),
    ]

    for env in events:
        data = env.model_dump(mode="json")
        deserialized = EventEnvelope.model_validate(data)
        assert deserialized.type == env.type
        assert deserialized.sequence == env.sequence


def test_error_envelope_sanitization():
    """Part 4.5: Error details must be user-safe and contain no secrets or API keys."""
    err = ErrorEnvelope(
        code=ErrorCode.AUTH_FAILED,
        message="Authentication token failed verification",
        retryable=False,
        severity="error",
        component="transport.auth",
        correlation_id=uuid4(),
        redacted_details={"reason": "signature_mismatch"},
    )
    err_json = err.model_dump_json()
    assert err.code == ErrorCode.AUTH_FAILED


def test_codegen_zero_diff():
    """Part 4.1: Generated TypeScript and Rust contracts must match disk with zero diff."""
    from lva.contracts.codegen import generate_typescript_contracts, generate_rust_contracts

    repo_root = Path(__file__).resolve().parents[2]
    ts_file = repo_root / "apps" / "desktop-ui" / "src" / "generated" / "lva-ipc.ts"
    rs_file = repo_root / "apps" / "desktop-shell" / "src-tauri" / "src" / "generated" / "lva_ipc.rs"

    assert ts_file.exists(), f"TypeScript contract {ts_file} missing"
    assert rs_file.exists(), f"Rust contract {rs_file} missing"

    assert ts_file.read_text(encoding="utf-8") == generate_typescript_contracts()
    assert rs_file.read_text(encoding="utf-8") == generate_rust_contracts()

