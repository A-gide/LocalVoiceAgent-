from __future__ import annotations

import contextlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any
from uuid import UUID

from .recall import TemporalRecallEngine, _segment_text
from .schema import init_journal_db
from .temporal import (
    extract_mentions,
)

log = logging.getLogger("lva.journal.repository")


def _resolve_timezone(tz_name: str | None = None, offset_mins: int | None = None) -> Any:
    """Resolve timezone object from name (ZoneInfo) or offset minutes per Part 7.1/7.3."""
    if tz_name and tz_name != "UTC":
        try:
            import zoneinfo
            return zoneinfo.ZoneInfo(tz_name)
        except Exception:
            pass
    if offset_mins:
        return timezone(timedelta(minutes=offset_mins))
    return timezone.utc


class JournalRepository:
    def __init__(
        self,
        db_path: str | Path | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        if conn is not None:
            self.conn = conn
        elif db_path is not None:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(path), check_same_thread=False)
        else:
            self.conn = sqlite3.connect(":memory:", check_same_thread=False)

        self.conn.row_factory = sqlite3.Row
        init_journal_db(self.conn)
        self.recall_engine = TemporalRecallEngine(self.conn)


    def create_session(
        self,
        session_id: str | UUID,
        started_at_utc_us: int | None = None,
        source: str = "core",
    ) -> None:
        if started_at_utc_us is None:
            started_at_utc_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO sessions (session_id, started_at_utc_us, source)
                VALUES (?, ?, ?)
                """,
                (str(session_id), started_at_utc_us, source),
            )

    def create_turn(
        self,
        session_id: str | UUID,
        turn_sequence: int,
        started_at_utc_us: int | None = None,
        status: str = "started",
    ) -> None:
        if started_at_utc_us is None:
            started_at_utc_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        self.create_session(session_id, started_at_utc_us=started_at_utc_us)
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO turns (session_id, turn_sequence, started_at_utc_us, status)
                VALUES (?, ?, ?, ?)
                """,
                (str(session_id), turn_sequence, started_at_utc_us, status),
            )

    def append_event(
        self,
        event_id: str | UUID,
        raw_text: str,
        occurred_at_utc_us: int | None = None,
        session_id: str | UUID | None = None,
        turn_sequence: int | None = None,
        speaker: str | None = "user",
        source: str = "core",
        event_timezone: str = "UTC",
        utc_offset_minutes: int = 0,
        started_at_utc_us: int | None = None,
        ended_at_utc_us: int | None = None,
        audio_ref: str | None = None,
        asr_provider: str | None = None,
        asr_model: str | None = None,
        confidence: float | None = None,
        domain: str | None = None,
        provenance: dict[str, Any] | None = None,
        external_source: str | None = None,
        external_id: str | None = None,
        commit: bool = True,
    ) -> str:
        """Insert one event and return its id.

        ``commit=False`` leaves the surrounding transaction open so a batch caller
        (the Screenpipe importer) can make a whole page atomic.  Without it the
        inner ``with self.conn`` committed the caller's transaction: a page whose
        second record was invalid left the first one committed, so the page was
        never one unit of work (plan 7.2 "每页导入在一个 transaction 中完成").
        """
        eid = str(event_id)
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        occ_us = occurred_at_utc_us if occurred_at_utc_us is not None else now_us

        if session_id and turn_sequence:
            self.create_turn(session_id, turn_sequence, started_at_utc_us=occ_us)

        provenance_json = json.dumps(provenance or {}, ensure_ascii=False)

        with self.conn if commit else contextlib.nullcontext():
            self.conn.execute(
                """
                INSERT INTO events (
                    event_id, session_id, turn_sequence, external_source, external_id,
                    occurred_at_utc_us, event_timezone, utc_offset_minutes,
                    started_at_utc_us, ended_at_utc_us, speaker, source, raw_text,
                    current_revision, audio_ref, asr_provider, asr_model,
                    confidence, domain, provenance_json, created_at_utc_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eid,
                    str(session_id) if session_id else None,
                    turn_sequence,
                    external_source,
                    external_id,
                    occ_us,
                    event_timezone,
                    utc_offset_minutes,
                    started_at_utc_us,
                    ended_at_utc_us,
                    speaker,
                    source,
                    raw_text,
                    audio_ref,
                    asr_provider,
                    asr_model,
                    confidence,
                    domain,
                    provenance_json,
                    now_us,
                ),
            )

            # Insert into FTS5
            seg = _segment_text(raw_text)
            self.conn.execute(
                "INSERT INTO events_fts (event_id, corrected_seg, raw_seg) VALUES (?, ?, ?)",
                (eid, seg, seg),
            )

            # Extract temporal mentions using event timestamp and timezone as anchor
            tz = _resolve_timezone(event_timezone, utc_offset_minutes)
            event_dt = datetime.fromtimestamp(occ_us / 1_000_000, tz=tz)
            mentions = extract_mentions(raw_text, event_dt)
            for m in mentions:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO temporal_mentions (
                        event_id, revision, mention_index, span_start, span_end,
                        expression, anchor_utc_us, range_start_utc_us,
                        range_end_utc_us, parser_version, parse_status
                    ) VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        eid,
                        m["mention_index"],
                        m["span_start"],
                        m["span_end"],
                        m["expression"],
                        m["anchor_utc_us"],
                        m["range_start_utc_us"],
                        m["range_end_utc_us"],
                        m["parser_version"],
                        m["parse_status"],
                    ),
                )

        return eid

    def apply_source_redaction(
        self,
        external_source: str,
        external_id: str,
        *,
        redacted_text: str = "[REDACTED]",
        commit: bool = True,
    ) -> bool:
        """Apply a source's later redaction mark to an event already stored.

        Plan L896 requires the importer to respect source redaction/deletion marks,
        and I06 forbids rewriting ``raw_text``.  Both hold here: the raw transcript
        stays exactly as captured (it is what proves what was received), and the
        redaction is recorded as a **new revision** so ``current_text`` -- the only
        text search and the UI read -- becomes the redacted form.

        Returns True when a revision was added, False when there was nothing to do
        (no such event, or it is already redacted), so a caller can report honestly.
        """
        row = self.conn.execute(
            """
            SELECT e.event_id, e.current_revision, e.raw_text, v.current_text
            FROM events e
            LEFT JOIN current_event_text v ON v.event_id = e.event_id
            WHERE e.external_source = ? AND e.external_id = ?
            """,
            (external_source, external_id),
        ).fetchone()
        if row is None:
            return False
        if (row["current_text"] or "") == redacted_text:
            return False

        event_id = row["event_id"]
        revision = int(row["current_revision"] or 0)
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)

        with self.conn if commit else contextlib.nullcontext():
            self.conn.execute(
                """
                INSERT INTO event_revisions (
                    event_id, revision, corrected_text, reason, actor, created_at_utc_us
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    revision + 1,
                    redacted_text,
                    "source_redaction",
                    "screenpipe_importer",
                    now_us,
                ),
            )
            self.conn.execute(
                "UPDATE events SET current_revision = ? WHERE event_id = ?",
                (revision + 1, event_id),
            )
            # The FTS row mirrors what is searchable, so it follows the revision
            # rather than the immutable raw text.
            seg = _segment_text(redacted_text)
            self.conn.execute(
                "UPDATE events_fts SET corrected_seg = ?, raw_seg = ? WHERE event_id = ?",
                (seg, seg, event_id),
            )
        return True

    create_event = append_event

    def add_revision(
        self,
        event_id: str | UUID,
        corrected_text: str,
        reason: str,
        actor: str = "user",
        rules_version: str | None = None,
    ) -> int:
        eid = str(event_id)
        now_us = int(datetime.now(timezone.utc).timestamp() * 1_000_000)

        with self.conn:
            # Get current revision and raw_text
            cur = self.conn.execute(
                "SELECT current_revision, occurred_at_utc_us, raw_text, event_timezone, utc_offset_minutes FROM events WHERE event_id = ?",
                (eid,),
            )
            row = cur.fetchone()
            if not row:
                raise KeyError(f"Event '{eid}' not found in Journal")

            current_rev = row["current_revision"]
            occ_us = row["occurred_at_utc_us"]
            raw_text = row["raw_text"]
            ev_tz = row["event_timezone"]
            ev_offset = row["utc_offset_minutes"]
            new_rev = current_rev + 1

            # Insert revision
            self.conn.execute(
                """
                INSERT INTO event_revisions (
                    event_id, revision, corrected_text, rules_version,
                    reason, actor, created_at_utc_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (eid, new_rev, corrected_text, rules_version, reason, actor, now_us),
            )

            # Update current revision on events table
            self.conn.execute(
                "UPDATE events SET current_revision = ? WHERE event_id = ?",
                (new_rev, eid),
            )

            # Update FTS5 atomically
            self.conn.execute("DELETE FROM events_fts WHERE event_id = ?", (eid,))
            raw_seg = _segment_text(raw_text)
            corr_seg = _segment_text(corrected_text)
            self.conn.execute(
                "INSERT INTO events_fts (event_id, corrected_seg, raw_seg) VALUES (?, ?, ?)",
                (eid, corr_seg, raw_seg),
            )

            # Extract temporal mentions for the corrected revision
            tz = _resolve_timezone(ev_tz, ev_offset)
            event_dt = datetime.fromtimestamp(occ_us / 1_000_000, tz=tz)
            mentions = extract_mentions(corrected_text, event_dt)
            for m in mentions:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO temporal_mentions (
                        event_id, revision, mention_index, span_start, span_end,
                        expression, anchor_utc_us, range_start_utc_us,
                        range_end_utc_us, parser_version, parse_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        eid,
                        new_rev,
                        m["mention_index"],
                        m["span_start"],
                        m["span_end"],
                        m["expression"],
                        m["anchor_utc_us"],
                        m["range_start_utc_us"],
                        m["range_end_utc_us"],
                        m["parser_version"],
                        m["parse_status"],
                    ),
                )

        return new_rev

    def search(
        self,
        query: str,
        query_anchor: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search journal with dual-anchor temporal filtering via TemporalRecallEngine."""
        return self.recall_engine.search(query, query_anchor=query_anchor, limit=limit)

    def format_history_context(self, hits: list[dict[str, Any]]) -> str:
        """Format recalled events into a prompt memory context block."""
        return self.recall_engine.format_history_context(hits)

    def get_event(self, event_id: str | UUID) -> dict[str, Any] | None:
        cur = self.conn.execute(
            "SELECT * FROM current_event_text WHERE event_id = ?",
            (str(event_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_revisions(self, event_id: str | UUID) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM event_revisions WHERE event_id = ? ORDER BY revision ASC",
            (str(event_id),),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_history(self, event_id: str | UUID) -> Any | None:
        """Fetch full event history with revisions and temporal mentions (PR-019 UI DTO)."""
        return self.recall_engine.get_event_history(event_id)

    def stats(self) -> dict[str, Any]:
        """Return counts of events, sessions, turns, revisions, and temporal mentions (PR-016)."""
        cur = self.conn.cursor()
        events_cnt = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        sessions_cnt = cur.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        turns_cnt = cur.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        revs_cnt = cur.execute("SELECT COUNT(*) FROM event_revisions").fetchone()[0]
        mentions_cnt = cur.execute("SELECT COUNT(*) FROM temporal_mentions").fetchone()[0]
        return {
            "events": events_cnt,
            "sessions": sessions_cnt,
            "turns": turns_cnt,
            "revisions": revs_cnt,
            "temporal_mentions": mentions_cnt,
        }
