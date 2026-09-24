from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import sys
from uuid import uuid5, NAMESPACE_DNS

from .repository import JournalRepository

log = logging.getLogger("lva.journal.migrate_legacy")


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 checksum of legacy DB snapshot per Part 7.4."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def migrate_legacy_db(
    legacy_db_path: str | Path,
    target_repo: JournalRepository,
    dry_run: bool = False,
) -> dict:
    """Migrate legacy memory.db to Journal v2 without modifying the legacy file.

    Returns migration report:
    {
        "checksum": str,
        "total_legacy_rows": int,
        "migrated_count": int,
        "skipped_count": int,
        "revisions_created": int,
        "invalid_rows": int,
        "errors": list[str]
    }
    """
    path = Path(legacy_db_path)
    if not path.exists():
        log.warning("Legacy DB file %s does not exist", path)
        return {
            "checksum": "",
            "total_legacy_rows": 0,
            "migrated_count": 0,
            "skipped_count": 0,
            "revisions_created": 0,
            "invalid_rows": 0,
            "errors": [f"File {path} not found"],
        }

    checksum = compute_file_sha256(path)

    legacy_conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    legacy_conn.row_factory = sqlite3.Row

    try:
        cur = legacy_conn.execute("SELECT COUNT(*) as cnt FROM utterances")
        total_rows = cur.fetchone()["cnt"]
    except sqlite3.OperationalError as exc:
        legacy_conn.close()
        return {
            "checksum": checksum,
            "total_legacy_rows": 0,
            "migrated_count": 0,
            "skipped_count": 0,
            "revisions_created": 0,
            "invalid_rows": 0,
            "errors": [f"Failed to query legacy utterances: {exc}"],
        }

    report = {
        "checksum": checksum,
        "total_legacy_rows": total_rows,
        "migrated_count": 0,
        "skipped_count": 0,
        "revisions_created": 0,
        "invalid_rows": 0,
        "errors": [],
    }

    cur = legacy_conn.execute(
        """
        SELECT id, ts, source, speaker, raw_text, fixed_text,
               domain, audio_path, duration_s, meta
        FROM utterances
        ORDER BY ts ASC
        """
    )

    for row in cur:
        try:
            legacy_id = row["id"]
            ts_val = row["ts"]
            if ts_val is None:
                raise ValueError("Timestamp is NULL")
            try:
                ts = float(ts_val)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Malformed timestamp '{ts_val}': {exc}") from exc

            occ_us = int(ts * 1_000_000)
            raw_text = row["raw_text"] or ""
            fixed_text = row["fixed_text"]
            domain = row["domain"]
            audio_path = row["audio_path"]
            meta_raw = row["meta"]

            try:
                meta = json.loads(meta_raw) if meta_raw else {}
            except Exception:
                meta = {"raw_meta": str(meta_raw)}

            provenance = {
                "migrated_from": "legacy_memory_db",
                "legacy_id": legacy_id,
                **meta,
            }

            # Deterministic UUID for idempotency
            event_id = uuid5(NAMESPACE_DNS, f"lva.legacy.utterance.{legacy_id}")

            # Check if event already exists (idempotency)
            if target_repo.get_event(event_id) is not None:
                report["skipped_count"] += 1
                continue

            if dry_run:
                # Dry run validates row integrity without writing to target_repo
                report["migrated_count"] += 1
                if fixed_text and fixed_text != raw_text:
                    report["revisions_created"] += 1
                continue

            target_repo.append_event(
                event_id=event_id,
                raw_text=raw_text,
                occurred_at_utc_us=occ_us,
                speaker=row["speaker"] or "user",
                source=row["source"] or "legacy",
                domain=domain,
                audio_ref=audio_path,
                provenance=provenance,
                external_source="legacy_memory_db",
                external_id=str(legacy_id),
            )
            report["migrated_count"] += 1

            # If fixed_text differs from raw_text, create revision 1
            if fixed_text and fixed_text != raw_text:
                target_repo.add_revision(
                    event_id=event_id,
                    corrected_text=fixed_text,
                    reason="legacy_fixed_text",
                    actor="legacy_migration",
                )
                report["revisions_created"] += 1

        except Exception as exc:
            report["invalid_rows"] += 1
            report["errors"].append(f"Row id={row['id'] if 'id' in row.keys() else 'unknown'}: {exc}")

    legacy_conn.close()
    log.info(
        "Legacy migration complete: total=%d, migrated=%d, skipped=%d, revisions=%d, invalid=%d, errors=%d",
        report["total_legacy_rows"],
        report["migrated_count"],
        report["skipped_count"],
        report["revisions_created"],
        report["invalid_rows"],
        len(report["errors"]),
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy memory.db to Journal v2")
    parser.add_argument("--legacy-db", required=True, help="Path to legacy memory.db")
    parser.add_argument("--target-db", help="Path to target journal.sqlite3 (default: in-memory)")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry-run verification only")
    parser.add_argument("--report-json", help="Path to write JSON report")

    args = parser.parse_args(argv)

    target_repo = JournalRepository(args.target_db) if args.target_db else JournalRepository()
    report = migrate_legacy_db(args.legacy_db, target_repo, dry_run=args.dry_run)

    print("Migration Report:")
    print(f"  SHA256 Checksum:    {report['checksum']}")
    print(f"  Total Legacy Rows:  {report['total_legacy_rows']}")
    print(f"  Migrated Rows:      {report['migrated_count']}")
    print(f"  Skipped (Existing): {report['skipped_count']}")
    print(f"  Revisions Created:  {report['revisions_created']}")
    print(f"  Invalid / Quarantined Rows: {report['invalid_rows']}")
    if report["errors"]:
        print(f"  Errors ({len(report['errors'])}):")
        for err in report["errors"][:5]:
            print(f"    - {err}")

    if args.report_json:
        with open(args.report_json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Report written to {args.report_json}")

    return 0 if report["invalid_rows"] == 0 or report["migrated_count"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

