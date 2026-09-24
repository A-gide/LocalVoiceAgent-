from __future__ import annotations

import logging
from uuid import UUID

from .repository import JournalRepository

log = logging.getLogger("lva.journal.corrections")


class CorrectionService:
    def __init__(self, repository: JournalRepository) -> None:
        self.repo = repository

    def correct_event(
        self,
        event_id: str | UUID,
        corrected_text: str,
        reason: str,
        actor: str = "user",
        rules_version: str | None = None,
    ) -> int:
        """Add an append-only revision to an event. Raw text is never overwritten (I06)."""
        new_rev = self.repo.add_revision(
            event_id=event_id,
            corrected_text=corrected_text,
            reason=reason,
            actor=actor,
            rules_version=rules_version,
        )
        log.info(
            "Event %s corrected -> new revision %d by %s (reason: %s)",
            event_id,
            new_rev,
            actor,
            reason,
        )
        return new_rev
