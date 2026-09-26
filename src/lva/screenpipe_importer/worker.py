from __future__ import annotations

import json
import hashlib
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

    #: Bound on how many pages one drain will fetch, so a source that never
    #: returns an empty page cannot spin forever.
    MAX_PAGES = 200
    CURSOR_PREFIX = "screenpipe-rest-offset-v1:"

    #: T01: how far *below* the checkpoint one call re-reads to catch records
    #: that reached the source after the checkpoint had already moved past them
    #: (late-arriving or timestamp-corrected records).  The checkpoint itself
    #: stays monotonic -- it is never moved backwards -- so this bounded sweep is
    #: the only way a record underneath it can be discovered.  The window bounds
    #: the cost of each call; a record that appears *later* than this window away
    #: from the checkpoint is outside it and is a documented limitation.
    REOPEN_WINDOW_US = 7 * 24 * 60 * 60 * 1_000_000

    #: T01-R2: after this many consecutive failed attempts the record is left on
    #: record as abandoned so the range can close instead of rescanning history
    #: forever.  Abandonment is explicit and auditable (see JournalRepository).
    QUARANTINE_ABANDON_AFTER = 3

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
                    cursor = NULL,
                    updated_at_utc_us = excluded.updated_at_utc_us
                """,
                (watermark_utc_us, now_us),
            )

    def _load_resume_state(self, watermark: int) -> tuple[int, int]:
        row = self.repo.conn.execute(
            """
            SELECT cursor FROM import_checkpoints
            WHERE importer = 'screenpipe_rest' AND external_source = 'audio'
            """
        ).fetchone()
        cursor = row["cursor"] if row else None
        if cursor is None:
            return 0, 0
        if not isinstance(cursor, str) or not cursor.startswith(self.CURSOR_PREFIX):
            raise ValueError(
                "IMPORT_CHECKPOINT_CURSOR_UNSUPPORTED: refusing to discard an "
                "unknown Screenpipe continuation cursor"
            )
        try:
            state = json.loads(cursor[len(self.CURSOR_PREFIX) :])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "IMPORT_CHECKPOINT_CURSOR_INVALID: refusing to restart a capped "
                "Screenpipe drain from the head"
            ) from exc
        if (
            not isinstance(state, dict)
            or state.get("version") != 1
            or type(state.get("offset")) is not int
            or state["offset"] < 0
            or type(state.get("skipped")) is not int
            or state["skipped"] < 0
            or type(state.get("watermark")) is not int
            or state["watermark"] != watermark
        ):
            raise ValueError(
                "IMPORT_CHECKPOINT_CURSOR_INVALID: continuation state does not "
                "match the current watermark; refusing to skip source records"
            )
        return state["offset"], state["skipped"]

    def _save_resume_state(self, offset: int, skipped: int, watermark: int) -> None:
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        cursor = self.CURSOR_PREFIX + json.dumps(
            {
                "version": 1,
                "offset": offset,
                "skipped": skipped,
                "watermark": watermark,
            },
            separators=(",", ":"),
        )
        with self.repo.conn:
            self.repo.conn.execute(
                """
                INSERT INTO import_checkpoints (
                    importer, external_source, cursor, watermark_utc_us, updated_at_utc_us
                ) VALUES ('screenpipe_rest', 'audio', ?, ?, ?)
                ON CONFLICT(importer, external_source) DO UPDATE SET
                    cursor = excluded.cursor,
                    updated_at_utc_us = excluded.updated_at_utc_us
                """,
                (cursor, watermark, now_us),
            )

    def _clear_resume_state(self) -> None:
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        with self.repo.conn:
            self.repo.conn.execute(
                """
                UPDATE import_checkpoints SET cursor = NULL, updated_at_utc_us = ?
                WHERE importer = 'screenpipe_rest' AND external_source = 'audio'
                """,
                (now_us,),
            )

    async def import_page(self, limit: int = 50) -> int:
        """Drain every available page, then advance the checkpoint once.

        The earlier version fetched a single page (``offset=0``) and moved the
        checkpoint to that page's *maximum* timestamp.  Against a newest-first
        source the first page's maximum IS the newest record, so the next request's
        ``start_time`` excluded every older record and they became unreachable
        forever -- 150 of 200 records in the reproduced case.

        Two changes follow from that: the pages are drained, so "what this call
        saw" is the whole available range, and the checkpoint is written once at
        the end rather than per page, so a partial drain cannot claim progress it
        did not make.  Each page still commits in its own transaction, as plan
        7.2 requires.

        Replays from a crash checkpoint without duplicating events (I17).
        Stops safely if the response schema is unsupported.
        """
        # Idempotency caveat (I17): the unique constraint on
        # (external_source, external_id) is only as strong as the id.  A
        # source-supplied id is stable, so a replay is recognised.  A *derived* id
        # (the source gave none) cannot be both stable across a redaction and
        # unique per record, so lossless idempotency is not promised for it -- the
        # record carries `stable_id: false` and a reconciliation must refuse to
        # rely on it rather than assume the guarantee holds.
        watermark = self.get_watermark()
        start_time_iso = None
        if watermark > 0:
            start_time_iso = datetime.fromtimestamp(watermark / 1_000_000, tz=timezone.utc).isoformat()

        imported_count = 0
        redacted_count = 0
        skipped_count = 0
        max_seen_ts = watermark
        open_quarantine = False

        offset, resumed_skip_count = self._load_resume_state(watermark)
        drained = False
        for _page in range(self.MAX_PAGES):
            items = await self.client.search(
                limit=limit, offset=offset, start_time=start_time_iso
            )
            if not isinstance(items, list):
                raise ValueError("IMPORT_SCHEMA_UNSUPPORTED: Screenpipe search response must be a list")
            if not items:
                drained = True
                break

            # Atomic page transaction (Part 7.2)
            with self.repo.conn:
                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("IMPORT_SCHEMA_UNSUPPORTED: Item must be a dictionary")

                    # A single unusable record must not abort the whole page: the
                    # page transaction is what guarantees atomicity, and a record
                    # whose timestamp cannot be parsed has no safe position in the
                    # timeline.  It is skipped and the checkpoint is left where it
                    # was, so the record is retried rather than passed over.
                    try:
                        normalized = normalize_screenpipe_audio_item(item)
                    except ValueError as exc:
                        log.warning("Skipping unimportable Screenpipe record: %s", exc)
                        if self._quarantine_record(item, str(exc)):
                            skipped_count += 1
                            open_quarantine = True
                        continue
                    occ_us = normalized["occurred_at_utc_us"]
                    # Track the true maximum of the drained range, not just of the
                    # records newly inserted here: when everything in range is
                    # already stored (deduplication) the checkpoint still has to be
                    # able to close over the range once any quarantine is resolved.
                    if occ_us > max_seen_ts:
                        max_seen_ts = occ_us

                    # Keep this guard at the worker boundary as well as in the
                    # normalizer: a derived id cannot safely identify a prior row
                    # for a source redaction.
                    if normalized.get("redacted") and (
                        normalized.get("stable_id") is False
                        or normalized.get("external_id_is_derived") is True
                    ):
                        log.warning(
                            "UNVERIFIED_SOURCE_REDACTION: refusing a redaction "
                            "without a stable source id; existing Journal text is retained"
                        )
                        if self._quarantine_record(item, "UNVERIFIED_SOURCE_REDACTION"):
                            skipped_count += 1
                            open_quarantine = True
                        continue

                    # Idempotent deduplication (I17): check unique constraint
                    # Both the current id and any id an earlier formula produced
                    # for this record are checked: a changed derived-id formula
                    # must not make an already-imported row look like a new one,
                    # or a replay would duplicate it.
                    candidate_ids = [normalized["external_id"]] + list(
                        normalized.get("legacy_external_ids") or []
                    )
                    placeholders = ",".join("?" for _ in candidate_ids)
                    cur = self.repo.conn.execute(
                        f"SELECT DISTINCT external_id, audio_ref, provenance_json FROM events "
                        f"WHERE external_source = ? AND external_id IN ({placeholders})",
                        [normalized["external_source"], *candidate_ids],
                    )
                    matched_rows = cur.fetchall()
                    current_matches = [
                        row
                        for row in matched_rows
                        if row["external_id"] == normalized["external_id"]
                    ]
                    legacy_matches = [
                        row
                        for row in matched_rows
                        if row["external_id"] in normalized.get("legacy_external_ids", [])
                    ]
                    if normalized.get("redacted") and current_matches:
                        # The event is already stored, but the source may have
                        # marked it redacted since the first import.  Plan L896
                        # requires that mark to be honoured, so the duplicate check
                        # cannot simply skip: it applies the redaction as a new
                        # revision to the stored id that actually matched (raw_text
                        # stays intact per I06).
                        for matched_row in current_matches:
                            matched_id = matched_row["external_id"]
                            if self.repo.apply_source_redaction(
                                normalized["external_source"],
                                matched_id,
                                commit=False,
                            ):
                                redacted_count += 1
                                log.info(
                                    "Applied a later source redaction to %s",
                                    matched_id,
                                )
                        continue
                    if normalized.get("redacted") and legacy_matches:
                        log.warning(
                            "UNVERIFIED_SOURCE_REDACTION: only a derived legacy id "
                            "matched; refusing to revise or delete that Journal row"
                        )
                        skipped_count += 1
                        continue
                    if current_matches:
                        log.debug("Event already exists, skipping duplicate: %s", normalized["external_id"])
                        continue
                    if legacy_matches:
                        incoming_provenance = normalized.get("provenance") or {}
                        incoming_path = normalized.get("audio_ref") or incoming_provenance.get(
                            "audio_file_path"
                        )
                        confirmed_legacy_match = False
                        ambiguous_legacy_match = False
                        for matched_row in legacy_matches:
                            try:
                                stored_provenance = json.loads(
                                    matched_row["provenance_json"] or "{}"
                                )
                            except (TypeError, ValueError):
                                stored_provenance = {}
                            if not isinstance(stored_provenance, dict):
                                stored_provenance = {}
                            stored_path = stored_provenance.get("audio_file_path") or matched_row[
                                "audio_ref"
                            ]
                            if (
                                isinstance(incoming_path, str)
                                and incoming_path
                                and isinstance(stored_path, str)
                                and stored_path
                            ):
                                if incoming_path == stored_path:
                                    confirmed_legacy_match = True
                            else:
                                ambiguous_legacy_match = True
                        if confirmed_legacy_match:
                            log.debug(
                                "Event already exists under a matching legacy id and file path"
                            )
                            continue
                        if ambiguous_legacy_match:
                            log.warning(
                                "UNVERIFIED_LEGACY_IDENTITY: a derived legacy id matched "
                                "but both file paths are not available; preserving the "
                                "source record and blocking the checkpoint"
                            )
                            skipped_count += 1
                            continue
                        # Every legacy alias hit has a different recorded path, so
                        # it cannot suppress this distinct capture; let the current
                        # path-bound id reach the Journal unique constraint below.

                    # A record at or before the checkpoint is only skipped when it
                    # is a true replay.  Using `<=` dropped a record that shared a
                    # microsecond with the checkpoint: the checkpoint is the highest
                    # timestamp already imported, so equality means "possibly the
                    # same record", which the unique constraint above resolved.
                    if occ_us < watermark:
                        continue

                    self.repo.append_event(
                        event_id=normalized["event_id"],
                        raw_text=normalized["raw_text"],
                        occurred_at_utc_us=occ_us,
                        audio_ref=normalized.get("audio_ref"),
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
                        # Do not commit per record: the page must be one
                        # transaction (plan 7.2), or a page whose later record is
                        # invalid leaves the earlier ones committed.
                        commit=False,
                    )
                    imported_count += 1

            if len(items) < limit:
                drained = True
                break
            offset += limit

        # The checkpoint moves once, and only when the drain actually finished.
        # Hitting the page cap is *not* finishing: advancing then would skip every
        # record past the cap, because the next request's start_time would exclude
        # them.  Leaving the checkpoint alone keeps them reachable.
        drain_skipped_count = resumed_skip_count + skipped_count
        # T01: a bounded sweep below the checkpoint, so a record that arrived after
        # the checkpoint passed its timestamp is still discovered.  Runs on a
        # drained range only -- the incremental pages must be complete first, or
        # the sweep would race the pages still being read.
        if drained:
            imported_count += await self._reopen_sweep(watermark, limit)
        if drained and not drain_skipped_count and not open_quarantine and max_seen_ts > watermark:
            self.update_watermark(max_seen_ts)
        elif drained and (drain_skipped_count or open_quarantine):
            log.warning(
                "Screenpipe drain has %d skipped and %d open quarantined record(s); "
                "the checkpoint remains at %d so those records can be retried. "
                "Use abandon_quarantined_record() to close the range explicitly.",
                drain_skipped_count,
                self.repo.quarantine_summary()["open"],
                watermark,
            )
        if drained:
            self._clear_resume_state()

        if not drained:
            log.warning(
                "UNVERIFIED_SCREENPIPE_PAGINATION: drain stopped at page cap (%d); "
                "watermark remains %d and persisted offset %d will resume the range. "
                "Completeness across source mutations depends on stable ordering "
                "and membership, which requires the S4 real-source contract",
                self.MAX_PAGES,
                watermark,
                offset,
            )
            self._save_resume_state(offset, drain_skipped_count, watermark)
        if skipped_count:
            log.info("Screenpipe import skipped %d unimportable record(s)", skipped_count)
        if redacted_count:
            log.info("Screenpipe import applied %d source redaction(s)", redacted_count)
        return imported_count

    # --------------------------------------------------------------- T01 helpers
    def _record_key(self, item: dict[str, Any]) -> str:
        """A stable key for a source record that cannot be normalized.

        Derived from the source-supplied id when present; otherwise from the raw
        JSON, which is all that remains when the record is unusable.  The key is
        only for quarantine bookkeeping, never for the Journal's identity.
        """
        content = item.get("content") if isinstance(item.get("content"), dict) else {}
        raw_id = item.get("id") or content.get("id") or content.get("audio_chunk_id")
        if raw_id:
            return str(raw_id)
        return "sha256:" + hashlib.sha256(
            json.dumps(item, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]

    def _quarantine_record(self, item: dict[str, Any], reason: str) -> bool:
        """Record an unusable source record; return True while it still blocks.

        T01-R2: after ``QUARANTINE_ABANDON_AFTER`` attempts the record is left on
        record as abandoned, so the range can close instead of rescanning history
        forever.  The record is never imported and never deleted -- the gap stays
        visible with its reason and an abandon timestamp.
        """
        try:
            key = self._record_key(item)
            attempts = self.repo.record_quarantined_record(key, reason)
            if attempts >= self.QUARANTINE_ABANDON_AFTER:
                if self.repo.abandon_quarantined_record(key):
                    log.warning(
                        "T01 quarantine: record %s abandoned after %d attempts "
                        "(%s); the checkpoint may close past it",
                        key,
                        attempts,
                        reason,
                    )
                return False
            return True
        except Exception as exc:  # noqa: BLE001 - never let bookkeeping drop a record
            log.warning("T01 quarantine bookkeeping failed for a record: %s", exc)
            return True

    async def _reopen_sweep(self, watermark: int, limit: int) -> int:
        """Re-read a bounded window below the checkpoint and import what is missing.

        The checkpoint is monotonic, so a record whose timestamp is below it is
        excluded by the next incremental request.  This sweep asks the source for
        the range ``[watermark - REOPEN_WINDOW_US, watermark)`` and inserts only
        records that are not already stored -- deduplication makes it idempotent.
        """
        if watermark <= 0:
            return 0
        window_start = max(0, watermark - self.REOPEN_WINDOW_US)
        start_iso = datetime.fromtimestamp(window_start / 1_000_000, tz=timezone.utc).isoformat()
        end_iso = datetime.fromtimestamp(watermark / 1_000_000, tz=timezone.utc).isoformat()
        found = 0
        offset = 0
        for _page in range(self.MAX_PAGES):
            try:
                items = await self.client.search(
                    limit=limit, offset=offset, start_time=start_iso, end_time=end_iso
                )
            except TypeError:
                # A client that does not support `end_time` (older doubles, or a
                # build whose API surface is narrower) still supports the bounded
                # lower edge; the upper bound is then left to the `occ_us >= watermark`
                # guard below.
                items = await self.client.search(
                    limit=limit, offset=offset, start_time=start_iso
                )
            if not isinstance(items, list):
                raise ValueError("IMPORT_SCHEMA_UNSUPPORTED: Screenpipe search response must be a list")
            if not items:
                break
            with self.repo.conn:
                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("IMPORT_SCHEMA_UNSUPPORTED: Item must be a dictionary")
                    try:
                        normalized = normalize_screenpipe_audio_item(item)
                    except ValueError:
                        continue
                    occ_us = normalized["occurred_at_utc_us"]
                    if occ_us >= watermark:
                        continue
                    candidate_ids = [normalized["external_id"]] + list(
                        normalized.get("legacy_external_ids") or []
                    )
                    placeholders = ",".join("?" for _ in candidate_ids)
                    exists = self.repo.conn.execute(
                        f"SELECT 1 FROM events WHERE external_source = ? AND external_id IN ({placeholders})",
                        [normalized["external_source"], *candidate_ids],
                    ).fetchone()
                    if exists:
                        continue
                    self.repo.append_event(
                        event_id=normalized["event_id"],
                        raw_text=normalized["raw_text"],
                        occurred_at_utc_us=occ_us,
                        audio_ref=normalized.get("audio_ref"),
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
                        commit=False,
                    )
                    found += 1
            if len(items) < limit:
                break
            offset += limit
        if found:
            log.info("T01 reopen sweep recovered %d record(s) below the checkpoint", found)
        return found


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
