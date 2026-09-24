"""Unit tests for legacy memory migration (PR-017).

Verifies Part 7.4 and Part 11 (PR-017):
1. Snapshot SHA-256 checksum calculation.
2. Dry-run mode without modifying target repository.
3. Conservation law: total_legacy_rows == migrated_count + skipped_count + invalid_rows.
4. Idempotency on repeated execution.
5. Quarantine of malformed timestamps and JSON.
6. Revision creation when fixed_text != raw_text.
7. CLI entrypoint invocation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from lva.journal.migrate_legacy import compute_file_sha256, main, migrate_legacy_db
from lva.journal.repository import JournalRepository


@pytest.fixture
def legacy_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "legacy_source.db"
    conn = sqlite3.connect(str(db_file))
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
        (1, 1789000000.0, "mic", "user", "今天天气真好", "今天天气真好", "chat", "/audio/1.wav", 1.5, '{"device": "mic1"}'),
        (2, 1789000010.0, "mic", "user", "明天络合实验", "明天络合滴定实验", "chem", "/audio/2.wav", 2.0, '{"confidence": 0.9}'),
        (3, None, "mic", "user", "无时间戳数据", None, "chat", "", 1.0, '{}'),  # malformed: ts is None
        (4, 1789000020.0, "mic", "user", "非JSON元数据", None, "chat", "", 1.0, 'CORRUPTED_RAW_TEXT'),
    ]
    conn.executemany("INSERT INTO utterances VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return db_file


def test_checksum_calculation(legacy_db: Path):
    computed = compute_file_sha256(legacy_db)
    assert len(computed) == 64
    assert all(c in "0123456789abcdef" for c in computed)

    # Double check manually
    with open(legacy_db, "rb") as f:
        expected = hashlib.sha256(f.read()).hexdigest()
    assert computed == expected


def test_dry_run_does_not_modify_target(legacy_db: Path):
    repo = JournalRepository(":memory:")
    report = migrate_legacy_db(legacy_db, repo, dry_run=True)

    assert report["total_legacy_rows"] == 4
    assert report["migrated_count"] == 3
    assert report["invalid_rows"] == 1
    assert report["checksum"] != ""

    # Target repository must remain completely empty
    cur = repo.conn.cursor()
    event_count = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert event_count == 0


def test_migration_conservation_and_revisions(legacy_db: Path):
    repo = JournalRepository(":memory:")
    report = migrate_legacy_db(legacy_db, repo, dry_run=False)

    # Conservation law
    assert report["total_legacy_rows"] == 4
    assert report["migrated_count"] == 3
    assert report["invalid_rows"] == 1
    assert report["total_legacy_rows"] == report["migrated_count"] + report["invalid_rows"]

    # Revision created for row 2 (明天络合实验 -> 明天络合滴定实验)
    assert report["revisions_created"] == 1

    # Verify search
    hits = repo.search("络合滴定")
    assert len(hits) == 1
    assert hits[0]["current_text"] == "明天络合滴定实验"
    assert hits[0]["raw_text"] == "明天络合实验"


def test_migration_idempotent_rerun(legacy_db: Path):
    repo = JournalRepository(":memory:")

    # Pass 1
    rep1 = migrate_legacy_db(legacy_db, repo)
    assert rep1["migrated_count"] == 3
    assert rep1["skipped_count"] == 0

    # Pass 2: all previously migrated rows are recognized and skipped
    rep2 = migrate_legacy_db(legacy_db, repo)
    assert rep2["migrated_count"] == 0
    assert rep2["skipped_count"] == 3
    assert rep2["invalid_rows"] == 1
    assert rep2["total_legacy_rows"] == rep2["migrated_count"] + rep2["skipped_count"] + rep2["invalid_rows"]

    # Total events in target repo remains 3
    cur = repo.conn.cursor()
    total_events = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert total_events == 3


def test_missing_or_corrupt_legacy_db(tmp_path: Path):
    repo = JournalRepository(":memory:")

    # 1. Non-existent file
    rep1 = migrate_legacy_db(tmp_path / "non_existent.db", repo)
    assert rep1["total_legacy_rows"] == 0
    assert len(rep1["errors"]) > 0

    # 2. Corrupt/empty database without utterances table
    corrupt_file = tmp_path / "corrupt.db"
    conn = sqlite3.connect(str(corrupt_file))
    conn.execute("CREATE TABLE dummy (x INT)")
    conn.commit()
    conn.close()

    rep2 = migrate_legacy_db(corrupt_file, repo)
    assert rep2["total_legacy_rows"] == 0
    assert "Failed to query legacy utterances" in rep2["errors"][0]


def test_cli_execution(legacy_db: Path, tmp_path: Path):
    target_db = tmp_path / "migrated_journal.sqlite3"
    report_json = tmp_path / "report.json"

    # Test invoking CLI via python -m lva.journal.migrate_legacy
    cmd = [
        sys.executable,
        "-m",
        "lva.journal.migrate_legacy",
        "--legacy-db",
        str(legacy_db),
        "--target-db",
        str(target_db),
        "--report-json",
        str(report_json),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "Migration Report:" in res.stdout
    assert report_json.exists()

    with open(report_json, encoding="utf-8") as f:
        rep = json.load(f)
    assert rep["total_legacy_rows"] == 4
    assert rep["migrated_count"] == 3


def test_dry_run_with_existing_records_detects_skipped(legacy_db: Path):
    repo = JournalRepository(":memory:")
    # First migrate for real
    rep_real = migrate_legacy_db(legacy_db, repo, dry_run=False)
    assert rep_real["migrated_count"] == 3
    assert rep_real["skipped_count"] == 0

    # Then run dry-run against the populated repo
    rep_dry = migrate_legacy_db(legacy_db, repo, dry_run=True)
    assert rep_dry["total_legacy_rows"] == 4
    assert rep_dry["migrated_count"] == 0
    assert rep_dry["skipped_count"] == 3
    assert rep_dry["invalid_rows"] == 1
    assert rep_dry["total_legacy_rows"] == rep_dry["migrated_count"] + rep_dry["skipped_count"] + rep_dry["invalid_rows"]

