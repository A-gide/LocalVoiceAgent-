from __future__ import annotations

import logging
from typing import Callable
from uuid import UUID, uuid4

log = logging.getLogger("lva.core.session")


class SessionController:
    def __init__(self, on_session_change: Callable[[UUID | None], None] | None = None) -> None:
        self._current_session_id: UUID | None = None
        self._on_session_change = on_session_change

    @property
    def current_session_id(self) -> UUID | None:
        return self._current_session_id

    def start_session(self) -> UUID:
        self._current_session_id = uuid4()
        log.info("Session started: %s", self._current_session_id)
        if self._on_session_change:
            self._on_session_change(self._current_session_id)
        return self._current_session_id

    def end_session(self) -> None:
        if self._current_session_id is not None:
            old_id = self._current_session_id
            self._current_session_id = None
            log.info("Session ended: %s", old_id)
            if self._on_session_change:
                self._on_session_change(None)
