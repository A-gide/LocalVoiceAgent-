"""R42 review fixes - production runner failure, model state, capture UI chain."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from lva.contracts.commands import CommandEnvelope, TurnSendTextPayload
from lva.contracts.enums import Mode
from lva.core.runtime import RuntimeController
from lva.contracts.state import HubBinding

pytestmark = pytest.mark.red_v121


class _StubExecutor:
    """A TurnExecutor whose outcome reports failure the way the real one does."""

    def __init__(self, failed=None, reply=""):
        self._failed = failed
        self._reply = reply

    def run_text_turn(self, text, domain=None, speak=False):
        return SimpleNamespace(failed=self._failed, reply=self._reply)


def test_the_production_runner_reports_an_executor_failure():
    """F-003: a runner that raises must make the command rejected, not applied."""
    from lva.server import run_default_turn

    rt = RuntimeController()
    rt.set_mode(Mode.LIVE)
    rt.turn_runner = lambda text, turn: run_default_turn(
        rt, _StubExecutor(failed="provider exploded"), text
    )

    res = rt.execute_command(
        CommandEnvelope(
            type="turn.send_text",
            payload=TurnSendTextPayload(type="turn.send_text", text="hello"),
        )
    )

    assert res.status == "rejected", (
        "the production runner reported success for a turn the executor failed: "
        f"status={res.status!r}"
    )
    assert rt.turn_controller.current_turn is None, "the failed turn was left open"


def test_the_production_runner_records_a_successful_reply():
    """The success path must still publish the reply for turn.completed."""
    from lva.server import run_default_turn

    rt = RuntimeController()
    rt.set_mode(Mode.LIVE)
    rt.turn_runner = lambda text, turn: run_default_turn(
        rt, _StubExecutor(reply="the answer"), text
    )

    res = rt.execute_command(
        CommandEnvelope(
            type="turn.send_text",
            payload=TurnSendTextPayload(type="turn.send_text", text="hello"),
        )
    )

    assert res.status == "applied"
    assert rt.reply_text == "the answer"


def test_an_uncommitted_binding_does_not_drive_inference():
    """F-005: a preparing / rolled-back binding must not steer inference."""
    rt = RuntimeController()
    rt.set_hub_binding(
        HubBinding(desired_model_id="chosen-B", active_model_id=None, status="preparing")
    )
    assert rt.bound_inference_model() is None, (
        "a binding that is still preparing selected a model the Hub has not "
        "activated; a failed switch would keep steering later requests"
    )

    rt.set_hub_binding(
        HubBinding(desired_model_id="chosen-B", active_model_id=None, status="failed")
    )
    assert rt.bound_inference_model() is None, (
        "a failed binding still selected the target model"
    )

    rt.set_hub_binding(
        HubBinding(desired_model_id="chosen-B", active_model_id="chosen-B", status="ready")
    )
    assert rt.bound_inference_model() == "chosen-B"


def test_the_ui_runs_and_acknowledges_a_capture_request():
    """FIX-006: the request must reach the executor and its observed value ack."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    store = (root / "apps" / "desktop-ui" / "src" / "stores" / "runtime.ts").read_text(
        encoding="utf-8"
    )
    bridge = (root / "apps" / "desktop-ui" / "src" / "bridge" / "tauri-bridge.ts").read_text(
        encoding="utf-8"
    )

    assert "capture.operation_requested" in store, (
        "the UI never handles the Core capture request, so the operation never runs"
    )
    assert "executeCaptureOperation" in store, (
        "the UI does not call the Desktop capture executor for the request"
    )
    assert "capture.ack" in store, (
        "the UI never sends the observed result back, so the scope stays unverified"
    )
    assert "execute_capture_operation" in bridge, (
        "the bridge has no command face for the capture executor"
    )
    assert "managed_stopped" in store, (
        "the ack must carry the observed managed_stopped value"
    )
