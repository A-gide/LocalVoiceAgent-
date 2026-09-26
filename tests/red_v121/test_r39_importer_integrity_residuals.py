"""Behavioral RED cases for the two R39 importer integrity residuals."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

pytestmark = pytest.mark.red_v121

NEWER = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)


class MutableSearchClient:
    """Small start_time/offset source whose bad item can later be corrected."""

    def __init__(self, items):
        self.items = items

    async def search(self, limit=50, offset=0, start_time=None):
        cutoff = datetime.fromisoformat(start_time) if start_time else None
        visible = []
        for item in self.items:
            timestamp = item["content"].get("timestamp")
            try:
                occurred_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except (AttributeError, TypeError, ValueError):
                if cutoff is None:
                    visible.append(item)
                continue
            if cutoff is None or occurred_at >= cutoff:
                visible.append(item)
        return visible[offset : offset + limit]


def test_skipped_bad_timestamp_does_not_checkpoint_past_later_correction():
    """A corrected source item must remain fetchable after an invalid timestamp."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    newer = {
        "id": "newer-record",
        "content": {"transcription": "newer", "timestamp": NEWER.isoformat()},
    }
    corrected = {
        "id": "corrected-record",
        "content": {"transcription": "was malformed", "timestamp": "not-a-time"},
    }
    client = MutableSearchClient([newer, corrected])
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(client, repo)

    asyncio.run(worker.import_page(limit=10))
    watermark_after_skip = worker.get_watermark()

    corrected["content"]["timestamp"] = (NEWER - timedelta(hours=1)).isoformat()
    asyncio.run(worker.import_page(limit=10))

    corrected_row = repo.conn.execute(
        "SELECT 1 FROM events WHERE external_source = ? AND external_id = ?",
        ("screenpipe_rest", "corrected-record"),
    ).fetchone()
    assert watermark_after_skip == 0 and corrected_row is not None, (
        "the drained page advanced the checkpoint despite skipping an item; "
        f"watermark_after_skip={watermark_after_skip}, "
        f"corrected_record_imported={corrected_row is not None}"
    )


def test_skipped_record_remains_a_checkpoint_blocker_across_capped_resume():
    """A later resumed page must remember skips from the earlier capped page."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    bad = {
        "id": "corrected-after-resume",
        "content": {"transcription": "late correction", "timestamp": "not-a-time"},
    }
    older = {
        "id": "older-valid-record",
        "content": {
            "transcription": "older but valid",
            "timestamp": (NEWER - timedelta(hours=2)).isoformat(),
        },
    }
    client = MutableSearchClient(
        [
            {
                "id": "newer-record",
                "content": {"transcription": "newer", "timestamp": NEWER.isoformat()},
            },
            bad,
            older,
        ]
    )
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(client, repo)
    worker.MAX_PAGES = 1

    asyncio.run(worker.import_page(limit=2))
    bad["content"]["timestamp"] = (NEWER - timedelta(hours=3)).isoformat()
    asyncio.run(worker.import_page(limit=2))
    watermark_after_resume = worker.get_watermark()
    asyncio.run(worker.import_page(limit=2))

    corrected_row = repo.conn.execute(
        "SELECT 1 FROM events WHERE external_source = ? AND external_id = ?",
        ("screenpipe_rest", "corrected-after-resume"),
    ).fetchone()
    assert watermark_after_resume == 0 and corrected_row is not None, (
        "the capped continuation forgot that an earlier page skipped a record, "
        f"then checkpointed beyond its correction: "
        f"watermark_after_resume={watermark_after_resume}, "
        f"corrected_record_imported={corrected_row is not None}"
    )


def test_redaction_uses_the_source_id_that_matched_deduplication(monkeypatch):
    """A stable source id selected by de-duplication receives the redaction."""
    import lva.screenpipe_importer.worker as worker_module
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    normalized = {
        "external_source": "screenpipe_rest",
        "external_id": "stable-source-id",
        "legacy_external_ids": [],
        "redacted": True,
        "stable_id": True,
        "external_id_is_derived": False,
        "occurred_at_utc_us": int(NEWER.timestamp() * 1_000_000),
    }
    monkeypatch.setattr(
        worker_module, "normalize_screenpipe_audio_item", lambda _item: normalized
    )

    class OneItemClient:
        async def search(self, limit=50, offset=0, start_time=None):
            return [{"source": "redacted duplicate"}][offset : offset + limit]

    repo = JournalRepository(":memory:")
    event_id = uuid4()
    repo.append_event(
        event_id=event_id,
        raw_text="private transcript",
        occurred_at_utc_us=int(NEWER.timestamp() * 1_000_000),
        external_source="screenpipe_rest",
        external_id="stable-source-id",
    )

    asyncio.run(ScreenpipeImportWorker(OneItemClient(), repo).import_page(limit=10))

    event = repo.conn.execute(
        "SELECT current_revision FROM events WHERE event_id = ?", (str(event_id),)
    ).fetchone()
    revision = repo.conn.execute(
        "SELECT corrected_text FROM event_revisions "
        "WHERE event_id = ? AND reason = 'source_redaction'",
        (str(event_id),),
    ).fetchone()
    assert event["current_revision"] == 1 and revision is not None and (
        revision["corrected_text"] == "[REDACTED]"
    ), (
        "de-duplication matched stable-source-id, but the redaction lookup did "
        f"not update that row: revision={event['current_revision']}, "
        f"redaction_revision={revision is not None}"
    )
