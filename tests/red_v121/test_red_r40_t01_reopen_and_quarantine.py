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


def test_an_unusable_record_is_recorded_and_blocks_until_explicitly_abandoned():
    """T01-R2: a bad record is on record and blocks until an operator abandons it.

    Abandonment must be a manual decision.  An automatic threshold would move the
    checkpoint past a record that was never imported, which silently drops data.
    """
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    bad = {"id": "bad-1", "content": {"transcription": "x", "timestamp": "not-a-time"}}
    client = WindowedClient([_rec("good", BASE), bad])
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(client, repo)

    for _ in range(worker.QUARANTINE_ABANDON_AFTER + 2):
        asyncio.run(worker.import_page(limit=10))

    # No automatic abandonment, and the checkpoint stays put for retry.
    summary = repo.quarantine_summary()
    assert summary["open"] >= 1 and summary["abandoned"] == 0, (
        "a record was abandoned automatically; abandonment must be an explicit "
        f"operator decision. summary={summary}"
    )
    assert worker.get_watermark() == 0

    # The explicit exit: an operator abandons it, then the range may close.
    assert repo.abandon_quarantined_record("bad-1") is True
    row = repo.conn.execute(
        "SELECT reason, abandoned, abandoned_at_utc_us FROM import_quarantine "
        "WHERE record_key = 'bad-1'"
    ).fetchone()
    assert row is not None and row["abandoned"] == 1 and row["abandoned_at_utc_us"]

    asyncio.run(worker.import_page(limit=10))
    assert worker.get_watermark() > 0, "the checkpoint never closed after the abandon exit"


def test_the_reopen_sweep_continues_past_a_low_page_cap():
    """A window that does not fit the page budget must resume, not starve."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    client = WindowedClient([_rec("newer", BASE)])
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(client, repo)
    asyncio.run(worker.import_page(limit=10))
    watermark = worker.get_watermark()
    assert watermark > 0

    # Three older records, each page returns a single item, one page per call.
    for i in range(3):
        client.items.append(_rec(f"old-{i}", BASE - timedelta(hours=i + 1)))
    worker.MAX_PAGES = 1

    for _ in range(6):
        asyncio.run(worker.import_page(limit=1))
        if all(f"old-{i}" in _stored_ids(repo) for i in range(3)):
            break

    missing = [f"old-{i}" for i in range(3) if f"old-{i}" not in _stored_ids(repo)]
    assert not missing, (
        "the reopen sweep did not continue past the page cap; "
        f"unreachable={missing!r}, stored={sorted(_stored_ids(repo))}"
    )


def test_an_incomplete_sweep_is_persisted_for_resume():
    """A sweep that hits the cap must persist its offset, not silently claim done."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    client = WindowedClient([_rec("newer", BASE)])
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(client, repo)
    asyncio.run(worker.import_page(limit=10))

    # Four older records and a page size of 2: the incremental drain finishes
    # (the window returns a single stored record), but the sweep needs two pages
    # while only one is allowed.
    for i in range(4):
        client.items.append(_rec(f"old-{i}", BASE - timedelta(hours=i + 1)))
    worker.MAX_PAGES = 1
    asyncio.run(worker.import_page(limit=2))

    cursor = repo.conn.execute(
        "SELECT cursor FROM import_checkpoints WHERE importer='screenpipe_rest'"
    ).fetchone()["cursor"]
    assert cursor and '"sweep"' in cursor, (
        "an incomplete reopen sweep left no continuation state: "
        f"cursor={cursor!r}"
    )



def test_the_sweep_tail_is_reached_while_new_records_keep_arriving():
    """A continuously advancing watermark must not starve the sweep tail.


    Each round adds a newer record (advancing the checkpoint) while five older
    records still need sweeping.  Advancing the watermark used to clear the whole
    cursor, wiping the saved sweep continuation, so the oldest record never
    landed.
    """
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    client = WindowedClient([_rec("seed", BASE)])
    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(client, repo)
    worker.MAX_PAGES = 2
    asyncio.run(worker.import_page(limit=2))

    for i in range(5):
        client.items.append(_rec(f"old-{i}", BASE - timedelta(hours=i + 1)))

    for rnd in range(4):
        client.items.append(_rec(f"new-{rnd}", BASE + timedelta(minutes=rnd + 1)))
        asyncio.run(worker.import_page(limit=2))
        missing = [f"old-{i}" for i in range(5) if f"old-{i}" not in _stored_ids(repo)]
        if not missing:
            break

    missing = [f"old-{i}" for i in range(5) if f"old-{i}" not in _stored_ids(repo)]
    assert not missing, (
        "the reopen sweep tail stayed unreachable while the checkpoint advanced: "
        f"missing={missing!r}, stored={sorted(_stored_ids(repo))}"
    )

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
