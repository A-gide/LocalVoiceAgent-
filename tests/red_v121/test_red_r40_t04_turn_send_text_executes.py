"""R40 T04 — `turn.send_text` must execute and emit the typed turn lifecycle."""
from __future__ import annotations

import pytest

from lva.contracts.commands import CommandEnvelope, TurnSendTextPayload
from lva.contracts.enums import Mode
from lva.core.runtime import RuntimeController

pytestmark = pytest.mark.red_v121


def test_turn_send_text_runs_the_executor_and_completes_the_turn():
    """The typed command must execute, not only allocate a Turn."""
    rt = RuntimeController()
    rt.set_mode(Mode.LIVE)
    executed: list[str] = []

    def runner(text, turn):
        executed.append(text)
        rt.reply_text = f"reply to {text}"
        rt.turn_controller.complete_turn(turn)

    rt.turn_runner = runner
    res = rt.execute_command(
        CommandEnvelope(
            type="turn.send_text",
            payload=TurnSendTextPayload(type="turn.send_text", text="hello"),
        )
    )

    assert res.status == "applied"
    assert executed == ["hello"], (
        "turn.send_text allocated a Turn but never ran the executor: "
        f"executed={executed!r}"
    )
    assert rt.turn_controller.current_turn is None, (
        "the turn was opened but never closed; the caller is left streaming forever"
    )


def test_turn_send_text_emits_the_typed_lifecycle_events():
    """`turn.started` / `turn.completed` must reach the typed event stream."""
    events: list = []
    rt = RuntimeController(event_broadcaster=events.append)
    rt.set_mode(Mode.LIVE)

    def runner(text, turn):
        rt.reply_text = "the reply"
        rt.turn_controller.complete_turn(turn)

    rt.turn_runner = runner
    rt.execute_command(
        CommandEnvelope(
            type="turn.send_text",
            payload=TurnSendTextPayload(type="turn.send_text", text="hi"),
        )
    )

    kinds = [e.type for e in events]
    assert "turn.started" in kinds, (
        f"no turn.started event was emitted; emitted={kinds!r}"
    )
    assert "turn.completed" in kinds, (
        f"no turn.completed event was emitted; emitted={kinds!r}"
    )
    started = next(e for e in events if e.type == "turn.started")
    completed = next(e for e in events if e.type == "turn.completed")
    assert started.payload.user_text == "hi"
    assert completed.payload.reply_text == "the reply", (
        "turn.completed must carry the reply so the UI can render it"
    )


def test_turn_send_text_is_still_refused_in_forbidden_modes():
    """The mode guard is unchanged; the runner must not be reached (I07/I08)."""
    rt = RuntimeController()
    reached: list[str] = []
    rt.turn_runner = lambda text, turn: reached.append(text)

    for mode in (Mode.STANDBY, Mode.PASSIVE, Mode.PRIVACY_PAUSE):
        rt.set_mode(mode)
        res = rt.execute_command(
            CommandEnvelope(
                type="turn.send_text",
                payload=TurnSendTextPayload(type="turn.send_text", text="x"),
            )
        )
        assert res.status == "rejected"

    assert reached == [], (
        "a forbidden mode reached the turn runner; the guard must reject first"
    )


def test_suppression_lets_a_richer_caller_own_the_turn():
    """`/api/ask` runs the executor itself; the default runner must stay out."""
    rt = RuntimeController()
    rt.set_mode(Mode.LIVE)
    reached: list[str] = []
    rt.turn_runner = lambda text, turn: reached.append(text)

    rt.turn_runner_suppressed = True
    try:
        rt.execute_command(
            CommandEnvelope(
                type="turn.send_text",
                payload=TurnSendTextPayload(type="turn.send_text", text="q"),
            )
        )
    finally:
        rt.turn_runner_suppressed = False

    assert reached == [], "the default runner executed a turn /api/ask already owns"
