from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone

TEMPORAL_PATTERNS = [
    (r"(刚才|刚刚)", "just_now"),
    (r"(前天)", "day_before_yesterday"),
    (r"(昨天|昨日)", "yesterday"),
    (r"(今天|今日)", "today"),
    (r"(明天|明日)", "tomorrow"),
    (r"(后天)", "day_after_tomorrow"),
    (r"(上周)", "last_week"),
    (r"(本周|这周)", "this_week"),
    (r"(下周)", "next_week"),
]


def resolve_temporal_range(
    expression_type: str,
    anchor: datetime,
) -> tuple[datetime, datetime]:
    """Resolve an expression type into a [start_utc, end_utc] window anchored to `anchor`."""
    tz = anchor.tzinfo or timezone.utc
    anchor_date = anchor.date()

    if expression_type == "just_now":
        return anchor - timedelta(minutes=15), anchor

    elif expression_type == "today":
        start = datetime.combine(anchor_date, time.min, tzinfo=tz)
        end = datetime.combine(anchor_date, time.max, tzinfo=tz)
        return start, end

    elif expression_type == "yesterday":
        target = anchor_date - timedelta(days=1)
        start = datetime.combine(target, time.min, tzinfo=tz)
        end = datetime.combine(target, time.max, tzinfo=tz)
        return start, end

    elif expression_type == "day_before_yesterday":
        target = anchor_date - timedelta(days=2)
        start = datetime.combine(target, time.min, tzinfo=tz)
        end = datetime.combine(target, time.max, tzinfo=tz)
        return start, end

    elif expression_type == "tomorrow":
        target = anchor_date + timedelta(days=1)
        start = datetime.combine(target, time.min, tzinfo=tz)
        end = datetime.combine(target, time.max, tzinfo=tz)
        return start, end

    elif expression_type == "day_after_tomorrow":
        target = anchor_date + timedelta(days=2)
        start = datetime.combine(target, time.min, tzinfo=tz)
        end = datetime.combine(target, time.max, tzinfo=tz)
        return start, end

    elif expression_type == "this_week":
        # Monday is 0
        monday = anchor_date - timedelta(days=anchor_date.weekday())
        sunday = monday + timedelta(days=6)
        start = datetime.combine(monday, time.min, tzinfo=tz)
        end = datetime.combine(sunday, time.max, tzinfo=tz)
        return start, end

    elif expression_type == "last_week":
        monday = anchor_date - timedelta(days=anchor_date.weekday() + 7)
        sunday = monday + timedelta(days=6)
        start = datetime.combine(monday, time.min, tzinfo=tz)
        end = datetime.combine(sunday, time.max, tzinfo=tz)
        return start, end

    elif expression_type == "next_week":
        monday = anchor_date - timedelta(days=anchor_date.weekday() - 7)
        sunday = monday + timedelta(days=6)
        start = datetime.combine(monday, time.min, tzinfo=tz)
        end = datetime.combine(sunday, time.max, tzinfo=tz)
        return start, end

    return anchor - timedelta(days=1), anchor


def extract_query_temporal_range(
    query: str,
    query_anchor: datetime | None = None,
) -> tuple[datetime, datetime, str] | None:
    """Parse relative time from a query using the query time as anchor.

    If parsing succeeds, returns (start_utc, end_utc, matched_expression).
    If no temporal expression is found or parsing fails, returns None.
    """
    if query_anchor is None:
        query_anchor = datetime.now(timezone.utc)

    for pattern, exp_type in TEMPORAL_PATTERNS:
        match = re.search(pattern, query)
        if match:
            matched_str = match.group(0)
            start_dt, end_dt = resolve_temporal_range(exp_type, query_anchor)
            return start_dt, end_dt, matched_str

    return None


def extract_mentions(
    text: str,
    anchor_utc_us: int | datetime,
) -> list[dict]:
    """Parse relative time mentions from text using anchor timestamp.

    Iterates over TEMPORAL_PATTERNS in text, extracts half-open Unicode
    code-point spans [span_start, span_end), sorts mentions by span_start,
    and assigns mention_index (0, 1, 2...).
    """
    if isinstance(anchor_utc_us, datetime):
        if anchor_utc_us.tzinfo is None:
            anchor_dt = anchor_utc_us.replace(tzinfo=timezone.utc)
        else:
            anchor_dt = anchor_utc_us
        anchor_us = int(anchor_dt.timestamp() * 1_000_000)
    else:
        anchor_us = int(anchor_utc_us)
        anchor_dt = datetime.fromtimestamp(anchor_us / 1_000_000, tz=timezone.utc)

    raw_matches: list[tuple[int, int, str, str]] = []
    for pattern, exp_type in TEMPORAL_PATTERNS:
        for match in re.finditer(pattern, text):
            raw_matches.append((match.start(), match.end(), match.group(0), exp_type))

    raw_matches.sort(key=lambda m: (m[0], m[1]))

    mentions: list[dict] = []
    for idx, (span_start, span_end, expr, exp_type) in enumerate(raw_matches):
        try:
            start_dt, end_dt = resolve_temporal_range(exp_type, anchor_dt)
            r_start = int(start_dt.timestamp() * 1_000_000)
            r_end = int(end_dt.timestamp() * 1_000_000)
            status = "parsed"
        except Exception:
            r_start = None
            r_end = None
            status = "failed"

        mentions.append({
            "mention_index": idx,
            "span_start": span_start,
            "span_end": span_end,
            "expression": expr,
            "anchor_utc_us": anchor_us,
            "range_start_utc_us": r_start,
            "range_end_utc_us": r_end,
            "parser_version": "1.0",
            "parse_status": status,
        })
    return mentions


def extract_event_temporal_mentions(
    text: str,
    event_anchor: datetime,
) -> list[dict]:
    """Parse relative time mentions from event text using event timestamp as anchor."""
    return extract_mentions(text, event_anchor)


def clean_search_query(query: str, matched_temporal_expr: str | None = None) -> str:
    """Clean query for text/FTS search by removing temporal expression and question filler.

    If the query only asked a generic question anchored in time (e.g. '我昨天说了什么？'),
    the returned keyword is empty string, indicating pure temporal recall.
    If specific content keywords exist (e.g. '昨天吃火锅'), returns '吃火锅'.
    """
    cleaned = query
    if matched_temporal_expr:
        cleaned = re.sub(re.escape(matched_temporal_expr), "", cleaned)

    # Strip pronouns at start (e.g. "我", "你", "我们")
    cleaned = re.sub(r"^[我你您他她它我们大家]+", "", cleaned)

    # Strip common Chinese question filler patterns
    fillers = [
        r"(说|讲|聊|谈|提)了?(什么|啥|哪些)",
        r"(做|搞)了?(什么|啥|哪些)",
        r"有(什么|啥|哪些)",
        r"(的)?(安排|计划|事情|内容|记录|历史|对话)",
        r"[？?吗呢呀吧啊了]",
    ]
    for p in fillers:
        cleaned = re.sub(p, "", cleaned)

    return cleaned.strip()

