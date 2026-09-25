from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any

from ..journal.repository import JournalRepository
from .client import ScreenpipeRestClient
from .normalize import normalize_screenpipe_audio_item

log = logging.getLogger("lva.screenpipe_importer.worker")


class ScreenpipeImportWorker:
    """Worker that imports Screenpipe events transactionally with watermark checkpoints (PR-018)."""

    def __init__(
        self,
        client: ScreenpipeRestClient,
        repository: JournalRepository,
    ) -> None:
        self.client = client
        self.repo = repository

    def get_watermark(self) -> int:
        cur = self.repo.conn.execute(
            """
            SELECT watermark_utc_us FROM import_checkpoints
            WHERE importer = 'screenpipe_rest' AND external_source = 'audio'
            """
        )
        row = cur.fetchone()
        return row["watermark_utc_us"] if row and row["watermark_utc_us"] else 0

    def update_watermark(self, watermark_utc_us: int) -> None:
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        with self.repo.conn:
            self.repo.conn.execute(
                """
                INSERT INTO import_checkpoints (
                    importer, external_source, watermark_utc_us, updated_at_utc_us
                ) VALUES ('screenpipe_rest', 'audio', ?, ?)
                ON CONFLICT(importer, external_source) DO UPDATE SET
                    watermark_utc_us = excluded.watermark_utc_us,
                    updated_at_utc_us = excluded.updated_at_utc_us
                """,
                (watermark_utc_us, now_us),
            )

    async def import_page(self, limit: int = 50) -> int:
        """Import one page within a single transaction; updates checkpoint upon commit (Part 7.2).

        Replays from crash checkpoint without duplicating events (I17).
        Stops safely if response schema is unsupported.
        """
        watermark = self.get_watermark()
        start_time_iso = None
        if watermark > 0:
            start_time_iso = datetime.fromtimestamp(watermark / 1_000_000, tz=timezone.utc).isoformat()

        items = await self.client.search(limit=limit, start_time=start_time_iso)
        if not isinstance(items, list):
            raise ValueError("IMPORT_SCHEMA_UNSUPPORTED: Screenpipe search response must be a list")

        imported_count = 0
        redacted_count = 0
        skipped_count = 0
        max_seen_ts = watermark
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)

        # Atomic page transaction (Part 7.2)
        with self.repo.conn:
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("IMPORT_SCHEMA_UNSUPPORTED: Item must be a dictionary")

                # A single unusable record must not abort the whole page: the page
                # transaction is what guarantees atomicity, and a record whose
                # timestamp cannot be parsed has no safe position in the timeline.
                # It is skipped and the watermark is left where it was, so the
                # record is retried rather than silently passed over.
                try:
                    normalized = normalize_screenpipe_audio_item(item)
                except ValueError as exc:
                    log.warning("Skipping unimportable Screenpipe record: %s", exc)
                    skipped_count += 1
                    continue
                occ_us = normalized["occurred_at_utc_us"]

                # Idempotent deduplication (I17): check unique constraint
                cur = self.repo.conn.execute(
                    "SELECT 1 FROM events WHERE external_source = ? AND external_id = ?",
                    (normalized["external_source"], normalized["external_id"]),
                )
                if cur.fetchone() is not None:
                    # The event is already stored, but the source may have marked it
                    # redacted *since* the first import.  Plan L896 requires that mark
                    # to be honoured, so the duplicate check cannot simply skip: it
                    # applies the redaction as a new revision (raw_text stays intact
                    # per I06).
                    if normalized.get("redacted"):
                        if self.repo.apply_source_redaction(
                            normalized["external_source"],
                            normalized["external_id"],
                            commit=False,
                        ):
                            redacted_count += 1
                            log.info(
                                "Applied a later source redaction to %s",
                                normalized["external_id"],
                            )
                    else:
                        log.debug("Event already exists, skipping duplicate: %s", normalized["external_id"])
                    continue

                # A record at or before the watermark is only skipped when it is a
                # *true* replay.  Using `<=` dropped a record that shared a
                # microsecond with the checkpoint: the checkpoint is the highest
                # timestamp already imported, so equality means "possibly the same
                # record", which the unique constraint above has already resolved.
                if occ_us < watermark:
                    continue

                self.repo.append_event(
                    event_id=normalized["event_id"],
                    raw_text=normalized["raw_text"],
                    occurred_at_utc_us=occ_us,
                    event_timezone=normalized.get("event_timezone", "UTC"),
                    utc_offset_minutes=normalized.get("utc_offset_minutes", 0),
                    started_at_utc_us=normalized.get("started_at_utc_us"),
                    ended_at_utc_us=normalized.get("ended_at_utc_us"),
                    speaker=normalized["speaker"],
                    source=normalized["source"],
                    confidence=normalized["confidence"],
                    domain=normalized["domain"],
                    provenance=normalized["provenance"],
                    external_source=normalized["external_source"],
                    external_id=normalized["external_id"],
                    # Do not commit per record: the page must be one transaction
                    # (plan 7.2), or a page whose later record is invalid leaves the
                    # earlier ones committed.
                    commit=False,
                )
                imported_count += 1
                if occ_us > max_seen_ts:
                    max_seen_ts = occ_us

            # Update checkpoint in the same transaction
            if max_seen_ts > watermark:
                self.repo.conn.execute(
                    """
                    INSERT INTO import_checkpoints (
                        importer, external_source, watermark_utc_us, updated_at_utc_us
                    ) VALUES ('screenpipe_rest', 'audio', ?, ?)
                    ON CONFLICT(importer, external_source) DO UPDATE SET
                        watermark_utc_us = excluded.watermark_utc_us,
                        updated_at_utc_us = excluded.updated_at_utc_us
                    """,
                    (max_seen_ts, now_us),
                )

        return imported_count


class ScreenpipeSqliteAdapter:
    """Optional direct read-only SQLite adapter per Part 7.2.

    Disabled by default. When enabled with `enabled=True`, opens Screenpipe DB
    with read-only connection, verifies fixed schema version, and returns events.
    If schema does not match known versions, raises ValueError("IMPORT_SCHEMA_UNSUPPORTED").
    """

    KNOWN_AUDIO_TABLES = {"audio_transcriptions", "audio_chunks"}

    def __init__(self, db_path: str | Path, enabled: bool = False) -> None:
        self.db_path = Path(db_path)
        self.enabled = enabled

    def verify_and_connect(self) -> sqlite3.Connection:
        if not self.enabled:
            raise RuntimeError("Screenpipe direct SQLite adapter is disabled by default")
        if not self.db_path.exists():
            raise FileNotFoundError(f"Screenpipe DB '{self.db_path}' not found")

        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        # Verify fixed schema version: check table existence
        cur = conn.cursor()
        tables = {
            row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if not tables.intersection(self.KNOWN_AUDIO_TABLES):
            conn.close()
            raise ValueError("IMPORT_SCHEMA_UNSUPPORTED: Screenpipe DB missing expected audio tables")

        return conn
