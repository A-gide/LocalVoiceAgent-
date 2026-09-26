"""R40 T01 — historical-range reopening and the explicit quarantine exit."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.red_v121

BASE = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


class WindowedClient:
    """start_time/end_time-filtering source whose older record appears later."""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.calls: list[dict] = []

    async def search(self, limit=50, offset=0, start_time=None, end_time=None):
        self.calls.append(
            {"limit": limit, "offset": offset, "start_time": start_time, "end_time": end_time}
        )
        lo = datetime.fromisoformat(start_time) if start_time else None
        hi = datetime.fromisoformat(end_time) if end_time else None
        visible = []
        for item in self.items:
            ts = item["content"]["timestamp"]
            try:
                occurred = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (AttributeError, TypeError, ValueError):
                # An unusable timestamp is still a record the source returns
                # when no lower bound is applied; a bounded window cannot place
                # it, so it only appears in the unbounded request.
                if lo is None:
                    visible.append(item)
                continue
            if lo is not None and occurred < lo:
                continue
            if hi is not None and occurred >= hi:
                continue
            visible.append(item)
        return visible[offset : offset + limit]


def _rec(id_, when, text="hello"):
    return {"id": id_, "content": {"transcription": text, "timestamp": when.isoformat()}}


def _stored_ids(repo):
    return {
        row["external_id"]
        for row in repo.conn.execute(
            "SELECT external_id FROM events WHERE external_source = 'screenpipe_rest'"
        ).fetchall()
    }


def test_a_late_arriving_older_record_is_recovered_below_the_checkpoint():
    """The checkpoint is monotonic, so a bounded sweep must find the late record."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    newer = _rec("newer", BASE)
    client = WindowedClient([newer])
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(client, repo)

    asyncio.run(worker.import_page(limit=10))
    assert worker.get_watermark() > 0

    # A corrected/晚到 record lands below the checkpoint that already passed it.
    client.items.append(_rec("late-older", BASE - timedelta(hours=2)))
    asyncio.run(worker.import_page(limit=10))

    assert "late-older" in _stored_ids(repo), (
        "a record below an already-advanced checkpoint stayed unreachable: "
        f"stored={sorted(_stored_ids(repo))}"
    )


def test_the_reopen_sweep_is_idempotent_across_repeated_calls():
    """Repeated sweeps must not duplicate already-recovered records."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    client = WindowedClient([_rec("newer", BASE)])
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(client, repo)
    asyncio.run(worker.import_page(limit=10))
    client.items.append(_rec("late-older", BASE - timedelta(hours=2)))

    for _ in range(3):
        asyncio.run(worker.import_page(limit=10))

    count = repo.conn.execute(
        "SELECT COUNT(*) FROM events WHERE external_id = 'late-older'"
    ).fetchone()[0]
    assert count == 1, f"the reopen sweep duplicated the recovered record: count={count}"


def test_the_reopen_sweep_request_is_bounded_below_the_checkpoint():
    """The sweep must not degrade into an unbounded full-history rescan."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    client = WindowedClient([_rec("newer", BASE)])
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(client, repo)
    asyncio.run(worker.import_page(limit=10))
    client.calls.clear()
    asyncio.run(worker.import_page(limit=10))

    sweep_calls = [c for c in client.calls if c.get("end_time")]
    assert sweep_calls, "the reopen sweep never issued a bounded window request"
    watermark = worker.get_watermark()
    for call in sweep_calls:
        lo = datetime.fromisoformat(call["start_time"]).timestamp() * 1_000_000
        hi = datetime.fromisoformat(call["end_time"]).timestamp() * 1_000_000
        assert int(hi) == watermark
        assert int(lo) >= watermark - worker.REOPEN_WINDOW_US


def test_an_unusable_record_is_recorded_and_blocks_until_abandoned():
    """T01-R2: a bad record is on record, blocks the checkpoint, then can exit."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    bad = {"id": "bad-1", "content": {"transcription": "x", "timestamp": "not-a-time"}}
    client = WindowedClient([_rec("good", BASE), bad])
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(client, repo)

    for _ in range(worker.QUARANTINE_ABANDON_AFTER + 1):
        asyncio.run(worker.import_page(limit=10))

    summary = repo.quarantine_summary()
    assert summary["abandoned"] >= 1, (
        "a permanently unusable record was never given the explicit abandon exit: "
        f"summary={summary}"
    )
    # The gap stays visible rather than being silently dropped.
    row = repo.conn.execute(
        "SELECT reason, abandoned, abandoned_at_utc_us FROM import_quarantine "
        "WHERE record_key = 'bad-1'"
    ).fetchone()
    assert row is not None and row["abandoned"] == 1 and row["abandoned_at_utc_us"]

    # Once abandoned, the checkpoint is allowed to close over the range.
    asyncio.run(worker.import_page(limit=10))
    assert worker.get_watermark() > 0, "the checkpoint never closed after the abandon exit"


def test_an_open_quarantine_record_still_blocks_the_checkpoint():
    """Before the abandon threshold the checkpoint must stay put for retry."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    bad = {"id": "bad-early", "content": {"transcription": "x", "timestamp": "nope"}}
    client = WindowedClient([_rec("good", BASE), bad])
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(client, repo)

    asyncio.run(worker.import_page(limit=10))

    assert worker.get_watermark() == 0
    assert repo.quarantine_summary()["open"] == 1
