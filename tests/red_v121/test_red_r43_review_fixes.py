"""R43 review fixes - unknown ack, cross-runtime ack, empty failure message."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from lva.contracts.commands import CaptureAckPayload, CommandEnvelope, TurnSendTextPayload
from lva.contracts.enums import Mode, PrivacyScope
from lva.core.runtime import RuntimeController

pytestmark = pytest.mark.red_v121


def _stop_operation(rt):
    events = []
    rt._event_broadcaster = events.append
    rt.set_mode(Mode.PRIVACY_PAUSE)
    return [e for e in events if e.type == "capture.operation_requested"][-1].payload.operation_id


def _ack(rt, operation_id, managed_stopped):
    return rt.execute_command(
        CommandEnvelope(
            type="capture.ack",
            payload=CaptureAckPayload(
                type="capture.ack",
                operation_id=operation_id,
                managed_stopped=managed_stopped,
            ),
        )
    )


def test_an_unknown_stop_result_keeps_the_scope_unverified():
    """P0: a null managed_stopped must not be read as a confirmed stop."""
    rt = RuntimeController()
    rt.set_mode(Mode.LIVE)
    op = _stop_operation(rt)

    result = _ack(rt, op, None)

    assert result.status == "applied", f"the ack was refused: {result.error}"
    scope = rt.get_state().privacy_scope
    assert scope != PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF, (
        "an unknown stop result raised the scope to VERIFIED; the flag was left "
        "at the optimistic True instead of the observed unknown"
    )
    assert rt.capture_coordinator.managed_screenpipe_stopped is None, (
        "a null ack must leave the managed-capture state unknown"
    )


def test_a_definite_stop_ack_still_verifies_the_scope():
    """The unknown case must not break the confirmed one."""
    rt = RuntimeController()
    rt.set_mode(Mode.LIVE)
    op = _stop_operation(rt)
    _ack(rt, op, True)
    assert rt.get_state().privacy_scope == PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF


def test_an_ack_from_a_previous_runtime_is_refused():
    """P1: operation ids must not collide across a Core restart."""
    old = RuntimeController()
    old.set_mode(Mode.LIVE)
    old_op = _stop_operation(old)

    new = RuntimeController()
    new.set_mode(Mode.LIVE)
    new_op = _stop_operation(new)

    assert old_op != new_op, (
        "operation ids restart per Core, so a stale ack can match a new request"
    )

    result = _ack(new, old_op, True)
    assert result.status == "rejected", (
        "an ack minted by a previous runtime was accepted by the new one"
    )
    assert new.get_state().privacy_scope != PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF


def test_a_failure_with_an_empty_message_is_still_rejected():
    """P2: `outcome.failed` may be an empty string, which is not "no failure"."""
    from lva.server import run_default_turn

    class Executor:
        def run_text_turn(self, text, domain=None, speak=False):
            return SimpleNamespace(failed="", reply="")

    rt = RuntimeController()
    rt.set_mode(Mode.LIVE)
    rt.turn_runner = lambda text, turn: run_default_turn(rt, Executor(), text)

    result = rt.execute_command(
        CommandEnvelope(
            type="turn.send_text",
            payload=TurnSendTextPayload(type="turn.send_text", text="hi"),
        )
    )
    assert result.status == "rejected", (
        "an executor failure with an empty message was reported as success: "
        f"status={result.status!r}"
    )
    assert rt.turn_controller.current_turn is None
