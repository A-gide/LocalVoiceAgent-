"""Text normalisation used by benchmarks and by memory search.

Kept deliberately small and dependency-free so benchmark numbers stay
reproducible.
"""
from __future__ import annotations

import re
import unicodedata

_PUNCT = "，。！？、；：（）《》“”‘’【】—…·,.!?;:()<>\"'`~ \t\n\r"

_DIGITS = {ord(c): d for c, d in zip("0123456789", "零一二三四五六七八九")}

# Common ASR output conventions that are not part of the words themselves.
_TAG_RE = re.compile(r"<\|[^|]*\|>")
_SPACE_RE = re.compile(r"\s+")


def strip_tags(text: str) -> str:
    """Remove SenseVoice-style event/emotion tags such as <|zh|> or <|NEUTRAL|>."""
    return _TAG_RE.sub("", text)


def normalize(text: str) -> str:
    """Lowercase, drop punctuation/whitespace, full-width -> half-width."""
    t = unicodedata.normalize("NFKC", strip_tags(text or ""))
    t = t.lower()
    t = "".join(ch for ch in t if ch not in _PUNCT)
    t = _SPACE_RE.sub("", t)
    return t


def digits_to_chinese(text: str) -> str:
    return (text or "").translate(_DIGITS)


def cer(reference: str, hypothesis: str) -> float:
    """Character error rate on normalised text (Levenshtein / len(ref))."""
    ref = digits_to_chinese(normalize(reference))
    hyp = digits_to_chinese(normalize(hypothesis))
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, start=1):
        cur = [i]
        for j, hc in enumerate(hyp, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(ref)


def contains_terms(text: str, terms: list[str]) -> tuple[int, int]:
    """How many of `terms` appear verbatim (case-insensitive) in `text`."""
    low = (text or "").lower()
    hit = sum(1 for t in terms if t and t.lower() in low)
    return hit, len(terms)


# --------------------------------------------------------------- for speech
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_MARKS = re.compile(r"[`*_#>~|]+")
_LATEX_BLOCK = re.compile(r"\$\$.*?\$\$|\\\[.*?\\\]", re.S)
_LATEX_INLINE = re.compile(r"\$[^$\n]{1,120}\$")
_LATEX_CMD = re.compile(r"\\[a-zA-Z]+\s*")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.、)])\s*", re.M)
_ARROWS = {"\u21cc": "可逆生成为", "\u2192": "生成", "\u21d2": "得到", "\u2264": "小于等于",
           "\u2265": "大于等于", "\u00d7": "乘", "\u2248": "约等于"}
# MeloTTS's lexicon has no entry for these, and reports them as OOV - i.e. the
# pause is silently dropped and the clauses run together.  Map them to a mark
# the lexicon does know.
_PAUSE_MAP = {"：": "，", "；": "，", ":": "，", ";": "，", "\u2014": "，", "\u3001": "，"}


def strip_for_speech(text: str) -> str:
    """Turn a model reply into something a synthesiser should actually read.

    Local models answer with Markdown headings, bold markers and LaTeX even when
    asked not to, and reading `###` or `\\frac{}{}` aloud is unacceptable.  The
    maths is replaced by a short spoken stand-in rather than deleted, so the
    sentence still makes sense.
    """
    t = text or ""
    t = _LATEX_BLOCK.sub(" 公式 ", t)
    t = _LATEX_INLINE.sub(" 公式 ", t)
    t = _LATEX_CMD.sub("", t)
    t = _MD_LINK.sub(r"\1", t)
    t = _MD_MARKS.sub("", t)
    t = _BULLET.sub("", t)
    for k, v in _ARROWS.items():
        t = t.replace(k, v)
    for k, v in _PAUSE_MAP.items():
        t = t.replace(k, v)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "。", t)
    t = t.replace("\n", "，")
    t = re.sub(r"[，。]{2,}", "。", t)
    return t.strip(" ，。;；")
