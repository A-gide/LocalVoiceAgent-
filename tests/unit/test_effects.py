"""Unit tests for StaleEffectGate per Part 4.6 and Invariant I01.

Verifies:
1. Gate 1: pre-dispatch rejection when turn is not current or epoch is stale.
2. Gate 2: in-stream cancellation detection and token suppression.
3. Gate 3: pre-side-effect rejection for playback, UI, history, and Journal commits.
4. Dropped effect tracking and counter increments.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from lva.contracts.ids import TurnId
from lva.core.effects import StaleEffectGate
from lva.core.turn import TurnController


def test_stale_effect_gate_three_layers():
    """Verify StaleEffectGate operates across all 3 architectural gates."""
    turn_ctrl = TurnController()
    session_id = uuid4()
    current_epoch = 0

    gate = StaleEffectGate(
        get_current_turn=lambda: turn_ctrl.current_turn,
        get_current_epoch=lambda: current_epoch,
    )

    # 1. Before turn creation: Gate 1 rejects
    dummy_turn = TurnId(session_id=session_id, sequence=99)
    assert gate.check_gate1_pre_dispatch(dummy_turn, current_epoch) is False

    # 2. Turn 1 created
    turn_1 = turn_ctrl.create_turn(session_id)
    assert gate.check_gate1_pre_dispatch(turn_1, current_epoch) is True
    assert gate.check_gate2_in_stream(turn_1, current_epoch) is True
    assert gate.check_gate3_pre_side_effect(turn_1, current_epoch, "playback") is True

    # 3. User barge-in: epoch increments, turn 1 cancelled
    current_epoch += 1
    turn_ctrl.cancel_turn(turn_1, reason="barge_in")

    # In-stream must reject turn 1
    assert gate.check_gate2_in_stream(turn_1, 0) is False
    # Pre-side-effect must reject all effects for turn 1
    assert gate.check_gate3_pre_side_effect(turn_1, 0, "ui_render") is False
    assert gate.check_gate3_pre_side_effect(turn_1, 0, "tts_playback") is False
    assert gate.check_gate3_pre_side_effect(turn_1, 0, "journal_commit") is False

    # Stale dropped count incremented
    assert gate.stale_dropped_count >= 4

    # 4. Turn 2 created on new epoch: all gates pass
    turn_2 = turn_ctrl.create_turn(session_id)
    assert gate.check_gate1_pre_dispatch(turn_2, current_epoch) is True
    assert gate.check_gate2_in_stream(turn_2, current_epoch) is True
    assert gate.check_gate3_pre_side_effect(turn_2, current_epoch, "journal_commit") is True
