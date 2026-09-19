"""
Memory Router & Scientific Terminology Engine for Open-LLM-VTuber
Implements MASTER_PROMPT.md Sections 6, 18, 19, 20, 21.

Features:
- Portable dynamic path resolution without hardcoding (respects LVA_ROOT).
- Domain-gated, confidence-aware scientific terminology correction.
- SQL push-down with temporal filtering and LIKE/FTS queries over Screenpipe SQLite.
- Realistic start_time and end_time offsets in Screenpipe archive (no fake 0.0/3.0).
- Real-time FTS5 synchronization.
"""
from __future__ import annotations

import os
import re
import json
import sqlite3
import datetime
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional
from dataclasses import dataclass, field
import jieba
from loguru import logger

def get_lva_root() -> Path:
    env_root = os.environ.get("LVA_ROOT")
    if env_root and Path(env_root).exists():
        return Path(env_root).resolve()
    # Relative from apps/open-llm-vtuber/src/open_llm_vtuber/memory_router.py -> 4 levels up
    try:
        cand = Path(__file__).resolve().parents[4]
        if cand.exists() and (cand / "vocabulary").exists():
            return cand
    except IndexError:
        pass
    try:
        cand3 = Path(__file__).resolve().parents[3]
        if cand3.exists() and (cand3 / "vocabulary").exists():
            return cand3
    except IndexError:
        pass
    return Path(os.getcwd()).resolve()

BASE_DIR = get_lva_root()
VOCAB_DIR = Path(os.environ.get("LVA_VOCAB_DIR", str(BASE_DIR / "vocabulary")))
SCREENPIPE_DB = Path(os.environ.get("SCREENPIPE_DB_PATH", str(BASE_DIR / "screenpipe-data" / "db.sqlite")))

def load_user_profile() -> Dict[str, Any]:
    """Loads user profile from user_profile.json if it exists."""
    profile_path = BASE_DIR / "user_profile.json"
    if profile_path.exists():
        try:
            with open(profile_path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read user profile at {profile_path}: {e}")
    return {}

# ----------------- Terminology Post-Processing (Section 6) -----------------
@dataclass
class CorrectionRule:
    src: str
    dst: str
    domain: str = "general"
    confidence: float = 0.5
    note: str = ""

@dataclass
class CorrectedText:
    raw: str
    corrected: str
    applied: List[Dict[str, Any]] = field(default_factory=list)
    domain: str = "general"
    flags: List[str] = field(default_factory=list)

class TerminologyEngine:
    def __init__(self, vocab_dir: Path):
        self.vocab_dir = vocab_dir
        self.domain_terms: Dict[str, set[str]] = self._load_domain_terms()
        self.rules: List[CorrectionRule] = self._load_rules()
        self._latin = re.compile(r"[A-Za-z][A-Za-z0-9\-']{2,}")

    def _load_domain_terms(self) -> Dict[str, set[str]]:
        terms: Dict[str, set[str]] = {}
        for dom in ("chemistry", "physics", "biology", "names"):
            fn = self.vocab_dir / f"{dom}.txt"
            if fn.exists():
                try:
                    lines = fn.read_text(encoding="utf-8", errors="ignore").splitlines()
                    s = {line.strip() for line in lines if line.strip() and not line.startswith("#")}
                    terms[dom] = s
                except Exception as e:
                    logger.warning(f"Failed to load domain term file {fn}: {e}")
            else:
                terms[dom] = set()
        return terms

    def _load_rules(self) -> List[CorrectionRule]:
        corr_file = self.vocab_dir / "corrections.json"
        rules = []
        if corr_file.exists():
            try:
                data = json.loads(corr_file.read_text(encoding="utf-8"))
                for r in data.get("rules", []):
                    rules.append(CorrectionRule(
                        src=r.get("from", ""),
                        dst=r.get("to", ""),
                        domain=r.get("domain") or "general",
                        confidence=float(r.get("confidence", 0.5)),
                        note=r.get("note", "")
                    ))
            except Exception as e:
                logger.error(f"Failed to load corrections.json: {e}")
        return rules

    def detect_domain(self, text: str) -> str:
        scores = {d: 0 for d in ("chemistry", "physics", "biology")}
        low = text.lower()
        for dom, term_set in self.domain_terms.items():
            if dom == "names":
                continue
            for t in term_set:
                if t.lower() in low:
                    scores[dom] = scores.get(dom, 0) + 1
        best_dom, best_score = max(scores.items(), key=lambda kv: kv[1])
        return best_dom if best_score > 0 else "general"

    def correct(self, text: str, domain: Optional[str] = None) -> CorrectedText:
        if not text:
            return CorrectedText(raw="", corrected="", applied=[], domain="general")

        detected_dom = domain or self.detect_domain(text)
        out = text
        applied: List[Dict[str, Any]] = []

        for r in self.rules:
            if not r.src or not r.dst or r.src == r.dst:
                continue
            if r.src not in out:
                continue

            # Domain gating: prevent false-positive rewrite when domain contradicts
            if r.domain != "general" and detected_dom != "general" and r.domain != detected_dom:
                continue
            if r.domain != "general" and detected_dom == "general":
                # Check for explicit domain evidence
                has_evidence = any(t.lower() in text.lower() for t in self.domain_terms.get(r.domain, set()))
                if not has_evidence and r.confidence < 0.85:
                    continue

            if r.confidence < 0.6:
                continue

            # Word boundary check for pure Latin/alphanumeric tokens
            if re.match(r"^[A-Za-z0-9_\-]+$", r.src):
                pattern = re.compile(r"\b" + re.escape(r.src) + r"\b", re.IGNORECASE)
                if not pattern.search(out):
                    continue
                out = pattern.sub(r.dst, out)
            else:
                out = out.replace(r.src, r.dst)

            applied.append({
                "from": r.src,
                "to": r.dst,
                "domain": r.domain,
                "confidence": r.confidence
            })
            logger.info(f"Terminology fix applied: '{r.src}' -> '{r.dst}' (domain={r.domain}, conf={r.confidence})")

        flags = self._flag_unknown_latin(out)
        return CorrectedText(raw=text, corrected=out, applied=applied, domain=detected_dom, flags=flags)

    def _flag_unknown_latin(self, text: str) -> List[str]:
        known = {t.lower() for s in self.domain_terms.values() for t in s}
        common = {"the", "and", "for", "with", "that", "this", "is", "of", "a", "in",
                  "to", "it", "you", "i", "we", "on", "at", "as", "be", "are", "mode", "fast", "deep"}
        flags = []
        for tok in self._latin.findall(text):
            if tok.lower() in known or tok.lower() in common:
                continue
            flags.append(tok)
        return flags

_engine_instance: Optional[TerminologyEngine] = None

def get_terminology_engine() -> TerminologyEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = TerminologyEngine(VOCAB_DIR)
    return _engine_instance

def correct_scientific_terminology(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    engine = get_terminology_engine()
    res = engine.correct(text)
    return res.corrected, res.applied


# ----------------- Deterministic Memory Router (Section 18, 19, 20) -----------------
TEMPORAL_TRIGGERS = [
    "刚才", "刚刚", "昨天", "今天", "之前", "我说过什么", "提过", 
    "回忆", "是不是说过", "有没有说过", "说过", "记录", "ALPHA-",
    "过去我说", "前天", "上次"
]

STOP_WORDS = set([
    "刚才", "刚刚", "昨天", "今天", "明天", "之前", "过去", "以前", "上次",
    "关于", "说了", "说过", "什么", "是不是", "有没有", "请问", "一下",
    "帮我", "回忆", "记得", "内容", "方案", "准备", "两个", "一种",
    "自己", "知道", "我们", "你们", "他们", "这个", "那个", "我"
])

def is_temporal_query(text: str) -> bool:
    t = text.lower()
    return any(trigger.lower() in t for trigger in TEMPORAL_TRIGGERS)

def query_screenpipe_history(query_text: str) -> Dict[str, Any]:
    if not SCREENPIPE_DB.exists():
        return {
            "found": False,
            "records": [],
            "context_prompt": "【本地现实历史记录】：本地录音数据库暂无记录。请如实回答没有找到任何历史记录，严禁编造。"
        }

    now = datetime.datetime.now(datetime.timezone.utc)
    time_filter_sql = ""
    time_params: List[Any] = []
    window_name = "全部历史"

    # Temporal window bounds
    if "刚才" in query_text or "刚刚" in query_text:
        window_name = "刚才 (最近30分钟)"
        cutoff = (now - datetime.timedelta(minutes=30)).isoformat()
        time_filter_sql = "AND timestamp >= ?"
        time_params.append(cutoff)
    elif "今天" in query_text:
        window_name = "今天"
        today_start = datetime.datetime(now.year, now.month, now.day, tzinfo=datetime.timezone.utc).isoformat()
        time_filter_sql = "AND timestamp >= ?"
        time_params.append(today_start)
    elif "昨天" in query_text:
        window_name = "昨天"
        today_start = datetime.datetime(now.year, now.month, now.day, tzinfo=datetime.timezone.utc)
        yesterday_start = (today_start - datetime.timedelta(days=1)).isoformat()
        time_filter_sql = "AND timestamp >= ? AND timestamp < ?"
        time_params.extend([yesterday_start, today_start.isoformat()])

    # Extract keywords
    cut_words = [w.strip() for w in jieba.cut(query_text) if len(w.strip()) >= 2]
    keywords = [w for w in cut_words if w not in STOP_WORDS]
    latin_tokens = re.findall(r"[A-Za-z0-9_\-]+", query_text)
    for lt in latin_tokens:
        if len(lt) >= 3 and lt not in keywords:
            keywords.append(lt)

    logger.info(f"Memory router query='{query_text}', window='{window_name}', keywords={keywords}")

    hits = []
    try:
        conn = sqlite3.connect(str(SCREENPIPE_DB), timeout=3.0)
        c = conn.cursor()

        if keywords:
            # P1-3: Fast FTS5 MATCH query with rowid JOIN
            try:
                fts_query = " OR ".join([f'"{k}"' if '-' in k else f"{k}*" for k in keywords])
                fts_sql = f"""
                    SELECT a.id, a.timestamp, a.transcription, a.device, a.is_input_device
                    FROM audio_transcriptions_fts f
                    JOIN audio_transcriptions a ON f.rowid = a.id
                    WHERE audio_transcriptions_fts MATCH ?
                      {time_filter_sql}
                    ORDER BY a.id DESC LIMIT 50
                """
                c.execute(fts_sql, [fts_query] + time_params)
                rows = c.fetchall()
                for row_id, ts, transcript, dev, is_in in rows:
                    hits.append({
                        "id": row_id,
                        "timestamp": ts,
                        "text": transcript,
                        "device": dev,
                        "is_input": bool(is_in)
                    })
                if hits:
                    logger.debug(f"FTS5 MATCH '{fts_query}' returned {len(hits)} hits")
            except Exception as fts_err:
                logger.debug(f"FTS5 query failed or skipped: {fts_err}")
                hits = []

            # P1-3 Fallback: Push down to SQL LIKE if FTS returned 0 (e.g. unsegmented Chinese)
            if not hits:
                like_clauses = " OR ".join(["transcription LIKE ?" for _ in keywords])
                sql = f"""
                    SELECT id, timestamp, transcription, device, is_input_device 
                    FROM audio_transcriptions 
                    WHERE transcription IS NOT NULL AND transcription != ''
                      AND ({like_clauses})
                      {time_filter_sql}
                    ORDER BY id DESC LIMIT 50
                """
                params = [f"%{k}%" for k in keywords] + time_params
                c.execute(sql, params)
                rows = c.fetchall()
                for row_id, ts, transcript, dev, is_in in rows:
                    hits.append({
                        "id": row_id,
                        "timestamp": ts,
                        "text": transcript,
                        "device": dev,
                        "is_input": bool(is_in)
                    })
        else:
            sql = f"""
                SELECT id, timestamp, transcription, device, is_input_device 
                FROM audio_transcriptions 
                WHERE transcription IS NOT NULL AND transcription != ''
                  AND is_input_device = 1
                  {time_filter_sql}
                ORDER BY id DESC LIMIT 20
            """
            c.execute(sql, time_params)
            rows = c.fetchall()
            for row_id, ts, transcript, dev, is_in in rows:
                hits.append({
                    "id": row_id,
                    "timestamp": ts,
                    "text": transcript,
                    "device": dev,
                    "is_input": bool(is_in)
                })
        conn.close()
    except Exception as e:
        logger.error(f"Error querying Screenpipe DB: {e}")

    # Build context prompt
    if hits:
        lines = []
        for h in hits[:5]:
            speaker = "用户" if h["is_input"] else "助手"
            lines.append(f"- [{h['timestamp']}] {speaker}: \"{h['text']}\"")
        records_str = "\n".join(lines)
        prompt = (
            f"【本地现实历史记录（事实来源 · 检索窗口：{window_name}）】：\n"
            f"在本地录音库中检索到以下用户真实历史发言：\n{records_str}\n"
            f"请严格依据上述事实记录回答用户的问题，保持准确、简洁。"
        )
        return {
            "found": True,
            "records": hits,
            "context_prompt": prompt
        }
    else:
        prompt = (
            f"【本地现实历史记录（事实来源 · 检索窗口：{window_name}）】：\n"
            f"系统已在本地录音数据库中进行检索，在窗口【{window_name}】内未检索到与用户提问相关的任何历史记录。\n"
            f"根据系统规则，严禁虚构用户现实历史！请直接明确回答用户：本地数据库中没有检索到相关记录。"
        )
        return {
            "found": False,
            "records": [],
            "context_prompt": prompt
        }

def archive_to_screenpipe(text: str, source: str = "live", is_input: bool = True, duration_s: Optional[float] = None) -> bool:
    """Archives a spoken sentence into Screenpipe's reality memory SQLite database.
    
    Dynamically computes chunk-relative start/end timestamps, inherits actual device names,
    and updates FTS5全文检索索引.
    """
    if not text or not text.strip():
        return False

    if not SCREENPIPE_DB.exists():
        logger.debug(f"Screenpipe DB not found at {SCREENPIPE_DB}, skipping archive.")
        return False

    try:
        conn = sqlite3.connect(str(SCREENPIPE_DB), timeout=3.0)
        c = conn.cursor()

        dev_filter = "%input%" if is_input else "%output%"
        c.execute("""
            SELECT id, timestamp, file_path FROM audio_chunks 
            WHERE file_path LIKE ? 
            ORDER BY id DESC LIMIT 1
        """, (dev_filter,))
        chunk_row = c.fetchone()
        if not chunk_row:
            c.execute("SELECT id, timestamp, file_path FROM audio_chunks ORDER BY id DESC LIMIT 1")
            chunk_row = c.fetchone()

        chunk_id = chunk_row[0] if chunk_row else 1
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        now_iso = now_dt.isoformat()

        if duration_s is not None and duration_s > 0:
            dur = duration_s
        else:
            dur = max(0.8, round(len(text) * 0.22, 2))

        offset = 0.0
        if chunk_row and chunk_row[1]:
            try:
                chunk_dt = datetime.datetime.fromisoformat(chunk_row[1])
                diff_sec = (now_dt - chunk_dt).total_seconds()
                offset = max(0.0, diff_sec % 30.0)
            except Exception:
                offset = 0.0

        start_time = round(offset, 2)
        end_time = round(offset + dur, 2)

        # P2-3: Parse actual device name from audio_chunk file path
        device_name = "lva-live-mic" if is_input else "lva-live-speaker"
        if chunk_row and len(chunk_row) > 2 and chunk_row[2]:
            fp = chunk_row[2]
            base_name = Path(fp).name
            match = re.search(r"^(.*?)\s*\((input|output)\)", base_name, re.IGNORECASE)
            if match:
                device_name = match.group(1).strip()
            elif "(" in base_name:
                device_name = base_name.split("_202")[0].strip()

        engine = "SenseVoice-int8" if is_input else "MeloTTS"

        c.execute("""
            INSERT OR IGNORE INTO audio_transcriptions (
                audio_chunk_id, offset_index, timestamp, transcription,
                device, is_input_device, transcription_engine, start_time, end_time, text_length
            ) VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chunk_id, now_iso, text, device_name,
            1 if is_input else 0, engine, start_time, end_time, len(text)
        ))
        row_id = c.lastrowid
        if not row_id:
            c.execute("SELECT id FROM audio_transcriptions WHERE audio_chunk_id = ? AND transcription = ? ORDER BY id DESC LIMIT 1", (chunk_id, text))
            r = c.fetchone()
            row_id = r[0] if r else None

        # Keep FTS5 in sync if virtual table exists (trigger handles or manual fallback)
        if row_id:
            try:
                c.execute("""
                    INSERT OR REPLACE INTO audio_transcriptions_fts (rowid, transcription, device, speaker_id)
                    VALUES (?, ?, ?, ?)
                """, (row_id, text, device_name, None))
            except Exception:
                pass

        conn.commit()
        conn.close()
        logger.debug(f"Archived to Screenpipe [id={row_id}, {start_time:.1f}s-{end_time:.1f}s, dev={device_name}]: {text[:30]}...")
        return True
    except Exception as e:
        logger.error(f"Failed to archive to Screenpipe: {e}")
        return False
