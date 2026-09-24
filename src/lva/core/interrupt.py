from __future__ import annotations

import logging
from typing import Callable

from ..contracts.enums import FloorOwner
from ..contracts.ids import TurnId
from .floor import FloorController
from .turn import TurnController

log = logging.getLogger("lva.core.interrupt")


class InterruptController:
    def __init__(
        self,
        turn_controller: TurnController,
        floor_controller: FloorController,
        on_interrupt_action: Callable[[str], None] | None = None,
    ) -> None:
        self.turn_controller = turn_controller
        self.floor_controller = floor_controller
        self._on_interrupt_action = on_interrupt_action
        self._provider_epoch: int = 0

    @property
    def provider_epoch(self) -> int:
        return self._provider_epoch

    def commit_interrupt(self, reason: str = "barge_in") -> int:
        """Atomically commit an interrupt transaction.

        1. Bump provider_epoch (invalidates all pending generation/playback)
        2. Set floor owner to USER (I03)
        3. Cancel active turn
        4. Trigger hardware/queue abort callbacks (player.flush, queue purge)
        """
        self._provider_epoch += 1
        current_turn = self.turn_controller.current_turn
        log.info(
            "Interrupt committed: reason=%s, new_epoch=%d, cancelling_turn=%s",
            reason,
            self._provider_epoch,
            current_turn,
        )

        self.floor_controller.set_owner(FloorOwner.USER)

        if current_turn is not None:
            self.turn_controller.cancel_turn(current_turn, reason=reason)

        if self._on_interrupt_action:
            try:
                # The reason is forwarded so the owner can pick the right abort:
                # a real barge-in wants the full barge-in semantics, while a mode
                # transition only wants the sound stopped.
                self._on_interrupt_action(reason)
            except Exception as exc:
                log.exception("Error executing interrupt action callback: %s", exc)

        return self._provider_epoch
