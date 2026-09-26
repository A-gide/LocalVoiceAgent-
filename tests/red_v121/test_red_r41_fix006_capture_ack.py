"""R41 FIX-006 - managed-capture request reaches the executor and its ack settles."""
from __future__ import annotations

from lva.contracts.commands import CommandEnvelope, CaptureAckPayload
from lva.contracts.enums import Mode, PrivacyScope
from lva.core.runtime import RuntimeController


def test_entering_privacy_pause_publishes_a_capture_operation():
    """Core must carry the stop request to the executor, not just record it."""
    events = []
    rt = RuntimeController(event_broadcaster=events.append)
    rt.set_mode(Mode.LIVE)
    events.clear()

    rt.set_mode(Mode.PRIVACY_PAUSE)

    requested = [e for e in events if e.type == "capture.operation_requested"]
    assert requested, (
        "Privacy Pause recorded an operation but published nothing, so it could "
        "never reach the process that owns the recorder"
    )
    op = requested[-1].payload
    assert op.kind == "stop" and op.operation_id


def test_a_capture_ack_settles_the_operation_and_verifies_the_scope():
    """An executor ack with the observed state must verify the scope."""
    events = []
    rt = RuntimeController(event_broadcaster=events.append)
    rt.set_mode(Mode.LIVE)
    rt.set_mode(Mode.PRIVACY_PAUSE)
    op_id = [e for e in events if e.type == "capture.operation_requested"][-1].payload.operation_id

    result = rt.execute_command(
        CommandEnvelope(
            type="capture.ack",
            payload=CaptureAckPayload(
                type="capture.ack", operation_id=op_id, managed_stopped=True,
                external_detected=False,
            ),
        )
    )

    assert result.status == "applied", f"the executor ack was refused: {result.error}"
    scope = rt.get_state().privacy_scope
    assert scope == PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF, (
        f"a definite stop ack did not verify the scope: {scope}"
    )


def test_a_failed_stop_ack_does_not_verify_the_scope():
    """An executor that could not stop must not let Core claim a verified pause."""
    events = []
    rt = RuntimeController(event_broadcaster=events.append)
    rt.set_mode(Mode.LIVE)
    rt.set_mode(Mode.PRIVACY_PAUSE)
    op_id = [e for e in events if e.type == "capture.operation_requested"][-1].payload.operation_id

    rt.execute_command(
        CommandEnvelope(
            type="capture.ack",
            payload=CaptureAckPayload(
                type="capture.ack", operation_id=op_id, managed_stopped=False,
            ),
        )
    )

    scope = rt.get_state().privacy_scope
    assert scope != PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF, (
        "Core claimed a verified pause after the executor reported it did not stop"
    )


def test_an_ack_for_an_unknown_operation_is_refused():
    """A stale/unrelated ack must not move the privacy scope."""
    rt = RuntimeController()
    rt.set_mode(Mode.LIVE)
    rt.set_mode(Mode.PRIVACY_PAUSE)

    result = rt.execute_command(
        CommandEnvelope(
            type="capture.ack",
            payload=CaptureAckPayload(
                type="capture.ack", operation_id="does-not-exist", managed_stopped=True,
            ),
        )
    )
    assert result.status == "rejected", "an unknown operation ack was accepted"
