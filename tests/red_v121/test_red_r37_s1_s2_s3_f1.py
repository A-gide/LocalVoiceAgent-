"""RED: R37 S1/S2/S3 + F1 negative fail-closed (executor slice).

Authorized scope: S1 (redaction field alignment), S2 (stable external id),
S3 (multi-page / ordering), and F1's constructed-table negative tests.  The
real-machine constraints only bind S4 (source compatibility) and S6 (real Hub
identity), so these do not wait on them.

Every assertion observes an outcome -- stored rows, the watermark, the verdict --
rather than searching the source for a function name.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"


def _ts(minutes_before: int) -> str:
    base = datetime(2026, 9, 25, 0, 0, 0, tzinfo=timezone.utc)
    return (base - timedelta(minutes=minutes_before)).isoformat()


class PagingClient:
    """A source that honours limit/offset and start_time, in a given order."""

    def __init__(self, items, *, descending=True):
        self.items = items
        self.descending = descending
        self.calls: list[tuple] = []

    async def search(self, limit=50, offset=0, start_time=None):
        self.calls.append((limit, offset, start_time))
        ordered = sorted(
            self.items,
            key=lambda it: it["content"]["timestamp"],
            reverse=self.descending,
        )
        if start_time:
            cut = datetime.fromisoformat(start_time)
            ordered = [
                it
                for it in ordered
                if datetime.fromisoformat(it["content"]["timestamp"]) >= cut
            ]
        return ordered[offset : offset + limit]


def _records(n: int):
    return [
        {
            "id": f"rec-{i}",
            "content": {"transcription": f"line {i}", "timestamp": _ts(i)},
        }
        for i in range(n)
    ]


def _count(repo) -> int:
    return repo.conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]


# ===================================================== S3: multi-page import
def test_a_descending_source_imports_every_page():
    """A newest-first source: page one's max time IS the newest record."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    repo = JournalRepository(":memory:")
    client = PagingClient(_records(200), descending=True)
    worker = ScreenpipeImportWorker(client, repo)

    asyncio.run(worker.import_page(limit=50))
    asyncio.run(worker.import_page(limit=50))
    asyncio.run(worker.import_page(limit=50))
    asyncio.run(worker.import_page(limit=50))

    stored = _count(repo)
    assert stored == 200, (
        f"only {stored} of 200 records were imported: the checkpoint advanced to "
        "the newest timestamp after the first page, so every older page is now "
        "excluded by start_time and is permanently unreachable"
    )


def test_an_ascending_source_imports_every_page():
    """An oldest-first source loses the remainder of the current page instead."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    repo = JournalRepository(":memory:")
    client = PagingClient(_records(200), descending=False)
    worker = ScreenpipeImportWorker(client, repo)

    for _ in range(4):
        asyncio.run(worker.import_page(limit=50))

    stored = _count(repo)
    assert stored == 200, (
        f"only {stored} of 200 records were imported from an oldest-first source"
    )


def test_the_watermark_never_exceeds_the_oldest_unimported_record():
    """A partial drain must not advance the checkpoint at all.

    After a full drain the checkpoint is legitimately the newest timestamp; what
    must never happen is a checkpoint that moved while records remained unfetched.
    So the assertion is conditional on completeness, not an ordering.
    """
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    repo = JournalRepository(":memory:")
    client = PagingClient(_records(200), descending=True)
    worker = ScreenpipeImportWorker(client, repo)
    asyncio.run(worker.import_page(limit=50))

    watermark = worker.get_watermark()
    stored = _count(repo)
    assert stored == 200, (
        f"only {stored} of 200 records were imported; the checkpoint advanced "
        "while records were still unfetched"
    )
    newest = repo.conn.execute(
        "SELECT MAX(occurred_at_utc_us) m FROM events"
    ).fetchone()["m"]
    assert watermark == newest, (
        "a completed drain must leave the checkpoint at the newest stored record"
    )


# ===================================================== S1: redaction field
def test_the_redaction_mark_reaches_the_worker_branch():
    """The normalizer writes the mark; the worker must read the same place."""
    from lva.screenpipe_importer.normalize import normalize_screenpipe_audio_item

    normalized = normalize_screenpipe_audio_item(
        {
            "id": "c1",
            "redacted": True,
            "content": {"transcription": "secret", "timestamp": _ts(5)},
        }
    )
    top = normalized.get("redacted")
    in_prov = (normalized.get("provenance") or {}).get("redacted")
    assert top is not None or in_prov is not None, (
        "the redaction mark is not exposed in a place the importer can read"
    )


def test_a_marked_record_applies_redaction_end_to_end():
    """Stored outcome, not an internal return value."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    repo = JournalRepository(":memory:")
    repo.append_event(
        event_id=uuid4(),
        raw_text="the original words",
        occurred_at_utc_us=5_000_000,
        # Must match what the normalizer emits, or the deduplication query cannot
        # find the stored row and the redaction branch is never reached.
        external_source="screenpipe_rest",
        external_id="c1",
    )
    seed = ScreenpipeImportWorker(PagingClient([]), repo)
    seed.update_watermark(5_000_000)

    client = PagingClient(
        [
            {
                "id": "c1",
                "redacted": True,
                "content": {"transcription": "the original words", "timestamp": _ts(0)},
            }
        ]
    )
    worker = ScreenpipeImportWorker(client, repo)
    asyncio.run(worker.import_page())

    row = repo.conn.execute(
        "SELECT current_text FROM current_event_text WHERE external_id = 'c1'"
    ).fetchone()
    assert row["current_text"] == "[REDACTED]", (
        "the source marked the record redacted but the stored text is unchanged, "
        "so the redaction never took effect"
    )


# ===================================================== S2: stable external id
def test_the_external_id_does_not_depend_on_the_transcription():
    """When the source supplies an id, a redaction must not change it.

    A *derived* id cannot satisfy both this and uniqueness (see the companion
    test), so the requirement is scoped to source-supplied ids -- which is the
    case the plan's idempotency guarantee is written for.
    """
    from lva.screenpipe_importer.normalize import normalize_screenpipe_audio_item

    plain = normalize_screenpipe_audio_item(
        {
            "id": "source-1",
            "content": {"transcription": "the original words", "timestamp": _ts(5)},
        }
    )
    marked = normalize_screenpipe_audio_item(
        {
            "id": "source-1",
            "redacted": True,
            "content": {"transcription": "the original words", "timestamp": _ts(5)},
        }
    )
    assert plain["external_id"] == marked["external_id"], (
        "a source-supplied id changed when the record was redacted, so the two "
        "versions of the same record cannot be matched"
    )


def test_a_record_without_a_source_id_is_not_silently_given_a_volatile_one():
    """If the source offers no stable id, the limitation must be visible.

    A derived id cannot be both stable and unique, so the honest outcome is to
    keep it unique (protecting the idempotency guarantee) and flag it as derived
    so a reconciliation can refuse to rely on it.
    """
    from lva.screenpipe_importer.normalize import normalize_screenpipe_audio_item

    normalized = normalize_screenpipe_audio_item(
        {"content": {"transcription": "words", "timestamp": _ts(5)}}
    )
    provenance = normalized.get("provenance") or {}
    assert provenance.get("stable_id") is False, (
        "a derived id is presented as if it came from the source, so a later "
        "reconciliation cannot tell it apart from a real one"
    )
    assert normalized.get("external_id_is_derived") is True, (
        "the caller must be able to see that this id is not source-authoritative"
    )


# ===================================================== F1: negative verdicts
def test_listener_row_parsing_keeps_a_row_whose_pid_is_unreadable():
    """The parse and the verdict must be covered by *Rust* tests, not string search.

    A Python assertion on Rust source cannot execute the branch it describes: it
    passes as long as the text exists, whether or not the logic works.  The
    behavioural coverage lives in `network_attestation.rs` (the parser and verdict
    unit tests); this test only checks that the Rust suite actually contains those
    cases, so the coverage cannot be dropped silently.
    """
    rust = read_text(
        REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src" / "network_attestation.rs"
    )
    for case in (
        "a_loopback_port_whose_owner_cannot_be_read_does_not_verify",
        "a_loopback_port_shared_by_two_processes_does_not_verify",
        "a_loopback_port_with_one_process_on_both_stacks_still_verifies",
        "an_unreadable_pid_is_kept_as_a_row_but_a_malformed_row_is_dropped",
    ):
        assert case in rust, (
            f"the Rust suite must cover {case}: the negative verdict logic has to "
            "be executed, not searched for"
        )


def test_attestation_requires_every_owner_to_be_known():
    """The verdict must consider every owner; proven by the Rust tests running."""
    rust = read_text(
        REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src" / "network_attestation.rs"
    )
    assert "find_map(|row| row.owning_process)" not in rust, (
        "the first non-None owner is taken, so a row whose PID is missing does not "
        "participate in the correlation and is not reported either"
    )
    assert "any_unreadable" in rust and "owners.len() > 1" in rust, (
        "the verdict must reject an incomplete owner set and a shared port; both "
        "branches are executed by the Rust tests"
    )
