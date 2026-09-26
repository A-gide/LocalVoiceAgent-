"""Behavioral RED cases for the independent R39 importer review."""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

pytestmark = pytest.mark.red_v121

STAMP = "2026-09-25T10:00:00+00:00"
STAMP_US = int(datetime.fromisoformat(STAMP).timestamp() * 1_000_000)


class MutableOffsetClient:
    """Static source order with explicit offset paging and mutable records."""

    def __init__(self, items):
        self.items = items
        self.calls: list[tuple[int, int, str | None]] = []

    async def search(self, limit=50, offset=0, start_time=None):
        self.calls.append((limit, offset, start_time))
        visible = self.items
        if start_time:
            cutoff = datetime.fromisoformat(start_time)
            visible = [
                item
                for item in visible
                if datetime.fromisoformat(
                    item["content"]["timestamp"].replace("Z", "+00:00")
                )
                >= cutoff
            ]
        return visible[offset : offset + limit]


def _event_count(repo) -> int:
    return repo.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def test_redaction_without_source_id_fails_closed_and_keeps_the_old_row(caplog):
    """A redacted derived ID must not become a new searchable Journal event."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    item = {
        "content": {
            "transcription": "private words",
            "timestamp": STAMP,
            "file_path": "/capture/one.wav",
        }
    }
    client = MutableOffsetClient([item])
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(client, repo)

    asyncio.run(worker.import_page(limit=10))
    initial_watermark = worker.get_watermark()
    client.items.append(
        {
            "redacted": True,
            "content": {
                "transcription": "private words",
                "timestamp": (
                    datetime.fromisoformat(STAMP) + timedelta(seconds=5)
                ).isoformat(),
                "file_path": "/capture/one.wav",
            },
        }
    )
    asyncio.run(worker.import_page(limit=10))
    watermark_after_unverified_redaction = worker.get_watermark()

    row_count = _event_count(repo)
    texts = [
        row["current_text"]
        for row in repo.conn.execute(
            "SELECT current_text FROM current_event_text ORDER BY occurred_at_utc_us"
        ).fetchall()
    ]
    assert (
        row_count == 1
        and texts == ["private words"]
        and watermark_after_unverified_redaction == initial_watermark
        and "UNVERIFIED" in caplog.text
    ), (
        "without a stable source id the importer inserted a second derived row "
        "or moved the checkpoint instead of failing closed; the original remains "
        "searchable and source redaction is UNVERIFIED: "
        f"rows={row_count}, current_texts={texts!r}, "
        f"watermark_before={initial_watermark}, "
        f"watermark_after={watermark_after_unverified_redaction}"
    )


def test_legacy_alias_does_not_drop_a_capture_with_a_different_file_path():
    """The old time+text alias cannot merge captures whose paths differ."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    text = "same transcript"
    legacy_id = f"audio_{STAMP_US}_{hashlib.sha256(text.encode()).hexdigest()[:12]}"
    existing = {
        "content": {
            "transcription": text,
            "timestamp": STAMP,
            "file_path": "/capture/a.wav",
        }
    }
    distinct = {
        "content": {
            "transcription": text,
            "timestamp": STAMP,
            "file_path": "/capture/b.wav",
        }
    }
    repo = JournalRepository(":memory:")
    repo.append_event(
        event_id=uuid4(),
        raw_text=text,
        occurred_at_utc_us=STAMP_US,
        audio_ref="/capture/a.wav",
        provenance={"audio_file_path": "/capture/a.wav"},
        external_source="screenpipe_rest",
        external_id=legacy_id,
    )

    asyncio.run(
        ScreenpipeImportWorker(MutableOffsetClient([existing, distinct]), repo).import_page(
            limit=10
        )
    )

    rows = repo.conn.execute(
        "SELECT audio_ref FROM events WHERE external_source = 'screenpipe_rest' "
        "ORDER BY audio_ref"
    ).fetchall()
    paths = [row["audio_ref"] for row in rows]
    assert paths == ["/capture/a.wav", "/capture/b.wav"], (
        "a legacy time+text alias matched a different file and suppressed its "
        f"Journal row; stored capture paths={paths!r}"
    )


def test_capped_import_resumes_after_worker_reconstruction():
    """A process restart must continue past the persisted page offset."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    records = [
        {
            "id": f"capture-{index}",
            "content": {
                "transcription": f"text {index}",
                "timestamp": f"2026-09-25T10:00:{index:02d}+00:00",
            },
        }
        for index in range(5)
    ]
    client = MutableOffsetClient(records)
    repo = JournalRepository(":memory:")
    first_worker = ScreenpipeImportWorker(client, repo)
    first_worker.MAX_PAGES = 2

    asyncio.run(first_worker.import_page(limit=1))
    first_count = _event_count(repo)

    restarted_worker = ScreenpipeImportWorker(client, repo)
    restarted_worker.MAX_PAGES = 2
    asyncio.run(restarted_worker.import_page(limit=1))
    after_restart_count = _event_count(repo)

    assert first_count == 2 and after_restart_count > first_count, (
        "the Journal checkpoint did not retain the capped offset; a reconstructed "
        "worker reread the head and the tail remained starved: "
        f"before_restart={first_count}, after_restart={after_restart_count}, "
        f"requests={client.calls!r}"
    )

    for _ in range(5):
        worker = ScreenpipeImportWorker(client, repo)
        worker.MAX_PAGES = 2
        asyncio.run(worker.import_page(limit=1))
        if _event_count(repo) == len(records):
            break
    assert _event_count(repo) == len(records), (
        "repeated worker reconstruction did not eventually import the full "
        f"static source result set: {_event_count(repo)} of {len(records)}"
    )
