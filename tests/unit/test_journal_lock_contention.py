"""PR-016 open boundary: multi-connection write contention (plan L1297).

The formal acceptance record for PR-016 (docs/PR-016-019-FORMAL-ACCEPTANCE-2026-09-24.md)
left one acceptance item partially covered:

    "DB lock rollback" -- atomicity rollback is covered by
    test_atomic_revision_and_fts_sync, but there is no test for *lock contention*
    between connections.  tests/unit had zero lock/rollback hits and
    repository.py had no explicit ROLLBACK / IntegrityError handling.

This file closes that boundary with evidence rather than an assertion of intent.
It drives the real repository, not a stand-in.

What it establishes:

1. the repository is a **single writer**: a second connection cannot interleave a
   write into the middle of a revision transaction;
2. when the second writer does lose the race, SQLite raises `database is locked`
   and **the loser leaves no partial state behind** -- that is the rollback the
   acceptance item asks about;
3. the winner's transaction is intact and readable by the loser afterwards.

Boundary of this evidence (stated, not implied): SQLite locking is what is being
exercised, so the test is about *contention handling*, not about a claim that the
product runs two writers.  The product does not: `JournalRepository` opens one
connection and Core is its only caller.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from lva.journal.repository import JournalRepository


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "journal-lock.db"


@pytest.fixture
def repo(db_path: Path) -> JournalRepository:
    return JournalRepository(db_path)


def _other_connection(db_path: Path) -> sqlite3.Connection:
    """A second connection to the same file, as another process would open it."""
    conn = sqlite3.connect(str(db_path), timeout=0.2, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def test_a_second_writer_cannot_steal_an_open_transaction(repo: JournalRepository, db_path: Path) -> None:
    """While the repository holds a write transaction, the other writer waits."""
    event_id = uuid4()
    repo.conn.execute("BEGIN IMMEDIATE")
    repo.conn.execute(
        """
        INSERT INTO events (event_id, raw_text, occurred_at_utc_us, speaker, source,
                            current_revision, created_at_utc_us)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (str(event_id), "第一个写入者", 1_000_000, "user", "core", 1_000_000),
    )

    other = _other_connection(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError) as excinfo:
            with other:
                other.execute(
                    """
                    INSERT INTO events (event_id, raw_text, occurred_at_utc_us,
                                        speaker, source, current_revision,
                                        created_at_utc_us)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (str(uuid4()), "第二个写入者", 2_000_000, "user", "core", 2_000_000),
                )
        assert "locked" in str(excinfo.value).lower(), (
            "the contending writer must be refused by the lock, not silently accepted"
        )
    finally:
        other.close()

    repo.conn.commit()


def test_the_losing_writer_leaves_no_partial_state(repo: JournalRepository, db_path: Path) -> None:
    """The refused write must roll back completely (the acceptance item)."""
    repo.conn.execute("BEGIN IMMEDIATE")
    repo.conn.execute(
        """
        INSERT INTO events (event_id, raw_text, occurred_at_utc_us, speaker, source,
                            current_revision, created_at_utc_us)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (str(uuid4()), "赢家写入", 1_000_000, "user", "core", 1_000_000),
    )

    loser_text = "输家写入"
    other = _other_connection(db_path)
    try:
        try:
            with other:
                other.execute(
                    """
                    INSERT INTO events (event_id, raw_text, occurred_at_utc_us,
                                        speaker, source, current_revision,
                                        created_at_utc_us)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (str(uuid4()), loser_text, 2_000_000, "user", "core", 2_000_000),
                )
        except sqlite3.OperationalError:
            pass  # the expected outcome; asserted below
    finally:
        other.close()

    repo.conn.commit()

    rows = repo.conn.execute(
        "SELECT raw_text FROM events ORDER BY occurred_at_utc_us"
    ).fetchall()
    texts = [row["raw_text"] for row in rows]
    assert texts == ["赢家写入"], (
        f"the losing writer must leave nothing behind, found: {texts}"
    )


def test_the_winner_transaction_stays_readable_and_consistent(repo: JournalRepository, db_path: Path) -> None:
    """After contention the committed state is intact and FTS stays in sync."""
    event_id = uuid4()
    repo.append_event(
        event_id,
        # ASCII on purpose: the CJK tokenizer splits Chinese into single-character
        # tokens (see test_cjk_fts_phrase_query_precision), which is a separate
        # concern.  This test is about the *mirror* staying consistent, so it uses
        # text whose tokenisation cannot mask a lost update.
        "lock contention consistency",
        occurred_at_utc_us=1_000_000,
    )

    other = _other_connection(db_path)
    try:
        stored = other.execute(
            "SELECT raw_text, current_revision FROM events WHERE event_id = ?",
            (str(event_id),),
        ).fetchone()
        assert stored is not None
        assert stored["raw_text"] == "lock contention consistency"
        # A freshly appended event carries no revision yet: 0 means "raw text is
        # still authoritative" and the first correction makes it 1 (schema.py L40).
        assert stored["current_revision"] == 0

        # The FTS mirror must agree with the base table: a lost update would show
        # up here as a row that cannot be found through the index.
        hit = other.execute(
            "SELECT COUNT(*) AS n FROM events_fts WHERE events_fts MATCH ?",
            ("consistency",),
        ).fetchone()
        assert hit["n"] == 1, "the FTS index must mirror the committed row"
    finally:
        other.close()


def test_readers_are_not_blocked_by_a_writer_in_wal_mode(repo: JournalRepository, db_path: Path) -> None:
    """WAL is the mechanism that keeps a long write from stalling recall."""
    mode = repo.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal", "PR-016 requires WAL (plan L1295)"

    repo.append_event(uuid4(), "写入中可读", occurred_at_utc_us=1_000_000)

    repo.conn.execute("BEGIN IMMEDIATE")
    repo.conn.execute(
        """
        INSERT INTO events (event_id, raw_text, occurred_at_utc_us, speaker, source,
                            current_revision, created_at_utc_us)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (str(uuid4()), "未提交", 2_000_000, "user", "core", 2_000_000),
    )

    other = _other_connection(db_path)
    try:
        # A read must succeed while the write transaction is still open.
        seen = other.execute("SELECT COUNT(*) AS n FROM events").fetchone()
        assert seen["n"] == 1, (
            "a reader must see the committed state, not the uncommitted write"
        )
    finally:
        other.close()
    repo.conn.commit()
