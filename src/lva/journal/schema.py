from __future__ import annotations

import sqlite3

JOURNAL_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  started_at_utc_us INTEGER NOT NULL,
  ended_at_utc_us INTEGER,
  source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
  session_id TEXT NOT NULL,
  turn_sequence INTEGER NOT NULL CHECK(turn_sequence >= 1),
  started_at_utc_us INTEGER NOT NULL,
  ended_at_utc_us INTEGER,
  status TEXT NOT NULL,
  PRIMARY KEY(session_id, turn_sequence),
  FOREIGN KEY(session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  session_id TEXT,
  turn_sequence INTEGER,
  external_source TEXT,
  external_id TEXT,
  occurred_at_utc_us INTEGER NOT NULL,
  event_timezone TEXT NOT NULL DEFAULT 'UTC',
  utc_offset_minutes INTEGER NOT NULL DEFAULT 0,
  started_at_utc_us INTEGER,
  ended_at_utc_us INTEGER,
  speaker TEXT,
  source TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  current_revision INTEGER NOT NULL DEFAULT 0,
  audio_ref TEXT,
  asr_provider TEXT,
  asr_model TEXT,
  confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  domain TEXT,
  provenance_json TEXT NOT NULL DEFAULT '{}',
  created_at_utc_us INTEGER NOT NULL,
  FOREIGN KEY(session_id, turn_sequence) REFERENCES turns(session_id, turn_sequence)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_events_external
  ON events(external_source, external_id)
  WHERE external_source IS NOT NULL AND external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS event_revisions (
  event_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK(revision >= 1),
  corrected_text TEXT NOT NULL,
  rules_version TEXT,
  reason TEXT NOT NULL,
  actor TEXT NOT NULL,
  created_at_utc_us INTEGER NOT NULL,
  PRIMARY KEY(event_id, revision),
  FOREIGN KEY(event_id) REFERENCES events(event_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS temporal_mentions (
  event_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  mention_index INTEGER NOT NULL CHECK(mention_index >= 0),
  span_start INTEGER NOT NULL CHECK(span_start >= 0),
  span_end INTEGER NOT NULL CHECK(span_end > span_start),
  expression TEXT NOT NULL,
  anchor_utc_us INTEGER NOT NULL,
  range_start_utc_us INTEGER,
  range_end_utc_us INTEGER,
  parser_version TEXT NOT NULL,
  parse_status TEXT NOT NULL,
  PRIMARY KEY(event_id, mention_index, revision),
  FOREIGN KEY(event_id) REFERENCES events(event_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS import_checkpoints (
  importer TEXT NOT NULL,
  external_source TEXT NOT NULL,
  cursor TEXT,
  watermark_utc_us INTEGER,
  source_schema_version TEXT,
  updated_at_utc_us INTEGER NOT NULL,
  PRIMARY KEY(importer, external_source)
);

CREATE TABLE IF NOT EXISTS deletion_audit (
  operation_id TEXT PRIMARY KEY,
  requested_at_utc_us INTEGER NOT NULL,
  completed_at_utc_us INTEGER,
  reason_code TEXT NOT NULL,
  event_id_hashes_json TEXT NOT NULL,
  deleted_count INTEGER NOT NULL
);

-- T01: a source record the importer could not use (missing/unparseable
-- timestamp, or an unverifiable source redaction).  It is recorded rather than
-- silently skipped, so the checkpoint can eventually close without losing the
-- fact that a record was left uncovered.  ``abandoned`` marks the explicit exit:
-- the range moved past it after repeated attempts and the gap is on record.
CREATE TABLE IF NOT EXISTS import_quarantine (
  importer TEXT NOT NULL,
  external_source TEXT NOT NULL,
  record_key TEXT NOT NULL,
  reason TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  abandoned INTEGER NOT NULL DEFAULT 0,
  first_seen_utc_us INTEGER NOT NULL,
  last_seen_utc_us INTEGER NOT NULL,
  abandoned_at_utc_us INTEGER,
  PRIMARY KEY(importer, external_source, record_key)
);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
  event_id UNINDEXED,
  corrected_seg,
  raw_seg,
  tokenize='unicode61'
);

DROP VIEW IF EXISTS current_event_text;
CREATE VIEW current_event_text AS
SELECT e.*,
       COALESCE(r.corrected_text, e.raw_text) AS current_text
FROM events e
LEFT JOIN event_revisions r
  ON r.event_id=e.event_id AND r.revision=e.current_revision;

-- Triggers for immutability
DROP TRIGGER IF EXISTS trg_events_prevent_raw_update;
CREATE TRIGGER trg_events_prevent_raw_update
BEFORE UPDATE OF raw_text ON events
BEGIN
  SELECT RAISE(ABORT, 'Updating raw_text in events table is forbidden by Journal immutability rules');
END;

DROP TRIGGER IF EXISTS trg_revisions_prevent_update;
CREATE TRIGGER trg_revisions_prevent_update
BEFORE UPDATE ON event_revisions
BEGIN
  SELECT RAISE(ABORT, 'Updating event_revisions is forbidden by Journal append-only rules');
END;
"""


def init_journal_db(conn: sqlite3.Connection) -> None:
    conn.executescript(JOURNAL_SCHEMA_SQL)
    conn.commit()
