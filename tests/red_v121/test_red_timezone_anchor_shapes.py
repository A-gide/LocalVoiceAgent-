"""PR-019 boundary: timezone resolution must be right for the shapes we store.

The formal acceptance record for PR-019
(docs/PR-016-019-FORMAL-ACCEPTANCE-2026-09-24.md) listed the DST item as covered
only for a fixed offset, with the real IANA case as an open boundary:
"real IANA timezone summer-time transition days are not covered".

Investigating that boundary produced a **withdrawn** finding first, and the
withdrawal is the useful part:

    _resolve_timezone("Asia/Shanghai", 0)  ->  UTC   (on a machine without tzdata)

That looks like a silent fallback that moves the local calendar day by one.  It
is not reachable, because **no producer ever stores an IANA name**:

* `screenpipe_importer/normalize.py` L24 writes `UTC+08:00` *and* the matching
  `utc_offset_minutes`;
* `worker.py` L95/L96 passes both through;
* `_resolve_timezone` falls back to the offset when a name does not resolve, so
  the offset -- not UTC -- is what the anchor uses.

An earlier draft of this file asserted the unreachable combination (a name with
`offset_mins=0`) and failed.  That was a defect in the test, not the product:
the assertion demanded behaviour for an input the product cannot produce.
It was rewritten to test the shapes that actually reach the repository, which is
also what the acceptance item asked for.

What is pinned here:

1. every stored shape resolves to the correct local day;
2. an unresolvable name with a real offset still lands on the offset, so the
   degraded path is not a silent UTC fallback;
3. the offset is what disambiguates, so a name that cannot be resolved does not
   cost the caller the local-day boundary.

Boundary: a true IANA summer-time *transition day* remains untested because no
code path stores an IANA name.  If a future slice starts storing names, this file
is the place to add the transition-day case -- and the silent-fallback question
becomes live at that point.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from lva.journal.repository import JournalRepository, _resolve_timezone

pytestmark = pytest.mark.red_v121


def _utc(y: int, mo: int, d: int, h: int, mi: int) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


# 23:30 UTC is 07:30 the *next* day at UTC+8 -- the boundary that makes a wrong
# resolution visible as a one-day error rather than a rounding difference.
EVENING_UTC = _utc(2026, 9, 20, 23, 30)
EXPECTED_LOCAL_DAY = datetime(2026, 9, 21).date()


def test_the_stored_screenpipe_shape_resolves_to_the_right_local_day() -> None:
    """normalize.py writes UTC+08:00 together with offset 480; both must agree."""
    local = EVENING_UTC.astimezone(_resolve_timezone("UTC+08:00", 480))
    assert local.date() == EXPECTED_LOCAL_DAY, (
        f"the stored shape resolved to {local!r}; an evening UTC event must land "
        "on the next local day at UTC+8"
    )


def test_an_unresolvable_name_still_uses_the_offset_not_utc() -> None:
    """The degraded path must fall back to the offset, never to a silent UTC."""
    local = EVENING_UTC.astimezone(_resolve_timezone("Not/AZone", 480))
    assert local.date() == EXPECTED_LOCAL_DAY, (
        f"an unknown name with offset 480 resolved to {local!r}; falling back to "
        "UTC here would move the local day and mis-anchor today"
    )


def test_the_offset_alone_is_enough_to_anchor_the_day() -> None:
    local = EVENING_UTC.astimezone(_resolve_timezone(None, 480))
    assert local.date() == EXPECTED_LOCAL_DAY


def test_utc_events_stay_on_their_utc_day() -> None:
    """The control case: no offset means no shift, so the assertion above bites."""
    local = EVENING_UTC.astimezone(_resolve_timezone("UTC", 0))
    assert local.date() == datetime(2026, 9, 20).date()


def test_a_stored_event_anchors_today_to_the_local_day() -> None:
    """End to end: the provenance and the anchor must describe one day."""
    repo = JournalRepository()
    t_utc = int(EVENING_UTC.timestamp() * 1_000_000)

    eid = uuid4()
    repo.append_event(
        eid,
        "今天上午开会",
        occurred_at_utc_us=t_utc,
        event_timezone="UTC+08:00",
        utc_offset_minutes=480,
    )

    history = repo.get_history(eid)
    assert history is not None
    assert history.temporal_mentions, "a temporal mention must be recorded"
    m = history.temporal_mentions[0]

    # Local day 2026-09-21 at UTC+8 starts 2026-09-20 16:00 UTC.
    start = datetime.fromtimestamp(m.range_start_utc_us / 1_000_000, tz=timezone.utc)
    assert start == _utc(2026, 9, 20, 16, 0), (
        f"today anchored at {start!r}; it must start on the local day the event "
        "actually fell in"
    )
    # The range spans the local day; the implementation ends it one microsecond
    # short of the next midnight (exclusive end), so compare the day boundary
    # rather than an exact microsecond count.
    span = timedelta(microseconds=m.range_end_utc_us - m.range_start_utc_us)
    assert timedelta(days=1) - span < timedelta(seconds=1), (
        f"today must span one local day, got {span}"
    )
