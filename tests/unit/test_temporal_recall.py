"""Unit tests for Temporal Recall and Correction History (PR-019).

Verifies Part 7.3 and Part 11 (PR-019):
1. Event-relative time anchor: '2026-09-10 明天' anchors to 2026-09-11.
2. Query-relative time anchor: '昨天' in query anchors to query invocation timestamp.
3. Repeated expression identity: '明天上午…明天下午…' produces 2 distinct mention_index rows with code-point spans.
4. Parse failure / no temporal expression: searches full Journal without restricting to 'last N hours'.
5. Pure temporal queries vs content-keyword queries.
6. Revision history UI DTO (EventHistoryDTO).
7. Context formatting for prompt injection.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest

from lva.journal.models import EventHistoryDTO
from lva.journal.repository import JournalRepository
from lva.journal.temporal import (
    extract_mentions,
    extract_query_temporal_range,
    resolve_temporal_range,
)


@pytest.fixture
def repo() -> JournalRepository:
    return JournalRepository(":memory:")


def test_event_relative_time_anchor():
    # Event happened on 2026-09-10
    event_dt = datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc)
    text = "明天做络合滴定实验"

    mentions = extract_mentions(text, event_dt)
    assert len(mentions) == 1
    m = mentions[0]

    assert m["expression"] == "明天"
    assert m["mention_index"] == 0

    # Range start/end must anchor to 2026-09-11
    start_dt = datetime.fromtimestamp(m["range_start_utc_us"] / 1_000_000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(m["range_end_utc_us"] / 1_000_000, tz=timezone.utc)

    assert start_dt.year == 2026 and start_dt.month == 9 and start_dt.day == 11
    assert end_dt.year == 2026 and end_dt.month == 9 and end_dt.day == 11


def test_repeated_expression_mention_index_and_spans():
    anchor = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    text = "明天上午开会，明天下午复盘"

    mentions = extract_mentions(text, anchor)
    assert len(mentions) == 2

    # Check distinct mention_index: 0, 1
    assert mentions[0]["mention_index"] == 0
    assert mentions[1]["mention_index"] == 1

    # Check half-open code point spans [start, end)
    span0 = text[mentions[0]["span_start"]:mentions[0]["span_end"]]
    span1 = text[mentions[1]["span_start"]:mentions[1]["span_end"]]
    assert span0 == "明天"
    assert span1 == "明天"
    assert mentions[0]["span_start"] < mentions[1]["span_start"]


def test_query_relative_time_anchor():
    # User asks "昨天说了什么", anchor is 2026-09-24
    query_anchor = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    query = "我昨天说了什么？"

    res = extract_query_temporal_range(query, query_anchor)
    assert res is not None
    start_dt, end_dt, expr = res
    assert expr == "昨天"
    assert start_dt.date() == datetime(2026, 9, 23).date()
    assert end_dt.date() == datetime(2026, 9, 23).date()


def test_pure_temporal_search(repo: JournalRepository):
    # Insert event on 2026-09-23
    t_yesterday = int(datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc).timestamp() * 1_000_000)
    # Insert event on 2026-09-20
    t_past = int(datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc).timestamp() * 1_000_000)

    repo.append_event(uuid4(), "昨天进行的备忘录音", occurred_at_utc_us=t_yesterday)
    repo.append_event(uuid4(), "更早之前的会议记录", occurred_at_utc_us=t_past)

    # Query anchored to 2026-09-24
    anchor_now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    hits = repo.search("我昨天说了什么？", query_anchor=anchor_now)

    assert len(hits) == 1
    assert hits[0]["raw_text"] == "昨天进行的备忘录音"


def test_mixed_temporal_and_keyword_search(repo: JournalRepository):
    # Two events on yesterday: one about chemistry, one about lunch
    t_yesterday = int(datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc).timestamp() * 1_000_000)
    repo.append_event(uuid4(), "昨天下午进行络合滴定实验", occurred_at_utc_us=t_yesterday)
    repo.append_event(uuid4(), "昨天中午吃火锅", occurred_at_utc_us=t_yesterday)

    anchor_now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    hits = repo.search("昨天络合滴定", query_anchor=anchor_now)

    assert len(hits) == 1
    assert hits[0]["raw_text"] == "昨天下午进行络合滴定实验"


def test_parse_failure_unrestricted_fts(repo: JournalRepository):
    """Part 7.3: parse failure must not arbitrarily restrict to 'last N hours'."""
    # Insert old event from 30 days ago
    t_old = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp() * 1_000_000)
    eid = uuid4()
    repo.append_event(eid, "三十天前的量子化学计算项目", occurred_at_utc_us=t_old)

    # Query has no temporal keyword or invalid temporal expression
    hits = repo.search("量子化学计算")
    assert len(hits) == 1
    assert hits[0]["raw_text"] == "三十天前的量子化学计算项目"


def test_event_history_dto(repo: JournalRepository):
    eid = uuid4()
    repo.append_event(eid, "明天上午做实验", occurred_at_utc_us=1000)
    repo.add_revision(eid, "明天上午做络合滴定实验", reason="specific_exp", actor="user")
    repo.add_revision(eid, "明天上午做高锰酸钾滴定实验", reason="chem_reagent", actor="user")

    history = repo.get_history(eid)
    assert isinstance(history, EventHistoryDTO)
    assert history.event_id == eid
    assert history.raw_text == "明天上午做实验"
    assert history.current_text == "明天上午做高锰酸钾滴定实验"
    assert history.current_revision == 2
    assert len(history.revisions) == 2
    assert history.revisions[0].corrected_text == "明天上午做络合滴定实验"
    assert history.revisions[1].corrected_text == "明天上午做高锰酸钾滴定实验"
    assert len(history.temporal_mentions) > 0


def test_format_history_context(repo: JournalRepository):
    hits = [
        {"occurred_at_utc_us": 1789000000_000_000, "speaker": "user", "current_text": "今天复习有机化学"},
        {"occurred_at_utc_us": 1789000010_000_000, "speaker": "assistant", "current_text": "收到，请问需要准备哪些资料？"},
    ]
    formatted = repo.format_history_context(hits)
    assert "user: 今天复习有机化学" in formatted
    assert "assistant: 收到，请问需要准备哪些资料？" in formatted


def test_revised_event_isolates_superseded_temporal_mentions(repo: JournalRepository):
    """When an event is revised and time expression changes, obsolete mentions must not trigger recall."""
    t_base = int(datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc).timestamp() * 1_000_000)
    eid = uuid4()
    # Rev 0: "明天做络合滴定实验" -> refers to 2026-09-21
    repo.append_event(eid, "明天做络合滴定实验", occurred_at_utc_us=t_base)

    # Querying "明天" before revision matches
    anchor_sep20 = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    hits_before = repo.search("明天做络合滴定", query_anchor=anchor_sep20)
    assert len(hits_before) == 1

    # Rev 1: Revised to "上周做络合滴定实验" -> refers to last week
    repo.add_revision(eid, "上周做络合滴定实验", reason="correct_time", actor="user")

    # Querying "明天" now must NOT match because the active revision no longer mentions "明天"
    hits_after_tomorrow = repo.search("明天做络合滴定", query_anchor=anchor_sep20)
    assert len(hits_after_tomorrow) == 0

    # Querying "上周" matches the active revision
    hits_after_last_week = repo.search("上周做络合滴定", query_anchor=anchor_sep20)
    assert len(hits_after_last_week) == 1
    assert hits_after_last_week[0]["current_text"] == "上周做络合滴定实验"


def test_cjk_fts_phrase_query_precision(repo: JournalRepository):
    """Phrase query must match adjacent CJK sequence, not scattered individual characters."""
    eid1 = uuid4()
    eid2 = uuid4()
    # eid1 contains exact phrase "络合滴定"
    repo.append_event(eid1, "今天做络合滴定实验")
    # eid2 contains the characters "络", "合", "滴", "定" scattered across the sentence
    repo.append_event(eid2, "在联合会合适的时候滴水观察，定价公道")

    hits = repo.search("络合滴定")
    assert len(hits) == 1
    assert hits[0]["event_id"] == str(eid1)


def test_non_temporal_query_preserves_filler_nouns(repo: JournalRepository):
    """Non-temporal queries must not strip nouns like '计划', '安排', '对话'."""
    eid = uuid4()
    repo.append_event(eid, "这是我们小组的复习计划和工作安排")

    hits1 = repo.search("复习计划")
    assert len(hits1) == 1
    assert hits1[0]["event_id"] == str(eid)

    hits2 = repo.search("工作安排")
    assert len(hits2) == 1
    assert hits2[0]["event_id"] == str(eid)


def test_timezone_offset_midnight_anchoring(repo: JournalRepository):
    """Timezone offset determines local calendar day: 23:30 UTC is next morning in UTC+8."""
    # 2026-09-20 23:30:00 UTC = 2026-09-21 07:30:00 UTC+8
    t_utc = int(datetime(2026, 9, 20, 23, 30, tzinfo=timezone.utc).timestamp() * 1_000_000)
    eid = uuid4()
    repo.append_event(
        eid,
        "今天上午安排讨论会",
        occurred_at_utc_us=t_utc,
        event_timezone="UTC+08:00",
        utc_offset_minutes=480,
    )

    history = repo.get_history(eid)
    assert history is not None
    assert len(history.temporal_mentions) == 1
    m = history.temporal_mentions[0]

    # In local time UTC+8, the event date was 2026-09-21, so "今天" must span 2026-09-21 local day
    # 2026-09-21 00:00:00+08:00 in UTC is 2026-09-20 16:00:00 UTC
    tz_beijing = timezone(timedelta(hours=8))
    start_dt = datetime.fromtimestamp(m.range_start_utc_us / 1_000_000, tz=tz_beijing)
    assert start_dt.date() == datetime(2026, 9, 21).date()

