"""Long-term memory: local transcript archive with real full-text search.

Everything lives in one SQLite file under this project's own `data` directory.
Nothing is sent anywhere, and no embeddings or cloud indexes are involved.

Searching Chinese with FTS5 needs care: the stock `unicode61` tokenizer treats a
whole Chinese clause as a single token, so `络合滴定` would never be found inside
`我准备比较两种络合滴定方案`.  The table therefore stores a *segmented* copy of
the text (every CJK character separated by a space) and queries are segmented the
same way, which turns a phrase search into an ordinary FTS5 phrase query.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS utterances (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,          -- unix seconds
    source      TEXT    NOT NULL,          -- 'live' | 'recording'
    speaker     TEXT    DEFAULT '',
    raw_text    TEXT    NOT NULL,
    fixed_text  TEXT    NOT NULL,
    domain      TEXT    DEFAULT 'general',
    audio_path  TEXT    DEFAULT '',
    duration_s  REAL    DEFAULT 0,
    meta        TEXT    DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_utt_ts ON utterances(ts);

CREATE VIRTUAL TABLE IF NOT EXISTS utterances_fts USING fts5(
    seg_text, raw_seg,
    content='',                       -- external content: we control the rows
    tokenize='unicode61'
);
"""

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def segment(text: str) -> str:
    """Insert spaces around every CJK character so FTS5 can index it."""
    if not text:
        return ""
    out = []
    for ch in text:
        if _CJK.match(ch):
            out.append(" ")
            out.append(ch)
            out.append(" ")
        else:
            out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _phrase_query(query: str) -> str:
    tokens = [t for t in segment(query).split(" ") if t]
    if not tokens:
        return ""
    escaped = [t.replace('"', '""') for t in tokens]
    return '"' + " ".join(escaped) + '"'


@dataclass
class Hit:
    id: int
    ts: float
    iso: str
    source: str
    raw_text: str
    fixed_text: str
    domain: str
    audio_path: str
    score: float = 0.0

    def as_dict(self) -> dict:
        return {"id": self.id, "ts": self.ts, "iso": self.iso, "source": self.source,
                "raw": self.raw_text, "text": self.fixed_text, "domain": self.domain,
                "audio": self.audio_path, "score": round(self.score, 4)}


@dataclass
class HistoryQuery:
    """What a deterministic history question looks like once parsed."""
    intent: str                     # 'recall' | 'affirm' | 'plain'
    since: float | None = None
    until: float | None = None
    keywords: list[str] = field(default_factory=list)
    raw: str = ""

    def window_label(self) -> str:
        if self.since is None:
            return "all time"
        days = (time.time() - self.since) / 86400.0
        if days < 0.1:
            return "the last few minutes"
        if days < 1.5:
            return "today"
        if days < 2.5:
            return "yesterday"
        if days < 8:
            return "the past week"
        return f"the past {int(days)} days"


class Memory:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or config.DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    # ------------------------------------------------------------------ write
    def add(self, raw_text: str, fixed_text: str | None = None, source: str = "live",
            domain: str = "general", speaker: str = "", audio_path: str = "",
            duration_s: float = 0.0, ts: float | None = None,
            meta: dict | None = None) -> int:
        ts = ts if ts is not None else time.time()
        fixed = fixed_text if fixed_text is not None else raw_text
        cur = self._db.execute(
            "INSERT INTO utterances (ts, source, speaker, raw_text, fixed_text, domain,"
            " audio_path, duration_s, meta) VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, source, speaker, raw_text, fixed, domain, audio_path, duration_s,
             json.dumps(meta or {}, ensure_ascii=False)),
        )
        rid = int(cur.lastrowid)
        self._db.execute(
            "INSERT INTO utterances_fts (rowid, seg_text, raw_seg) VALUES (?,?,?)",
            (rid, segment(fixed), segment(raw_text)),
        )
        self._db.commit()
        return rid

    def forget(self, rid: int) -> None:
        self._db.execute("DELETE FROM utterances WHERE id=?", (rid,))
        self._db.execute("DELETE FROM utterances_fts WHERE rowid=?", (rid,))
        self._db.commit()

    # ------------------------------------------------------------------- read
    @staticmethod
    def _iso(ts: float) -> str:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    def _hit(self, row: sqlite3.Row, score: float = 0.0) -> Hit:
        return Hit(id=row["id"], ts=row["ts"], iso=self._iso(row["ts"]),
                   source=row["source"], raw_text=row["raw_text"],
                   fixed_text=row["fixed_text"], domain=row["domain"],
                   audio_path=row["audio_path"], score=score)

    def search(self, query: str, limit: int = 20, since: float | None = None,
               until: float | None = None, exclude_ids: set[int] | None = None) -> list[Hit]:
        """FTS5 phrase search, newest first, with a LIKE fallback.

        `exclude_ids` exists because the utterance being asked about has already
        been archived by the time the history router runs - without this, a
        question like "我昨天说过要去火星吗" matches itself and looks like
        evidence that the user really did say it.
        """
        q = _phrase_query(query)
        hits: list[Hit] = []
        skip = exclude_ids or set()
        if q:
            sql = ("SELECT u.*, bm25(utterances_fts) AS rank FROM utterances_fts f "
                   "JOIN utterances u ON u.id = f.rowid WHERE utterances_fts MATCH ?")
            params: list = [q]
            if since is not None:
                sql += " AND u.ts >= ?"
                params.append(since)
            if until is not None:
                sql += " AND u.ts <= ?"
                params.append(until)
            sql += " ORDER BY u.ts DESC LIMIT ?"
            params.append(limit + len(skip))
            try:
                for row in self._db.execute(sql, params):
                    if row["id"] not in skip:
                        hits.append(self._hit(row, -float(row["rank"])))
            except sqlite3.OperationalError:
                hits = []
            hits = hits[:limit]
        if not hits:
            like = f"%{query}%"
            sql = ("SELECT * FROM utterances WHERE (fixed_text LIKE ? OR raw_text LIKE ?)")
            params = [like, like]
            if since is not None:
                sql += " AND ts >= ?"
                params.append(since)
            if until is not None:
                sql += " AND ts <= ?"
                params.append(until)
            sql += " ORDER BY ts DESC LIMIT ?"
            params.append(limit + len(skip))
            hits = [self._hit(r) for r in self._db.execute(sql, params)
                    if r["id"] not in skip][:limit]
        return hits

    def recent(self, limit: int = 10, source: str | None = None) -> list[Hit]:
        sql = "SELECT * FROM utterances"
        params: list = []
        if source:
            sql += " WHERE source=?"
            params.append(source)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        return [self._hit(r) for r in self._db.execute(sql, params)]

    def stats(self) -> dict:
        row = self._db.execute(
            "SELECT COUNT(*) n, MIN(ts) first, MAX(ts) last,"
            " SUM(duration_s) dur FROM utterances").fetchone()
        by_source = {r["source"]: r["n"] for r in self._db.execute(
            "SELECT source, COUNT(*) n FROM utterances GROUP BY source")}
        return {"count": row["n"] or 0,
                "first": self._iso(row["first"]) if row["first"] else None,
                "last": self._iso(row["last"]) if row["last"] else None,
                "audio_hours": round((row["dur"] or 0) / 3600.0, 3),
                "by_source": by_source}

    def close(self) -> None:
        self._db.close()


# ------------------------------------------------------------ history router
# Deterministic, keyword-based.  A weak local model cannot be trusted to decide
# whether to consult the archive, so obvious history questions are routed here
# before the LLM ever sees them.
_RECALL_VERBS = re.compile(r"(说过|讲过|提过|提到过|聊过|谈过|回忆|回想|记不记得|还记得|说|讲|聊|谈|提)")
_FIRST_PERSON = re.compile(r"(我|我们|咱)")
_TIME_WORDS = re.compile(
    r"(刚才|刚刚|今天|昨天|前天|上周|上回|上次|最近|之前|以前|这几天|昨晚|早上|上午|下午|晚上|上个月)")
_HISTORY_TRIGGERS = re.compile(
    r"(说过|讲过|提过|提到过|聊过|谈过|回忆|回想|记不记得|还记得|"
    r"什么时候说|啥时候说|何时说|是不是说过|有没有说过|本地历史|现实记录|本地记录)")

_HISTORY_PATTERNS: list[tuple[str, str]] = [
    (r"我[^，。？！?]{0,8}(说过|讲过|提过|提到过|聊过|谈过|是不是说过)", "recall"),
    (r"(我什么时候|啥时候|何时)(说过|讲过|提过|提到)", "recall"),
    (r"(帮我)?(回忆|回想)(一下)?", "recall"),
    (r"记不记得|还记得", "recall"),
    (r"(说|讲|聊|谈|提)了(什么|啥|哪些)", "recall"),
    (r"(本地|现实)(历史|记录|记忆)", "recall"),
    (r"(刚|刚刚|今天|昨天|前天|上周|上回|上次|最近|之前|以前|这几天)[^，。？！?]{0,6}"
     r"(说|讲|聊|谈|提|做|干)", "recall"),
]

_TIME_WINDOWS: list[tuple[str, float]] = [
    ("刚才", 15 * 60), ("刚刚", 15 * 60),
    ("今天", 24 * 3600), ("今天下午", 24 * 3600), ("上午", 24 * 3600),
    ("昨天", 2 * 86400), ("前天", 3 * 86400), ("昨晚", 2 * 86400),
    ("上周", 8 * 86400), ("这周", 8 * 86400), ("本周", 8 * 86400),
    ("上个月", 32 * 86400), ("最近", 8 * 86400), ("这几天", 8 * 86400),
    ("之前", 30 * 86400), ("以前", None), ("上次", None), ("上回", None),
]

_STOPWORDS = {
    "我", "我们", "你", "他", "她", "它", "的", "了", "是", "在", "有", "和", "与",
    "说", "讲", "提", "聊", "谈", "过", "吗", "呢", "什么", "怎么", "为什么",
    "今天", "昨天", "前天", "上周", "最近", "之前", "以前", "刚才", "刚刚",
    "帮我", "回忆", "回想", "查一下", "找一下", "搜一下", "记不记得", "还记得",
    "本地", "历史", "记录", "记忆", "一下", "时候", "何时", "啥时候",
}


def parse_history_query(text: str) -> HistoryQuery | None:
    """Return a HistoryQuery when `text` is plainly about past conversations.

    Deliberately generous: a false positive costs one local database lookup,
    while a false negative is what makes the assistant claim it has no memory.
    """
    if not text:
        return None
    t = text.strip()

    matched = _HISTORY_TRIGGERS.search(t) is not None
    if not matched:
        for pattern, kind in _HISTORY_PATTERNS:
            if re.search(pattern, t):
                matched = True
                break
    if not matched:
        # A recall verb together with a first person or a time word also counts,
        # which is what catches "我昨天是不是说过..." where words sit in between.
        if _RECALL_VERBS.search(t) and (_FIRST_PERSON.search(t) or _TIME_WORDS.search(t)):
            matched = True
    if not matched:
        return None
    intent = "recall"

    now = time.time()
    since: float | None = None
    for word, span in _TIME_WINDOWS:
        if word in t:
            if span is None:
                since = None
            elif since is None or span < (now - since):
                since = now - span
    keywords = _extract_keywords(t)
    return HistoryQuery(intent=intent, since=since, until=None, keywords=keywords, raw=t)


def _extract_keywords(text: str) -> list[str]:
    """Content words left after removing the question scaffolding."""
    from . import vocab

    terms = [t for t in vocab.default().known_terms() if t in text]
    cleaned = text
    for w in sorted(_STOPWORDS, key=len, reverse=True):
        cleaned = cleaned.replace(w, " ")
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", cleaned)
    words = [w for w in cleaned.split() if w and w not in _STOPWORDS]
    words = [w for w in words if len(w) > 1 and not w.isdigit()]
    out: list[str] = []
    for w in terms + words:
        if w not in out:
            out.append(w)
    return out


def search_history(mem: Memory, hq: HistoryQuery, limit: int = 5,
                   exclude_ids: set[int] | None = None) -> list[Hit]:
    """Run the parsed query, widening only when the question named no topic.

    If the question *did* name a topic ("火星") and nothing matches, an empty
    result is the correct answer - falling back to unrelated recent entries here
    is how an assistant ends up pretending it remembers something.
    """
    if not hq.keywords:
        return mem.recent(limit=limit)
    seen: dict[int, Hit] = {}
    for kw in hq.keywords:
        for hit in mem.search(kw, limit=limit, since=hq.since, exclude_ids=exclude_ids):
            seen.setdefault(hit.id, hit)
    if not seen:
        return []
    hits = sorted(seen.values(), key=lambda h: (-h.ts,))
    return hits[:limit]


def format_history_context(hits: Iterable[Hit], max_chars: int = 1200) -> str:
    """Compact evidence block for the LLM.  Never invents anything.

    Snippets are annotated with an absolute-time anchor when they contain a
    relative time expression.  Without it a row recorded as "明天去爬山" still
    reads as *tomorrow* when it is retrieved three weeks later - and because the
    block sits next to the question, that is exactly what the model repeats back.
    The anchor states what the words meant at the time, using the row's own
    timestamp; it does not rewrite the record.
    """
    lines = []
    for h in hits:
        lines.append(f"[{h.iso} | {h.source}] {h.fixed_text}")
        anchor = relative_time_anchor(h.fixed_text, h.ts)
        if anchor:
            lines.append(anchor)
    block = "\n".join(lines)
    return block[:max_chars]


# Words whose meaning depends on when the sentence was spoken.  Deliberately
# narrow: a false positive costs a line of prompt, but naming 现在/今天 as
# "anchored" while they are still being reinterpreted would be worse.
RELATIVE_TIME_TOKENS = (
    "今天", "今日", "今晚", "今早", "明天", "明晚", "昨天", "昨晚", "前天", "后天",
    "上周", "这周", "本周", "下周", "上个月", "这个月", "下个月", "去年", "今年",
    "明年", "上次", "上回", "下次", "最近", "这几天", "这段时间", "刚才", "刚刚",
    "一会儿", "过几天", "过两天", "大后天", "前几天",
)


def relative_time_anchor(text: str, ts: float) -> str:
    """An anchor line for a snippet whose words mean something time-dependent."""
    if not text or not any(tok in text for tok in RELATIVE_TIME_TOKENS):
        return ""
    when = datetime.fromtimestamp(ts)
    return (f"    （相对时间锚点：上一条中的“今天/明天/昨天/最近”等说法，"
            f"指的是 {when.strftime('%Y-%m-%d %H:%M')} 当时的含义，"
            f"不要按当前日期重新理解。）")
