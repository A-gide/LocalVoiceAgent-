"""Migration verification tests per Part 7.4 of the Architecture Plan.

Verifies:
1. Legacy SQLite schema migration into Journal v2 schema.
2. Robustness to corrupt/malformed data (NULL timestamps, invalid JSON).
3. Idempotent re-run: migrating twice produces identical row counts and no duplicates.
4. Conservation law: total_legacy_rows == migrated_count + invalid_rows.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lva.journal.migrate_legacy import migrate_legacy_db
from lva.journal.repository import JournalRepository


@pytest.fixture
def sample_legacy_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "legacy_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE utterances (
            id INTEGER PRIMARY KEY,
            ts REAL,
            source TEXT,
            speaker TEXT,
            raw_text TEXT,
            fixed_text TEXT,
            domain TEXT,
            audio_path TEXT,
            duration_s REAL,
            meta TEXT
        )
    """)
    rows = [
        (1, 1789000000.0, "mic", "user", "今天天气真好", "今天天气真好", "chat", "", 1.5, '{"device": "headset"}'),
        (2, 1789000010.0, "mic", "user", "明天络合实验", "明天络合滴定实验", "chem", "", 2.0, '{"confidence": 0.95}'),
        (3, None, "mic", "user", "无时间戳数据", None, "chat", "", 1.0, '{}'),  # invalid ts
        (4, 1789000020.0, "mic", "user", "非JSON元数据", None, "chat", "", 1.0, 'CORRUPTED_JSON'),
    ]
    conn.executemany("INSERT INTO utterances VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return db_path


def test_legacy_migration_conservation_and_revisions(sample_legacy_db: Path):
    """Verify legacy migration report accuracy, revision creation, and row conservation."""
    repo = JournalRepository()
    report = migrate_legacy_db(sample_legacy_db, repo)

    # Conservation: total == migrated + invalid
    assert report["total_legacy_rows"] == 4
    assert report["migrated_count"] == 3
    assert report["invalid_rows"] == 1
    assert report["total_legacy_rows"] == report["migrated_count"] + report["invalid_rows"]

    # One revision created for row 2 where fixed_text != raw_text
    assert report["revisions_created"] == 1

    # Search finds migrated and corrected text
    hits = repo.search("络合滴定")
    assert len(hits) == 1
    assert hits[0]["current_text"] == "明天络合滴定实验"
    assert hits[0]["raw_text"] == "明天络合实验"


def test_legacy_migration_idempotent(sample_legacy_db: Path):
    """Verify migrating twice is idempotent and does not produce duplicate rows."""
    repo = JournalRepository()

    # First run
    rep1 = migrate_legacy_db(sample_legacy_db, repo)
    assert rep1["migrated_count"] == 3

    # Second run into the same repository
    rep2 = migrate_legacy_db(sample_legacy_db, repo)
    # Events table has primary key constraint, duplicate imports are safely skipped or handled
    cursor = repo.conn.execute("SELECT COUNT(*) FROM events;")
    total_events = cursor.fetchone()[0]
    assert total_events == 3
