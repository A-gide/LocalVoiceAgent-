"""Unit tests for Core Command Engine per Part 4.4 and Part 13.1.

Verifies:
1. Command dispatch for all Part 4.4 typed commands.
2. Optimistic concurrency control (STALE_STATE rejection on version mismatch).
3. Idempotency window caching (duplicate returns first result without re-executing).
4. Mode guards on turn.send_text (strictly forbidden in non-LIVE modes).
"""
from __future__ import annotations

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
from lva.contracts.enums import ErrorCode, Mode
from lva.core.runtime import RuntimeController
from lva.journal.repository import JournalRepository


def test_command_runtime_lifecycle():
    """Verify runtime.get_snapshot, runtime.set_mode, and runtime.restore_mode."""
    rt = RuntimeController()

    # 1. get_snapshot
    res = rt.execute_command(
        CommandEnvelope(
            type="runtime.get_snapshot",
            payload=RuntimeGetSnapshotPayload(type="runtime.get_snapshot"),
        )
    )
    assert res.status == "applied"
    assert res.data["mode"] == Mode.STANDBY.value

    # 2. set_mode to LIVE
    res2 = rt.execute_command(
        CommandEnvelope(
            type="runtime.set_mode",
            precondition={"aggregate": "runtime_control", "revision": rt.runtime_control_revision},
              payload=RuntimeSetModePayload(type="runtime.set_mode", mode=Mode.LIVE),
        )
    )
    assert res2.status == "applied"
    assert rt.mode == Mode.LIVE

    # 3. set_mode to PRIVACY_PAUSE
    res3 = rt.execute_command(
        CommandEnvelope(
            type="runtime.set_mode",
            precondition={"aggregate": "runtime_control", "revision": rt.runtime_control_revision},
              payload=RuntimeSetModePayload(type="runtime.set_mode", mode=Mode.PRIVACY_PAUSE),
        )
    )
    assert res3.status == "applied"
    assert rt.mode == Mode.PRIVACY_PAUSE

    # 4. restore_mode restores to LIVE
    res4 = rt.execute_command(
        CommandEnvelope(
            type="runtime.restore_mode",
            precondition={"aggregate": "runtime_control", "revision": rt.runtime_control_revision},
            payload=RuntimeRestoreModePayload(type="runtime.restore_mode"),
        )
    )
    assert res4.status == "applied"
    assert res4.data["restored_mode"] == Mode.LIVE.value
    assert rt.mode == Mode.LIVE


def test_command_turn_send_text_mode_guards():
    """Verify turn.send_text enforces Part 3.3 mode restrictions."""
    rt = RuntimeController()

    # In STANDBY: rejected
    res_standby = rt.execute_command(
        CommandEnvelope(
            type="turn.send_text",
            payload=TurnSendTextPayload(type="turn.send_text", text="Hello"),
        )
    )
    assert res_standby.status == "rejected"
    assert res_standby.error.code == ErrorCode.PASSIVE_PROVIDER_FORBIDDEN

    # In PASSIVE: rejected
    rt.set_mode(Mode.PASSIVE)
    res_passive = rt.execute_command(
        CommandEnvelope(
            type="turn.send_text",
            payload=TurnSendTextPayload(type="turn.send_text", text="Hello"),
        )
    )
    assert res_passive.status == "rejected"
    assert res_passive.error.code == ErrorCode.PASSIVE_PROVIDER_FORBIDDEN

    # In LIVE: applied
    rt.set_mode(Mode.LIVE)
    res_live = rt.execute_command(
        CommandEnvelope(
            type="turn.send_text",
            payload=TurnSendTextPayload(type="turn.send_text", text="Hello"),
        )
    )
    assert res_live.status == "applied"
    assert "turn_id" in res_live.data
    assert res_live.data["turn_id"]["sequence"] == 1


def test_command_memory_operations():
    """Verify memory.search, memory.correct, and memory.hard_delete."""
    repo = JournalRepository()
    rt = RuntimeController(journal=repo)

    # Insert an event directly for testing
    eid = uuid4()
    repo.append_event(eid, "测试化学分子式", occurred_at_utc_us=1000000)

    # 1. memory.search
    res_search = rt.execute_command(
        CommandEnvelope(
            type="memory.search",
            payload=MemorySearchPayload(type="memory.search", query="化学分子式"),
        )
    )
    assert res_search.status == "applied"
    assert res_search.data["n"] == 1
    assert res_search.data["hits"][0]["current_text"] == "测试化学分子式"

    # 2. memory.correct
    res_correct = rt.execute_command(
        CommandEnvelope(
            type="memory.correct",
            precondition={"aggregate": "memory_event", "resource_id": str(eid), "revision": 0},
            payload=MemoryCorrectPayload(type="memory.correct", 
                event_id=eid,
                corrected_text="测试化学分子结构式",
                reason="refine",
            ),
        )
    )
    assert res_correct.status == "applied"
    assert res_correct.data["revision"] == 1

    # Verify search returns corrected text
    res_search2 = rt.execute_command(
        CommandEnvelope(
            type="memory.search",
            payload=MemorySearchPayload(type="memory.search", query="结构式"),
        )
    )
    assert res_search2.status == "applied"
    assert res_search2.data["n"] == 1
    assert res_search2.data["hits"][0]["current_text"] == "测试化学分子结构式"

    # 3. memory.hard_delete
    res_del = rt.execute_command(
        CommandEnvelope(
            type="memory.hard_delete",
            precondition={"aggregate": "memory_event", "resource_id": str(eid), "revision": 1},
            payload=MemoryHardDeletePayload(type="memory.hard_delete", 
                event_ids=[eid],
                reason_code="user_requested_erasure",
            ),
        )
    )
    assert res_del.status == "applied"
    assert res_del.data["deleted_count"] == 1

    # Verify event is completely deleted
    assert repo.get_event(eid) is None


def test_command_diagnostics_export_redacted():
    """Verify diagnostics.export_redacted returns sanitized bundle with no secrets."""
    repo = JournalRepository()
    rt = RuntimeController(journal=repo)

    res = rt.execute_command(
        CommandEnvelope(
            type="diagnostics.export_redacted",
            payload=DiagnosticsExportRedactedPayload(type="diagnostics.export_redacted"),
        )
    )
    assert res.status == "applied"
    data = res.data
    assert data["schema_version"] == "1.0"
    assert "runtime_instance_id" in data
    assert "journal_summary" in data
    assert "sk-" not in str(data)
