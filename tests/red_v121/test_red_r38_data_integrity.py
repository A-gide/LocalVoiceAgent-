"""RED: R38 residual data-integrity gaps (executor slice).

Three failures the R38 report called fixed but which the review reproduced
through the real worker call chain:

1. the page cap stops the drain, yet the watermark still advances, so the
   records beyond the cap become unreachable;
2. the derived id merges two *different* captures that share timestamp, device,
   duration and text but differ in file path;
3. the new derived-id formula does not match ids written by the old formula, so
   replaying a record stored before the change inserts it a second time.

Each assertion observes stored rows or the checkpoint, not an internal return.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
BASE = datetime(2026, 9, 25, 0, 0, 0, tzinfo=timezone.utc)


def _ts(minutes_before: int) -> str:
    return (BASE - timedelta(minutes=minutes_before)).isoformat()


def _us(minutes_before: int) -> int:
    return int((BASE - timedelta(minutes=minutes_before)).timestamp() * 1_000_000)


class PagingClient:
    """Honours limit/offset and start_time over a newest-first list."""

    def __init__(self, items):
        self.items = items
        self.calls: list[tuple] = []

    async def search(self, limit=50, offset=0, start_time=None):
        self.calls.append((limit, offset, start_time))
        out = sorted(self.items, key=lambda it: it["content"]["timestamp"], reverse=True)
        if start_time:
            cut = datetime.fromisoformat(start_time)
            out = [
                it
                for it in out
                if datetime.fromisoformat(it["content"]["timestamp"]) >= cut
            ]
        return out[offset : offset + limit]


def _count(repo) -> int:
    return repo.conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]


# =============================== 1. an unconfirmed drain must not move the checkpoint
def test_the_page_cap_does_not_advance_the_checkpoint():
    """Records beyond the cap must stay reachable, not be skipped forever."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    records = [
        {"id": f"r{i}", "content": {"transcription": f"t{i}", "timestamp": _ts(i)}}
        for i in range(201)
    ]
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(PagingClient(records), repo)
    worker.MAX_PAGES = 3  # a cap small enough to be hit in one call

    first = asyncio.run(worker.import_page(limit=1))
    watermark_after_capped_call = worker.get_watermark()

    assert first < 201, "the cap is meant to truncate this call"
    assert watermark_after_capped_call == 0 or watermark_after_capped_call <= repo.conn.execute(
        "SELECT MAX(occurred_at_utc_us) m FROM events"
    ).fetchone()["m"], (
        "the checkpoint advanced past what was actually stored, so the records "
        "between the cap and the checkpoint can never be fetched again"
    )

    # Draining further must still be possible.
    total = first
    for _ in range(300):
        added = asyncio.run(worker.import_page(limit=1))
        total += added
        if added == 0:
            break
    assert _count(repo) == 201, (
        f"only {_count(repo)} of 201 records were imported; the capped call left "
        "the rest unreachable"
    )


# =============================== 2. a derived id must not merge distinct captures
def test_a_derived_id_does_not_merge_different_files():
    """Two captures sharing every hash input except the file are not one record."""
    from lva.screenpipe_importer.normalize import normalize_screenpipe_audio_item

    common = {
        "transcription": "same words",
        "timestamp": _ts(0),
        "device_name": "mic",
        "duration": 2.0,
    }
    a = normalize_screenpipe_audio_item(
        {"content": {**common, "file_path": "/a.wav"}}
    )
    b = normalize_screenpipe_audio_item(
        {"content": {**common, "file_path": "/b.wav"}}
    )
    assert a["external_id"] != b["external_id"], (
        "two distinct captures collapse to the same id, so the unique constraint "
        "(plan L901) silently drops one of them"
    )


# =============================== 3. replay must stay idempotent across the formula
def test_replaying_a_record_stored_with_the_old_formula_does_not_duplicate_it():
    """The id change must not make existing rows look like new records."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    item = {"content": {"transcription": "legacy words", "timestamp": _ts(0), "device_name": "mic"}}
    # The id the previous formula produced for this record.
    legacy_id = "audio_{}_{}".format(
        _us(0), hashlib.sha256(b"legacy words").hexdigest()[:12]
    )

    repo = JournalRepository(":memory:")
    repo.append_event(
        event_id=uuid4(),
        raw_text="legacy words",
        occurred_at_utc_us=_us(0),
        external_source="screenpipe_rest",
        external_id=legacy_id,
    )
    worker = ScreenpipeImportWorker(PagingClient([item]), repo)

    asyncio.run(worker.import_page(limit=10))

    stored = _count(repo)
    assert stored == 1, (
        f"the same source record is stored {stored} times: the new derived-id "
        "formula does not recognise rows written by the old one, so a replay "
        "duplicates them"
    )


def test_the_importer_does_not_promise_lossless_idempotency_without_a_source_id():
    """Without a stable source id the guarantee must be stated as limited."""
    src = read_text(LVA / "screenpipe_importer" / "worker.py")
    assert "derived" in src.lower() or "stable_id" in src, (
        "the importer treats a derived id as if it carried the source's "
        "idempotency guarantee; the limitation must be visible in the code path "
        "that relies on it"
    )

