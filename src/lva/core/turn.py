from __future__ import annotations

import logging
from typing import Callable
from uuid import UUID

from ..contracts.ids import TurnId

log = logging.getLogger("lva.core.turn")


class TurnController:
    def __init__(
        self,
        on_turn_started: Callable[[TurnId], None] | None = None,
        on_turn_cancelled: Callable[[TurnId, str], None] | None = None,
        on_turn_completed: Callable[[TurnId], None] | None = None,
    ) -> None:
        self._current_turn: TurnId | None = None
        self._sequence: int = 0
        self._on_turn_started = on_turn_started
        self._on_turn_cancelled = on_turn_cancelled
        self._on_turn_completed = on_turn_completed

    @property
    def current_turn(self) -> TurnId | None:
        return self._current_turn

    def create_turn(self, session_id: UUID, user_text: str | None = None) -> TurnId:
        """Create a new monotonic turn. If a turn is already active, it is cancelled first (I02)."""
        if self._current_turn is not None:
            log.warning(
                "Cancelling active turn %s before creating new turn", self._current_turn
            )
            self.cancel_turn(self._current_turn, reason="superseded_by_new_turn")

        self._sequence += 1
        turn_id = TurnId(session_id=session_id, sequence=self._sequence)
        self._current_turn = turn_id
        log.debug("Turn created: %s (text: %s)", turn_id, user_text[:30] if user_text else None)

        if self._on_turn_started:
            self._on_turn_started(turn_id)
        return turn_id

    def cancel_turn(self, turn_id: TurnId | None = None, reason: str = "cancelled") -> bool:
        if self._current_turn is None:
            return False

        if turn_id is None or self._current_turn == turn_id:
            cancelled = self._current_turn
            self._current_turn = None
            log.debug("Turn cancelled: %s, reason=%s", cancelled, reason)
            if self._on_turn_cancelled:
                self._on_turn_cancelled(cancelled, reason)
            return True
        return False

    def complete_turn(self, turn_id: TurnId) -> bool:
        if self._current_turn is not None and self._current_turn == turn_id:
            self._current_turn = None
            log.debug("Turn completed: %s", turn_id)
            if self._on_turn_completed:
                self._on_turn_completed(turn_id)
            return True
        return False
