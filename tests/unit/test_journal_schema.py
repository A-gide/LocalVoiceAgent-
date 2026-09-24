"""Unit tests for Journal v2 schema and repository (PR-016).

Verifies Part 7.1 and Part 11 (PR-016):
1. Tables and views existence.
2. Immutability triggers: raw_text cannot be updated, revisions cannot be updated.
3. Atomic revisions and FTS synchronization.
4. Nullable confidence (None vs valid range [0, 1] vs invalid range).
5. Cascade deletion via foreign keys.
6. PrivacyDeletionService audited hard deletion with SHA-256 hashes.
7. Repository stats and history retrieval.
"""
from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

import pytest

from lva.journal.corrections import CorrectionService
from lva.journal.privacy_deletion import PrivacyDeletionService
from lva.journal.repository import JournalRepository
from lva.journal.schema import JOURNAL_SCHEMA_SQL, init_journal_db


@pytest.fixture
def repo() -> JournalRepository:
    return JournalRepository(":memory:")


def test_schema_tables_and_view_created(repo: JournalRepository):
    cur = repo.conn.cursor()
    tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    views = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()}

    expected_tables = {
        "sessions",
        "turns",
        "events",
        "event_revisions",
        "temporal_mentions",
        "import_checkpoints",
        "deletion_audit",
        "events_fts",
    }
    assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"
    assert "current_event_text" in views


def test_i06_raw_text_immutable_trigger(repo: JournalRepository):
    eid = str(uuid4())
    repo.append_event(event_id=eid, raw_text="原文本不可篡改", occurred_at_utc_us=1000)

    # Directly attempting to UPDATE raw_text must be aborted by trigger
    with pytest.raises(sqlite3.DatabaseError, match="Updating raw_text in events table is forbidden"):
        with repo.conn:
            repo.conn.execute("UPDATE events SET raw_text = '非法篡改' WHERE event_id = ?", (eid,))


def test_i06_event_revisions_immutable_trigger(repo: JournalRepository):
    eid = str(uuid4())
    repo.append_event(event_id=eid, raw_text="原文本", occurred_at_utc_us=1000)
    rev = repo.add_revision(event_id=eid, corrected_text="纠正版1", reason="typo")
    assert rev == 1

    # Attempting to UPDATE event_revisions must be aborted by trigger
    with pytest.raises(sqlite3.DatabaseError, match="Updating event_revisions is forbidden"):
        with repo.conn:
            repo.conn.execute(
                "UPDATE event_revisions SET corrected_text = '二次篡改' WHERE event_id = ?",
                (eid,),
            )


def test_atomic_revision_and_fts_sync(repo: JournalRepository):
    eid = str(uuid4())
    repo.append_event(event_id=eid, raw_text="明天做络合滴定", occurred_at_utc_us=1000)

    # Initial state
    ev = repo.get_event(eid)
    assert ev is not None
    assert ev["raw_text"] == "明天做络合滴定"
    assert ev["current_text"] == "明天做络合滴定"
    assert ev["current_revision"] == 0

    # Add revision
    rev = repo.add_revision(event_id=eid, corrected_text="明天做酸碱滴定", reason="user_correction")
    assert rev == 1

    # Verified current_text updated in view
    ev_updated = repo.get_event(eid)
    assert ev_updated["current_text"] == "明天做酸碱滴定"
    assert ev_updated["current_revision"] == 1
    assert ev_updated["raw_text"] == "明天做络合滴定"

    # FTS finds new corrected text
    hits = repo.search("酸碱滴定")
    assert len(hits) == 1
    assert hits[0]["event_id"] == eid


def test_nullable_confidence_constraint(repo: JournalRepository):
    # None confidence is allowed and stored as NULL
    eid1 = str(uuid4())
    repo.append_event(event_id=eid1, raw_text="无置信度文本", confidence=None)
    ev1 = repo.get_event(eid1)
    assert ev1["confidence"] is None

    # Valid confidence in [0.0, 1.0]
    eid2 = str(uuid4())
    repo.append_event(event_id=eid2, raw_text="有置信度文本", confidence=0.85)
    ev2 = repo.get_event(eid2)
    assert ev2["confidence"] == 0.85

    # Negative confidence violates CHECK constraint
    eid3 = str(uuid4())
    with pytest.raises(sqlite3.IntegrityError):
        with repo.conn:
            repo.append_event(event_id=eid3, raw_text="非法负置信度", confidence=-0.1)

    # Confidence > 1.0 violates CHECK constraint
    eid4 = str(uuid4())
    with pytest.raises(sqlite3.IntegrityError):
        with repo.conn:
            repo.append_event(event_id=eid4, raw_text="非法超限置信度", confidence=1.5)


def test_cascade_deletion(repo: JournalRepository):
    eid = str(uuid4())
    repo.append_event(event_id=eid, raw_text="明天开会复盘", occurred_at_utc_us=1000)
    repo.add_revision(event_id=eid, corrected_text="明天上午开会", reason="time_adjust")

    # Verify revision and temporal mentions exist
    cur = repo.conn.cursor()
    rev_count = cur.execute("SELECT COUNT(*) FROM event_revisions WHERE event_id = ?", (eid,)).fetchone()[0]
    mention_count = cur.execute("SELECT COUNT(*) FROM temporal_mentions WHERE event_id = ?", (eid,)).fetchone()[0]
    assert rev_count == 1
    assert mention_count > 0

    # Delete parent event directly with foreign_keys=ON
    with repo.conn:
        repo.conn.execute("DELETE FROM events WHERE event_id = ?", (eid,))

    # Child rows must be cascaded
    rev_count_after = cur.execute("SELECT COUNT(*) FROM event_revisions WHERE event_id = ?", (eid,)).fetchone()[0]
    mention_count_after = cur.execute("SELECT COUNT(*) FROM temporal_mentions WHERE event_id = ?", (eid,)).fetchone()[0]
    assert rev_count_after == 0
    assert mention_count_after == 0


def test_privacy_deletion_service_audit(repo: JournalRepository):
    service = PrivacyDeletionService(repo)
    eid1 = str(uuid4())
    eid2 = str(uuid4())
    repo.append_event(event_id=eid1, raw_text="机密私人对话内容1")
    repo.append_event(event_id=eid2, raw_text="机密私人对话内容2")

    deleted_count = service.hard_delete_events([eid1, eid2], reason_code="user_gdpr_request")
    assert deleted_count == 2

    # Events are gone from events and FTS
    assert repo.get_event(eid1) is None
    assert repo.get_event(eid2) is None
    assert len(repo.search("机密私人对话")) == 0

    # Audit record exists and does NOT contain the raw text
    cur = repo.conn.cursor()
    audit_row = cur.execute("SELECT * FROM deletion_audit ORDER BY requested_at_utc_us DESC LIMIT 1").fetchone()
    assert audit_row is not None
    assert audit_row["deleted_count"] == 2
    assert audit_row["reason_code"] == "user_gdpr_request"

    hashes = json.loads(audit_row["event_id_hashes_json"])
    assert len(hashes) == 2
    # Verify no raw text is stored in audit
    audit_dump = str(dict(audit_row))
    assert "机密私人对话" not in audit_dump


def test_repository_stats(repo: JournalRepository):
    initial_stats = repo.stats()
    assert initial_stats["events"] == 0

    eid = str(uuid4())
    repo.append_event(event_id=eid, raw_text="测试统计计数", occurred_at_utc_us=1000)
    repo.add_revision(event_id=eid, corrected_text="测试统计计数纠正版", reason="fix")

    new_stats = repo.stats()
    assert new_stats["events"] == 1
    assert new_stats["revisions"] == 1


def test_privacy_deletion_actual_count_matches_existing_rows(repo: JournalRepository):
    service = PrivacyDeletionService(repo)
    eid_existing = str(uuid4())
    eid_missing = str(uuid4())
    repo.append_event(event_id=eid_existing, raw_text="真实存在的记录")

    # Request deletion of 2 IDs, but only 1 exists
    deleted_count = service.hard_delete_events([eid_existing, eid_missing], reason_code="partial_delete")
    assert deleted_count == 1

    # Verify audit record records deleted_count == 1 (not 2)
    cur = repo.conn.cursor()
    audit_row = cur.execute("SELECT * FROM deletion_audit ORDER BY requested_at_utc_us DESC LIMIT 1").fetchone()
    assert audit_row is not None
    assert audit_row["deleted_count"] == 1

