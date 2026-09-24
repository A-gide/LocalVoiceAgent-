"""RED: v1.2.1 patch #5 - temporal mention identity.

Frozen rule (v1.2.1 §7.1):
* ``temporal_mentions`` is keyed by ``(event_id, revision, mention_index)``.
* ``mention_index`` counts occurrences of a temporal expression inside the
  current text revision, starting at 0.
* ``span_start`` / ``span_end`` are Unicode code-point offsets, half-open.
* The same expression may appear several times and MUST NOT be deduplicated by
  expression text.

Current implementation keys on ``(event_id, revision, expression)`` and has no
span columns, so "明天上午…明天下午…" collapses into one row.
"""
from __future__ import annotations

import sqlite3

import pytest

from lva.journal.repository import JournalRepository
from lva.journal.schema import JOURNAL_SCHEMA_SQL

pytestmark = pytest.mark.red_v121


def _columns(conn: sqlite3.Connection, table: str) -> dict[str, tuple]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1]: tuple(r) for r in rows}


def _pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    pk = sorted([(r[5], r[1]) for r in rows if r[5] > 0])
    return [name for _, name in pk]


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(JOURNAL_SCHEMA_SQL)
    yield c
    c.close()


def test_temporal_mentions_has_mention_index_and_spans(conn: sqlite3.Connection):
    cols = _columns(conn, "temporal_mentions")
    for required in ("mention_index", "span_start", "span_end"):
        assert required in cols, (
            f"v1.2.1 §7.1 requires temporal_mentions.{required}; "
            f"present columns: {sorted(cols)}"
        )


def test_temporal_mentions_pk_is_mention_index(conn: sqlite3.Connection):
    pk = _pk_columns(conn, "temporal_mentions")
    assert pk == ["event_id", "mention_index", "revision"], (
        "v1.2.1 §7.1 keys temporal_mentions by (event_id, revision, mention_index); "
        f"actual primary key: {pk}"
    )


def test_repeated_expression_produces_two_mentions(conn: sqlite3.Connection):
    """The same expression twice in one revision must yield two rows."""
    conn.execute(
        "INSERT INTO events(event_id, occurred_at_utc_us, source, raw_text, created_at_utc_us) "
        "VALUES ('e1', 1, 'test', '明天上午开会，明天下午复盘', 1)"
    )
    cols = _columns(conn, "temporal_mentions")
    assert "mention_index" in cols, "mention_index column missing (v1.2.1 §7.1)"

    insert = (
        "INSERT INTO temporal_mentions"
        "(event_id, revision, mention_index, span_start, span_end, expression,"
        " anchor_utc_us, parser_version, parse_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    conn.execute(insert, ("e1", 1, 0, 0, 2, "明天", 1, "v1", "parsed"))
    conn.execute(insert, ("e1", 1, 1, 7, 9, "明天", 1, "v1", "parsed"))
    conn.commit()

    n = conn.execute(
        "SELECT COUNT(*) FROM temporal_mentions WHERE event_id='e1' AND expression='明天'"
    ).fetchone()[0]
    assert n == 2, (
        "v1.2.1 §7.1 forbids deduplicating repeated expressions by text; "
        f"expected 2 rows for '明天', got {n}"
    )


def test_span_offsets_are_code_points():
    """Parser must emit code-point [start,end) offsets, not bytes."""
    from lva.journal import temporal as temporal_mod

    fn = getattr(temporal_mod, "extract_mentions", None)
    assert fn is not None, (
        "v1.2.1 §7.1/§7.3 requires a mention extractor returning "
        "mention_index + span_start/span_end; lva.journal.temporal has none"
    )
    mentions = fn("明天上午开会，明天下午复盘", anchor_utc_us=1_000_000)
    assert len(mentions) == 2, f"expected 2 mentions, got {len(mentions)}"
    idxs = sorted(m.get("mention_index") for m in mentions)
    assert idxs == [0, 1], f"mention_index must be 0,1; got {idxs}"
    for m in mentions:
        assert m["span_end"] > m["span_start"], "span must be half-open [start,end)"
        assert "明天" == "明天上午开会，明天下午复盘"[m["span_start"]:m["span_end"]]