"""R40 T05/T06 - source capability contract and absence-is-not-deletion."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.red_v121


def test_unobserved_capabilities_are_unknown_not_assumed():
    """A probe that cannot observe a capability must report it unknown."""
    from lva.screenpipe_importer.capabilities import SourceCapabilities

    caps = SourceCapabilities(version="0.4.50")
    unknown = caps.unknown_capabilities()
    assert "start_time_is_filter" in unknown
    assert "deletion_notice" in unknown
    assert not caps.fully_observed
    reason = caps.refuse_reason("deletion_notice")
    assert reason and "UNVERIFIED_SCREENPIPE_CAPABILITY" in reason, (
        "an unobserved capability must produce an explicit refusal, not a default"
    )


def test_probe_reports_only_what_the_source_actually_returns():
    """A health/version probe must not fabricate pagination/redaction facts."""
    from lva.screenpipe_importer.capabilities import probe_capabilities

    class Client:
        async def probe_capabilities(self):
            return {"healthy": True, "version": "0.4.50", "supported": True}

    caps = asyncio.run(probe_capabilities(Client()))
    assert caps.version == "0.4.50"
    assert caps.deletion_notice is None, "the probe invented a deletion capability"
    assert caps.start_time_is_filter is None, "the probe invented a filter semantic"


def test_probe_of_an_unreachable_source_stays_fully_unknown():
    """An unreachable source proves nothing; nothing may be filled in."""
    from lva.screenpipe_importer.capabilities import probe_capabilities

    class Client:
        async def probe_capabilities(self):
            raise RuntimeError("connection refused")

    caps = asyncio.run(probe_capabilities(Client()))
    assert caps.version is None and caps.deletion_notice is None
    assert not caps.fully_observed


def test_absence_from_the_source_is_not_treated_as_a_deletion():
    """The load-bearing rule: a vanished record must not be deleted."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.capabilities import SourceCapabilities
    from lva.screenpipe_importer.reconcile import ScreenpipeReconciler

    repo = JournalRepository(":memory:")
    repo.append_event(
        event_id="evt-absent",
        raw_text="still here",
        occurred_at_utc_us=int(datetime(2026, 9, 25, tzinfo=timezone.utc).timestamp() * 1_000_000),
        external_source="screenpipe_rest",
        external_id="sp-1",
    )
    reconciler = ScreenpipeReconciler(object(), repo, capabilities=SourceCapabilities())
    report = reconciler.note_absent_records(["sp-1"], seen_ids=set())

    assert report.absent_without_notice == ["sp-1"]
    assert report.deletion_sync_complete is False, (
        "without a deletion notice the reconciliation must not claim deletion sync"
    )
    row = repo.conn.execute(
        "SELECT raw_text FROM events WHERE external_id = 'sp-1'"
    ).fetchone()
    assert row is not None and row["raw_text"] == "still here", (
        "a record absent from the source was deleted: absence is not deletion"
    )


def test_an_explicit_redaction_signal_is_applied():
    """A positively observed redaction mark must reach the stored row."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.reconcile import ScreenpipeReconciler

    repo = JournalRepository(":memory:")
    repo.append_event(
        event_id="evt-redact",
        raw_text="private words",
        occurred_at_utc_us=int(datetime(2026, 9, 25, tzinfo=timezone.utc).timestamp() * 1_000_000),
        external_source="screenpipe_rest",
        external_id="sp-2",
    )
    report = ScreenpipeReconciler(object(), repo).reconcile_record("sp-2", redacted=True)
    assert report.redactions_applied == 1
    current = repo.conn.execute(
        "SELECT current_text FROM current_event_text WHERE external_id = 'sp-2'"
    ).fetchone()["current_text"]
    assert current == "[REDACTED]"


def test_a_derived_id_is_refused_by_reconciliation():
    """Without a stable source id, reconciliation must refuse, not guess."""
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.reconcile import ScreenpipeReconciler

    repo = JournalRepository(":memory:")
    report = ScreenpipeReconciler(object(), repo).reconcile_record(
        "audio_123_derived", redacted=True, stable_id=False
    )
    assert report.redactions_applied == 0
    assert report.unreconcilable_derived_ids == ["audio_123_derived"]
    assert any("derived" in item for item in report.limitations)
