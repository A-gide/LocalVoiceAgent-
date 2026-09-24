from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from .models import EventHistoryDTO, RevisionHistoryDTO, TemporalMention
from .temporal import (
    clean_search_query,
    extract_query_temporal_range,
)

log = logging.getLogger("lva.journal.recall")


def _segment_text(text: str) -> str:
    """Whitespace tokenization for SQLite FTS unicode61 CJK indexing."""
    chars = []
    for c in text:
        if ("\u4e00" <= c <= "\u9fff") or ("\u3400" <= c <= "\u4dbf") or ("\uf900" <= c <= "\ufaff"):
            chars.append(f" {c} ")
        else:
            chars.append(c)
    return " ".join("".join(chars).split())


def _fts_query(text: str) -> str:
    """Construct FTS5 query with quoted phrase syntax for accurate token matching."""
    terms = text.strip().split()
    if not terms:
        return ""
    phrases = []
    for term in terms:
        seg = _segment_text(term)
        if seg:
            escaped = seg.replace('"', '""')
            phrases.append(f'"{escaped}"')
    return " AND ".join(phrases) if phrases else '""'


class TemporalRecallEngine:
    """Recall engine providing dual-anchor temporal query routing and FTS search (PR-019)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def search(
        self,
        query: str,
        query_anchor: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search journal with dual-anchor temporal filtering.

        1. If query contains relative time expressions ("昨天", "今天"), filters by that range.
           Range matches either event occurred_at_utc_us OR current revision temporal_mentions range.
        2. If query only asks a generic question anchored in time ("我昨天说了什么？"),
           returns events purely by temporal filter.
        3. If parsing fails or no expression is present: searches the entire Journal without
           arbitrarily restricting to "last N hours" (Part 7.3).
        """
        temp_res = extract_query_temporal_range(query, query_anchor)
        time_filter = ""
        params: list[Any] = []
        matched_expr = None

        if temp_res is not None:
            start_dt, end_dt, matched_expr = temp_res
            start_us = int(start_dt.timestamp() * 1_000_000)
            end_us = int(end_dt.timestamp() * 1_000_000)
            time_filter = """
                AND (
                    (e.occurred_at_utc_us BETWEEN ? AND ?)
                    OR EXISTS (
                        SELECT 1 FROM temporal_mentions tm
                        WHERE tm.event_id = e.event_id
                          AND tm.revision = e.current_revision
                          AND tm.range_start_utc_us <= ? AND tm.range_end_utc_us >= ?
                    )
                )
            """
            params.extend([start_us, end_us, end_us, start_us])
            log.debug("Temporal filter applied: %s -> [%s, %s]", matched_expr, start_dt, end_dt)

        if temp_res is not None:
            clean_kw = clean_search_query(query, matched_expr)
            if not clean_kw:
                # Query is purely temporal (e.g. "我昨天说了什么？", "今天的安排")
                sql = f"""
                    SELECT e.event_id, e.occurred_at_utc_us, e.speaker, e.source,
                           e.raw_text, e.current_text, e.current_revision, e.confidence, e.domain,
                           e.utc_offset_minutes
                    FROM current_event_text e
                    WHERE 1=1
                    {time_filter}
                    ORDER BY e.occurred_at_utc_us DESC
                    LIMIT ?
                """
                query_params = params + [limit]
                cur = self.conn.execute(sql, query_params)
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            search_target = clean_kw
        else:
            search_target = query

        fts_q = _fts_query(search_target)
        sql = f"""
            SELECT e.event_id, e.occurred_at_utc_us, e.speaker, e.source,
                   e.raw_text, e.current_text, e.current_revision, e.confidence, e.domain,
                   e.utc_offset_minutes
            FROM current_event_text e
            WHERE (
                e.event_id IN (
                    SELECT event_id FROM events_fts WHERE events_fts MATCH ?
                )
                OR e.current_text LIKE ?
            )
            {time_filter}
            ORDER BY e.occurred_at_utc_us DESC
            LIMIT ?
        """
        query_params = [fts_q, f"%{search_target}%"] + params + [limit]

        try:
            cur = self.conn.execute(sql, query_params)
            rows = cur.fetchall()
        except sqlite3.OperationalError:
            # Fallback if FTS match syntax errors
            fallback_sql = f"""
                SELECT e.event_id, e.occurred_at_utc_us, e.speaker, e.source,
                       e.raw_text, e.current_text, e.current_revision, e.confidence, e.domain,
                       e.utc_offset_minutes
                FROM current_event_text e
                WHERE e.current_text LIKE ?
                {time_filter}
                ORDER BY e.occurred_at_utc_us DESC
                LIMIT ?
            """
            cur = self.conn.execute(fallback_sql, [f"%{search_target}%"] + params + [limit])
            rows = cur.fetchall()

        return [dict(r) for r in rows]

    def format_history_context(self, hits: list[dict[str, Any]]) -> str:
        """Format recalled events into a prompt memory context block."""
        lines = []
        for h in hits:
            dt_str = ""
            ts_us = h.get("occurred_at_utc_us")
            if ts_us:
                offset_mins = h.get("utc_offset_minutes") or 0
                tz = timezone(timedelta(minutes=offset_mins)) if offset_mins != 0 else timezone.utc
                dt = datetime.fromtimestamp(ts_us / 1_000_000, tz=tz)
                dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            speaker = h.get("speaker") or "user"
            text = h.get("current_text") or h.get("raw_text") or ""
            lines.append(f"[{dt_str}] {speaker}: {text}")
        return "\n".join(lines)

    def get_event_history(self, event_id: str | UUID) -> EventHistoryDTO | None:
        """Fetch full event history with revisions and temporal mentions (PR-019 UI DTO)."""
        eid = str(event_id)
        cur = self.conn.execute(
            "SELECT * FROM current_event_text WHERE event_id = ?",
            (eid,),
        )
        row = cur.fetchone()
        if not row:
            return None

        # Fetch revisions
        cur_rev = self.conn.execute(
            "SELECT * FROM event_revisions WHERE event_id = ? ORDER BY revision ASC",
            (eid,),
        )
        revisions = [
            RevisionHistoryDTO(
                revision=r["revision"],
                corrected_text=r["corrected_text"],
                reason=r["reason"],
                actor=r["actor"],
                rules_version=r["rules_version"],
                created_at_utc_us=r["created_at_utc_us"],
            )
            for r in cur_rev.fetchall()
        ]

        # Fetch temporal mentions
        cur_men = self.conn.execute(
            "SELECT * FROM temporal_mentions WHERE event_id = ? ORDER BY revision ASC, mention_index ASC",
            (eid,),
        )
        mentions = [
            TemporalMention(
                event_id=UUID(r["event_id"]),
                revision=r["revision"],
                mention_index=r["mention_index"],
                span_start=r["span_start"],
                span_end=r["span_end"],
                expression=r["expression"],
                anchor_utc_us=r["anchor_utc_us"],
                range_start_utc_us=r["range_start_utc_us"],
                range_end_utc_us=r["range_end_utc_us"],
                parser_version=r["parser_version"],
                parse_status=r["parse_status"],
            )
            for r in cur_men.fetchall()
        ]

        return EventHistoryDTO(
            event_id=UUID(row["event_id"]),
            raw_text=row["raw_text"],
            current_text=row["current_text"],
            current_revision=row["current_revision"],
            occurred_at_utc_us=row["occurred_at_utc_us"],
            event_timezone=row["event_timezone"],
            speaker=row["speaker"],
            source=row["source"],
            domain=row["domain"],
            confidence=row["confidence"],
            revisions=revisions,
            temporal_mentions=mentions,
        )
