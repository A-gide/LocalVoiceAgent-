from __future__ import annotations

import logging
from typing import Callable

from ..contracts.ids import TurnId

log = logging.getLogger("lva.core.effects")


class StaleEffectGate:
    def __init__(
        self,
        get_current_turn: Callable[[], TurnId | None],
        get_current_epoch: Callable[[], int],
    ) -> None:
        self._get_current_turn = get_current_turn
        self._get_current_epoch = get_current_epoch
        self.stale_dropped_count: int = 0

    def check_gate1_pre_dispatch(self, turn_id: TurnId, provider_epoch: int) -> bool:
        """Gate 1: Pre-dispatch check before launching inference or synthesis."""
        current_turn = self._get_current_turn()
        current_epoch = self._get_current_epoch()
        if current_turn != turn_id or current_epoch != provider_epoch:
            self.stale_dropped_count += 1
            log.warning(
                "Gate 1 REJECT: stale dispatch (turn=%s vs current=%s, epoch=%d vs current=%d)",
                turn_id,
                current_turn,
                provider_epoch,
                current_epoch,
            )
            return False
        return True

    def check_gate2_in_stream(self, turn_id: TurnId, provider_epoch: int) -> bool:
        """Gate 2: In-stream check between tokens or audio chunks."""
        current_turn = self._get_current_turn()
        current_epoch = self._get_current_epoch()
        if current_turn != turn_id or current_epoch != provider_epoch:
            self.stale_dropped_count += 1
            log.debug(
                "Gate 2 REJECT: stale stream chunk (turn=%s, epoch=%d)",
                turn_id,
                provider_epoch,
            )
            return False
        return True

    def check_gate3_pre_side_effect(
        self,
        turn_id: TurnId | None,
        provider_epoch: int,
        effect_name: str = "side_effect",
    ) -> bool:
        """Gate 3: Pre-side-effect check before playback, UI output, history, or Journal commit."""
        current_turn = self._get_current_turn()
        current_epoch = self._get_current_epoch()
        if turn_id is not None and (current_turn != turn_id or current_epoch != provider_epoch):
            self.stale_dropped_count += 1
            log.warning(
                "Gate 3 REJECT: dropped stale %s (turn=%s vs current=%s, epoch=%d vs current=%d)",
                effect_name,
                turn_id,
                current_turn,
                provider_epoch,
                current_epoch,
            )
            return False
        return True
