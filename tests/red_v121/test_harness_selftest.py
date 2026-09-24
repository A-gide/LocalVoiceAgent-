"""Harness self-test (PR-022 acceptance: "harness 自测").

These tests verify the harness itself and are expected to stay GREEN. They prove
that failure artifacts are redacted and that the fakes behave deterministically,
so a RED result in a sibling file is attributable to the product, not the rig.
"""
from __future__ import annotations

import json

import pytest

from harness import (
    ArtifactWriter,
    DeterministicClock,
    EventRecorder,
    FakeProvider,
    FakeProviderSet,
    RevisionProbe,
    TurnProbe,
    assert_no_sensitive,
    conversation_bypasses,
    forbidden_endpoint_hits,
    route_call_map,
)

pytestmark = pytest.mark.red_v121


def test_clock_is_deterministic():
    a, b = DeterministicClock(), DeterministicClock()
    assert a.now() == b.now()
    a.advance(500)
    assert (a.now() - b.now()).total_seconds() == pytest.approx(0.5 + 0.001, abs=0.01)


def test_recorder_captures_in_order():
    rec = EventRecorder()
    rec({"type": "a", "sequence": 1})
    rec({"type": "b", "sequence": 2})
    assert rec.types() == ["a", "b"]
    assert rec.sequences() == [1, 2]
    assert len(rec.by_type("b")) == 1


def test_provider_counters_and_crash_injection():
    p = FakeProvider("fake", "llm")
    assert list(p.stream([])) == ["fake ", "reply"]
    assert p.calls == 1

    p.fail_with = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        list(p.stream([]))
    assert p.calls == 2


def test_provider_set_reset():
    ps = FakeProviderSet()
    list(ps.llm.stream([]))
    ps.tts.synthesize("hi")
    assert (ps.llm.calls, ps.tts.calls) == (1, 1)
    ps.reset()
    assert (ps.llm.calls, ps.tts.calls) == (0, 0)


def test_artifact_writer_scrubs_secrets_and_paths(tmp_path):
    w = ArtifactWriter(tmp_path)
    payload = {
        "token": "sk-abcdefghijklmnopqrstuvwxyz012345",
        "endpoint": "http://127.0.0.1:49152/api/command",
        "home": r"C:\Users\alice\AppData\Local\VoiceAgent",
        "dpapi": "dpapi:AQAAANCMnd8BFdERjHoAwE/Cl+sBAAAA",
        "transcript": "user said something private",
    }
    path = w.write("failure.json", payload)
    text = path.read_text(encoding="utf-8")
    parsed = json.loads(text)

    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in text
    assert "dpapi:AQAAANCMnd8BFdERjHoAwE" not in text
    assert r"C:\Users\alice" not in text
    assert parsed["transcript"] == "[REDACTED]"
    assert_no_sensitive(text)


def test_assert_no_sensitive_catches_leaks():
    with pytest.raises(AssertionError):
        assert_no_sensitive("token=sk-abcdefghijklmnopqrstuvwxyz")
    with pytest.raises(AssertionError):
        assert_no_sensitive(r"path=C:\Users\bob\secret.txt")
    assert_no_sensitive("nothing sensitive here")


def test_i21_probe_detects_direct_hub_management_endpoint():
    endpoint = "/api/models/load"
    assert forbidden_endpoint_hits(f'fetch("{endpoint}")', [endpoint]) == [endpoint]
    assert forbidden_endpoint_hits('execute_command("hub.switch")', [endpoint]) == []


def test_i22_probe_detects_route_bypass_but_not_dispatch():
    bypass = '''
@router.post("/ask")
async def ask():
    await provider.stream([])
'''
    dispatched = '''
@router.post("/ask")
async def ask():
    await runtime.execute_command(command)
'''
    assert conversation_bypasses(bypass, {"stream", "append_event"}) == [
        "ask() calls ['stream']"
    ]
    assert conversation_bypasses(dispatched, {"stream", "append_event"}) == []
    assert "execute_command" in route_call_map(dispatched)["ask"]


# ------------------------------------------------- late turn / fault (I01/I02/I12)
def test_turn_probe_reproduces_a_late_turn():
    """A superseded turn must fail every gate on the production path (I01)."""
    probe = TurnProbe()

    # Positive: the live turn passes all three gates.
    fresh_turn, fresh_epoch = probe.start_turn("still current")
    assert probe.gates_pass(fresh_turn, fresh_epoch) == (True, True, True)

    # Negative: after a real interrupt the same turn is stale everywhere.
    stale_turn, stale_epoch = probe.start_turn("about to be superseded")
    assert probe.interrupt("barge_in") == stale_epoch + 1
    assert probe.gates_pass(stale_turn, stale_epoch) == (False, False, False)
    assert probe.controller.stale_gate.stale_dropped_count >= 3


def test_turn_probe_reproduces_a_fault_and_keeps_the_journal_intact():
    """Crash injection must raise, cancel the turn, and leave the Journal sound."""
    probe = TurnProbe()
    probe.start_turn("turn that will crash")

    # Positive control: a healthy stream raises nothing.
    assert probe.stream_with_fault(RuntimeError("unused"))[0] is True
    probe.providers.reset()
    assert list(probe.providers.llm.stream([])) == ["fake ", "reply"]
    probe.providers.reset()

    # Negative: the injected fault surfaces and is recovered the way Core does.
    turn, _ = probe.start_turn("crash here")
    raised, exc_type = probe.stream_with_fault(ConnectionResetError("provider died"))
    assert raised is True
    assert exc_type == "ConnectionResetError"
    assert probe.providers.llm.calls == 1
    assert probe.controller.turn_controller.current_turn is None
    assert probe.controller.session_controller.current_session_id is not None
    assert probe.journal_integrity() == "ok"

    # The session survives: the next turn continues on it.
    next_turn, _ = probe.start_turn("retry after crash")
    assert next_turn.sequence == turn.sequence + 1


# ------------------------------------------- aggregate CAS / heartbeat (4.2/4.4)
def test_revision_probe_separates_heartbeat_traffic_from_a_mode_conflict():
    """Heartbeat must not invalidate a pending command, but a stale one must fail."""
    probe = RevisionProbe()
    control = probe.revision("runtime_control")
    snapshot = probe.snapshot_version()

    # Real heartbeat traffic: activity publishes, not commands.
    probe.heartbeat("speaking")
    probe.heartbeat("listening")

    assert probe.revision("runtime_control") == control, (
        "heartbeat traffic must not bump runtime_control_revision"
    )
    assert probe.snapshot_version() > snapshot, (
        "a published-state change must still bump snapshot_version"
    )

    # Positive: the command captured before the heartbeat is still applicable.
    applied = probe.set_mode("live", revision=control)
    assert applied.status == "applied", f"heartbeat made a valid command stale: {applied.status}"
    assert probe.revision("runtime_control") == control + 1

    # Negative control: a genuinely stale revision must be rejected, so the
    # positive assertion above cannot pass vacuously.
    rejected = probe.set_mode("standby", revision=control)
    assert rejected.status == "rejected"
    assert rejected.error is not None
    assert rejected.error.code.value == "STALE_REVISION"
    assert rejected.error.redacted_details.get("aggregate") == "runtime_control"
    assert probe.revision("runtime_control") == control + 1, (
        "a rejected command must leave the aggregate revision untouched"
    )


def test_revision_probe_detects_a_missing_precondition():
    """The probe must observe a CAS rejection when no precondition is sent."""
    probe = RevisionProbe()
    result = probe.set_mode_without_precondition("live")
    assert result.status == "rejected"
    assert result.error is not None
    assert result.error.code.value == "STALE_REVISION"
