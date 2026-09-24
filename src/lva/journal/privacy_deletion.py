from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from .repository import JournalRepository

log = logging.getLogger("lva.journal.privacy_deletion")


class PrivacyDeletionService:
    def __init__(self, repository: JournalRepository) -> None:
        self.repo = repository

    def hard_delete_events(
        self,
        event_ids: list[str | UUID],
        reason_code: str,
    ) -> int:
        """Physically delete events from Journal with audited unredacted hashes.

        Never records original text in audit log.
        Performs audit insertion and cascaded event deletion in a single transaction.
        """
        if not event_ids:
            return 0

        op_id = str(uuid4())
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        str_ids = [str(eid) for eid in event_ids]

        # Compute SHA-256 hashes of event IDs
        id_hashes = [hashlib.sha256(eid.encode("utf-8")).hexdigest() for eid in str_ids]
        hashes_json = json.dumps(id_hashes)

        with self.repo.conn:
            # 1. Delete from FTS table
            for eid in str_ids:
                self.repo.conn.execute("DELETE FROM events_fts WHERE event_id = ?", (eid,))

            # 2. Delete from events (cascades to event_revisions & temporal_mentions)
            placeholders = ",".join("?" for _ in str_ids)
            cur = self.repo.conn.execute(
                f"DELETE FROM events WHERE event_id IN ({placeholders})",
                str_ids,
            )
            deleted_count = cur.rowcount

            # 3. Insert audit record with actual deleted_count
            self.repo.conn.execute(
                """
                INSERT INTO deletion_audit (
                    operation_id, requested_at_utc_us, completed_at_utc_us,
                    reason_code, event_id_hashes_json, deleted_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (op_id, now_us, now_us, reason_code, hashes_json, deleted_count),
            )

        log.info(
            "Audited hard deletion complete: operation_id=%s, deleted=%d, reason=%s",
            op_id,
            deleted_count,
            reason_code,
        )
        return deleted_count
