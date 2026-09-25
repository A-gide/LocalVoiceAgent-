"""RED: PR-020 privacy capture coordinator (ack-driven privacy scope).

Frozen authority: plan L1330-1338.

* L1333 current -> target: stopping only the Core mic and then claiming a
  privacy pause must become an acknowledgement-driven privacy scope.
* L1335 steps: Core mic stop ack; Standby/Privacy Pause both send a
  managed-capture-off operation; aggregate verified/unverified; restore_mode
  memory-only; Live sends an intent per record_reality_during_live.
* L1337 acceptance: I09/I10/I19; Core mic physical frames stop; Standby leaves
  LVA-managed capture Off; on timeout the scope is unknown, not success.
* L1338 rollback rule: a return to false success is not allowed; when external
  control fails, degrade to Core-only and say so explicitly.

Section 3.3 gives the four modes their managed-capture column, and section 3.4
fixes the four legal privacy_scope values.

What the shipped code does today (verified before writing these assertions):

* CaptureCoordinator has no operation concept at all -- no id, no deadline, no
  timeout -- so VERIFIED can only ever be reached by a test calling
  update_managed_capture_status by hand;
* entering Privacy Pause sets managed_stopped=None but never *asks* anyone to
  stop LVA-managed capture, so no acknowledgement could ever arrive;
* entering Live ignores record_reality_during_live entirely;
* privacy.scope_changed exists in the contract but has zero producers, so a
  scope change is invisible to the shell and the UI.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from harness import DeterministicClock, EventRecorder
from lva.contracts.enums import Mode, PrivacyScope
from lva.core.capture import CaptureCoordinator
from lva.core.runtime import RuntimeController

pytestmark = pytest.mark.red_v121


def _clock() -> DeterministicClock:
    return DeterministicClock()


def _coordinator(clock: DeterministicClock | None = None) -> CaptureCoordinator:
    clock = clock or _clock()
    return CaptureCoordinator(now=clock.now)


# ------------------------------------------------------- operations with ids
def test_managed_capture_off_is_an_operation_not_a_bare_flag():
    """L1335: Standby/Privacy Pause send a *managed-capture-off operation*."""
    clock = _clock()
    c = _coordinator(clock)
    op = c.request_managed_capture_off()
    assert getattr(op, "operation_id", None), (
        "a managed-capture-off request must carry an operation id so the ack can "
        "be correlated (plan L1345: operation id ack)"
    )
    assert op.kind == "stop", f"expected a stop operation, got {op.kind!r}"
    assert op.deadline > op.requested_at, "an operation must have a deadline"
    assert op.status == "pending"

def test_privacy_pause_asks_for_managed_capture_off():
    """Today Privacy Pause only records unknown and never asks anyone."""
    clock = _clock()
    rt = RuntimeController(capture_now=clock.now)
    rt.set_mode(Mode.PRIVACY_PAUSE)
    pending = rt.capture_coordinator.pending_operations()
    assert pending, (
        "entering Privacy Pause must send a managed-capture-off operation; "
        "without a request no acknowledgement can ever arrive and the scope is "
        "stuck at unknown forever (plan L1335)"
    )
    assert any(op.kind == "stop" for op in pending)


def test_standby_asks_for_managed_capture_off():
    clock = _clock()
    rt = RuntimeController(capture_now=clock.now)
    rt.set_mode(Mode.STANDBY)
    assert any(op.kind == "stop" for op in rt.capture_coordinator.operations), (
        "plan L1335: Standby sends the managed-capture-off operation too"
    )


# ------------------------------------------------------------- ack and timeout
def test_timeout_yields_unknown_not_success():
    """L1337: on timeout the scope is unknown, never success. L1338: no false success."""
    clock = _clock()
    rt = RuntimeController(capture_now=clock.now)
    rt.set_mode(Mode.PRIVACY_PAUSE)
    clock.advance(60_000)
    rt.expire_capture_operations()
    scope = rt.get_state().privacy_scope
    assert scope == PrivacyScope.LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN, (
        "an unacknowledged managed-capture-off request must time out to UNKNOWN; "
        f"claiming success is the false-success failure mode (got {scope})"
    )


def test_acknowledgement_verifies_the_scope():
    clock = _clock()
    rt = RuntimeController(capture_now=clock.now)
    rt.set_mode(Mode.PRIVACY_PAUSE)
    op = rt.capture_coordinator.pending_operations()[0]
    assert rt.acknowledge_capture_operation(
        op.operation_id, managed_stopped=True, external_detected=False
    )
    assert rt.get_state().privacy_scope == PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF
    assert not rt.capture_coordinator.pending_operations(), (
        "an acknowledged operation must stop being pending"
    )

def test_ack_for_an_unknown_operation_is_refused():
    clock = _clock()
    rt = RuntimeController(capture_now=clock.now)
    rt.set_mode(Mode.PRIVACY_PAUSE)
    assert rt.acknowledge_capture_operation(
        "not-an-operation-id", managed_stopped=True, external_detected=False
    ) is False, (
        "an ack that matches no outstanding operation must not be able to move "
        "the privacy scope"
    )
    assert rt.get_state().privacy_scope != PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF


def test_verified_requires_the_stop_operation_to_be_settled():
    """A stale stopped flag must not outrank an outstanding request."""
    clock = _clock()
    c = _coordinator(clock)
    # The flag reads "stopped" -- but a fresh request is issued and unanswered,
    # so the flag alone must not be enough to claim a verified pause.
    c.update_managed_capture_status(managed_stopped=True, external_detected=False)
    op = c.request_managed_capture_off()
    assert c.compute_privacy_scope(Mode.PRIVACY_PAUSE) != (
        PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF
    ), (
        "an outstanding, unanswered stop request must hold the scope below "
        "verified even when the cached flag reads stopped"
    )
    clock.advance(60_000)
    c.expire_overdue()
    assert c.compute_privacy_scope(Mode.PRIVACY_PAUSE) != PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF, (
        "the re-issued request went unanswered, so the scope must fall back to "
        "unknown rather than trusting the older flag"
    )
    assert op.status == "timed_out"


# ------------------------------------------------------ live/passive intents
def test_live_honours_the_reality_recording_setting():
    """L1335: Live sends an intent per record_reality_during_live (3.3)."""
    clock = _clock()
    rt = RuntimeController(capture_now=clock.now)
    rt.set_record_reality_during_live(True)
    rt.set_mode(Mode.LIVE)
    assert any(op.kind == "resume" for op in rt.capture_coordinator.operations), (
        "with reality recording enabled, entering Live must ask for LVA-managed "
        "capture to be running"
    )


def test_live_defaults_to_no_managed_reality_recording():
    """First install default is Off (3.3): Live must not start managed capture."""
    clock = _clock()
    rt = RuntimeController(capture_now=clock.now)
    assert rt.record_reality_during_live is False
    rt.set_mode(Mode.LIVE)
    last = rt.capture_coordinator.last_operation()
    assert last is not None and last.kind == "stop", (
        "with the setting Off, entering Live must ask LVA-managed capture to stay "
        f"off; last operation was {last!r}"
    )


def test_passive_turns_managed_capture_on():
    """3.3: entering Passive *is* the recording act, so managed capture is On."""
    clock = _clock()
    rt = RuntimeController(capture_now=clock.now)
    rt.set_mode(Mode.PASSIVE)
    assert any(op.kind == "resume" for op in rt.capture_coordinator.operations), (
        "entering Passive is an explicit recording action; managed capture must be "
        "asked to run"
    )

# ----------------------------------------------------------- scope events/reasons
def test_scope_change_is_emitted():
    """privacy.scope_changed has no producer today (section 4.3)."""
    recorder = EventRecorder()
    clock = _clock()
    rt = RuntimeController(event_broadcaster=recorder, capture_now=clock.now)
    rt.set_mode(Mode.PRIVACY_PAUSE)
    changes = recorder.by_type("privacy.scope_changed")
    assert changes, (
        "entering Privacy Pause changes the privacy scope; the shell and UI can "
        "only see that through a privacy.scope_changed event"
    )
    payload = changes[-1].payload
    assert payload.previous_scope == PrivacyScope.NOT_PAUSED
    assert payload.new_scope == PrivacyScope.LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN
    assert payload.unverified_reasons, (
        "3.4: a non-verified scope must say what is unverified"
    )


def test_verified_scope_change_has_no_unverified_reasons():
    recorder = EventRecorder()
    clock = _clock()
    rt = RuntimeController(event_broadcaster=recorder, capture_now=clock.now)
    rt.set_mode(Mode.PRIVACY_PAUSE)
    op = rt.capture_coordinator.pending_operations()[0]
    rt.acknowledge_capture_operation(op.operation_id, managed_stopped=True)
    changes = recorder.by_type("privacy.scope_changed")
    assert changes[-1].payload.new_scope == PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF
    assert changes[-1].payload.unverified_reasons == []


# -------------------------------------------------------------- core mic ack
def test_core_mic_stop_acknowledges_the_physical_stop():
    """L1335: Core mic stop ack -- the flag must follow the physical stop."""
    order: list[str] = []

    def stop_mic() -> None:
        order.append("physical")

    c = CaptureCoordinator(on_stop_mic=stop_mic)
    c.start_core_mic()
    assert c.core_mic_stopped is False
    c.stop_core_mic()
    assert order == ["physical"], "the physical stop must actually be performed"
    assert c.core_mic_stopped is True


def test_failed_physical_stop_does_not_report_stopped():
    """L1338: when external control fails, say so instead of claiming success."""

    def broken() -> None:
        raise RuntimeError("device refused to close")

    c = CaptureCoordinator(on_stop_mic=broken)
    c.start_core_mic()
    c.stop_core_mic()
    assert c.core_mic_stopped is False, (
        "a mic that failed to stop must not be reported as stopped; that is the "
        "false-success mode the plan forbids"
    )
    assert c.compute_privacy_scope(Mode.PRIVACY_PAUSE) != PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF


# ------------------------------------------------------------ determinism guard
def test_operations_are_reproducible_under_a_deterministic_clock():
    clock = _clock()
    c = _coordinator(clock)
    first = c.request_managed_capture_off()
    clock.advance(1000)
    second = c.request_managed_capture_off()
    assert first.operation_id != second.operation_id
    # The deterministic clock also ticks once per reading, so the gap is at least
    # the advance the probe asked for.
    assert second.requested_at - first.requested_at >= timedelta(milliseconds=1000)
    assert len(c.operations) == 2, "each request must be individually traceable"
