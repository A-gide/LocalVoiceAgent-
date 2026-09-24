from __future__ import annotations

import logging
from typing import Callable

from ..contracts.enums import FloorOwner

log = logging.getLogger("lva.core.floor")


class FloorController:
    def __init__(self, on_change: Callable[[FloorOwner, FloorOwner], None] | None = None) -> None:
        self._owner: FloorOwner = FloorOwner.NONE
        self._on_change = on_change

    @property
    def owner(self) -> FloorOwner:
        return self._owner

    def set_owner(self, new_owner: FloorOwner) -> None:
        if self._owner != new_owner:
            old_owner = self._owner
            self._owner = new_owner
            log.debug("Floor changed: %s -> %s", old_owner.value, new_owner.value)
            if self._on_change:
                self._on_change(old_owner, new_owner)
