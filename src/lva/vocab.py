"""Scientific-terminology correction.

Why this exists
---------------
No ASR engine in this project gets Latin abbreviations and rare Chinese terms
right on its own; the benchmark shows `EDTA -> 一地T`, `厄米算符 -> 恶弥散服`,
`晶场分裂 -> 经场分裂`.  Swapping to a bigger model fixes some of that but costs
latency, so errors are repaired after recognition using this project's own
vocabulary instead.

How it works
------------
Both the vocabulary entry and the transcript are reduced to a sequence of
*units*, built only from letters and CJK characters (punctuation is dropped but
its original offsets are remembered so a replacement can be written back into the
real string).  A term's units are: one per Chinese character (carrying its
pinyin), one per letter of a short ALL-CAPS acronym, or one per Latin word.  A
single Latin letter and a Chinese character whose pinyin is that letter's Chinese
name are both read as the same letter - that is what lets `一地T` be recognised as
`EDTA`.

Matching is a fuzzy edit distance over those unit sequences, with a graded
substitution cost:

* two Chinese syllables cost 0.0 if equal, 0.5 if their initials or finals come
  from a known confusion set, 1.0 otherwise.  The confusion sets are the ones a
  Chinese ASR hotword tool ships (`an/ang`, `z/zh`, `l/n`, `f/h`, `o/uo`, ...),
  which is what makes `luohe` reachable from `lehe`-style errors;
* two Latin tokens cost `1 - LCS(a, b) / max(len)`, which is what makes
  `Favorskii` reachable from `FDOSKI` and `Levi-Civita` from `USCIVIT` - the
  letter-level comparison the pinyin path cannot provide;
* because insertions and deletions cost 1.0 each, a stray filler word or a
  dropped syllable no longer breaks the match the way a fixed-length window did.

Safety rules, in the order they are enforced:
  * the raw transcript is never modified; corrections live in a separate field
  * a domain-specific term fires only when that domain has independent evidence
    (an explicit session domain, or other fuzzy matches in the same utterance)
  * a term must be mostly matched exactly, not merely similar - this is what
    stops a 4-character term from being "found" inside unrelated text
  * Chinese-only terms must be at least two characters: 熵(shang) would otherwise
    rewrite 上/商/伤 and 焓(han) would rewrite 涵/含
  * corrections are applied right-to-left so offsets stay valid
  * heavily distorted text is deliberately left alone
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache

from . import config

# Chinese names of the Latin letters, toneless, as pypinyin renders them.
LETTER_NAME: dict[str, str] = {
    "a": "ei", "b": "bi", "c": "xi", "d": "di", "e": "yi", "f": "aifu",
    "g": "ji", "h": "aichi", "i": "ai", "j": "jie", "k": "kei", "l": "aile",
    "m": "aimu", "n": "en", "o": "ou", "p": "pi", "q": "qiu", "r": "ar",
    "s": "aisi", "t": "ti", "u": "you", "v": "wei", "w": "dabuliu",
    "x": "ekesi", "y": "wai", "z": "zei",
}
NAME_TO_LETTER: dict[str, set[str]] = {}
for _l, _n in LETTER_NAME.items():
    NAME_TO_LETTER.setdefault(_n, set()).add(_l)

_WORD = re.compile(r"[A-Za-z]+")

# Pinyin initials, longest first so 双字母声母 are matched before single ones.
_INITIALS = ("zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l",
             "g", "k", "h", "j", "q", "x", "r", "z", "c", "s", "y", "w")

# Confusable phonemes, each costing 0.5 instead of 1.0.  Taken from the table a
# Chinese ASR hotword corrector ships (HaujetZhao/asr-hotword, hotword/
# algo_calc.py); these are the confusions Chinese ASR actually makes.
SIMILAR_PHONEMES: tuple[frozenset[str], ...] = (
    frozenset({"an", "ang"}), frozenset({"en", "eng"}), frozenset({"in", "ing"}),
    frozenset({"ian", "iang"}), frozenset({"uan", "uang"}),
    frozenset({"z", "zh"}), frozenset({"c", "ch"}), frozenset({"s", "sh"}),
    frozenset({"l", "n"}), frozenset({"f", "h"}),
    frozenset({"ai", "ei"}), frozenset({"o", "uo"}), frozenset({"e", "ie"}),
    frozenset({"p", "t"}), frozenset({"p", "b"}), frozenset({"t", "d"}),
    frozenset({"k", "g"}),
)

MIN_SCORE = 0.72          # similarity a fuzzy Chinese match must reach
MIN_EXACT_RATIO = 0.5     # ... and this share of its units must match exactly
MIN_LATIN_SCORE = 0.5     # Latin whole-word similarity floor
LATIN_ANCHOR = 3          # letters that must be contiguous for a Latin match
LATIN_ANCHOR_RATIO = 0.45 # ... and that anchor must cover this share of the shorter token
LATIN_LEN_TOLERANCE = 0.35  # a collapsed token must be about as long as the term
MIN_UNITS_FOR_FUZZY = 2   # Chinese-only terms need two characters (see docstring)
MIN_DOMAIN_EVIDENCE = 2.0
MIN_RULE_EVIDENCE = 1.0
MAX_EDIT_RATIO = 0.45     # never accept a match that is mostly insert/delete


def _lcs_length(a: str, b: str) -> int:
    """Longest common subsequence length (letters in order, gaps allowed)."""
    if not a or not b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            cur[j] = prev[j - 1] + 1 if a[i - 1] == b[j - 1] else max(prev[j], cur[j - 1])
        prev = cur
    return prev[-1]


def _lcs_substring(a: str, b: str) -> int:
    """Longest common *contiguous* substring length.

    This is the guard that keeps Latin matching honest.  A mangled acronym like
    `FDOSKI` shares the run `ski` with `Favorskii`, whereas an unrelated English
    word like `windows` shares only `ow` with `Minkowski` - so requiring a real
    contiguous anchor rejects the second without losing the first.
    """
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def latin_cost(a: str, b: str) -> float:
    """Letter-level similarity cost, so FDOSKI can reach Favorskii.

    0.0 means identical, 1.0 means "not the same word at all".  Short tokens get
    a stricter rule because one wrong letter in four is already a different word,
    and because a three-letter English word must not be read as an acronym:
    the first letter has to agree, which is what separates the real case
    (`EDT` for `EDTA`, first letter kept) from the false one (`the` for `EDTA`).
    """
    if a == b:
        return 0.0
    la, lb = len(a), len(b)
    if min(la, lb) <= 4:
        common = _lcs_length(a, b)
        if a[0] != b[0] or abs(la - lb) > 1:
            return 1.0
        # A three-letter fragment has to *be* a subsequence of the term: one
        # substitution in three letters is already a different word, and this is
        # what stops `ham` (a truncated `Hammett`) from being read as `HOMO`.
        # Four letters may lose one, which is how `EDDA` reaches `EDTA`.
        need = min(la, lb) if min(la, lb) <= 3 else min(la, lb) - 1
        return 0.25 if common >= need else 1.0
    anchor = _lcs_substring(a, b)
    # The anchor must also be substantial relative to the shorter token.  A flat
    # three-letter rule was not enough: `windows` and `Minkowski` share `ows`, so
    # an unrelated English word could have been rewritten into a technical term.
    if anchor < LATIN_ANCHOR or anchor < LATIN_ANCHOR_RATIO * min(la, lb):
        return 1.0
    return 1.0 - (_lcs_length(a, b) / max(la, lb))


def _syllables(text: str) -> list[str]:
    """Toneless pinyin, one entry per character (non-Chinese pass through)."""
    from pypinyin import Style, lazy_pinyin

    return list(lazy_pinyin(text, style=Style.NORMAL, errors=lambda x: list(x)))


def _split_syllable(syl: str) -> tuple[str, str]:
    """Split a toneless syllable into (initial, final); ('', syl) if no initial."""
    for ini in _INITIALS:
        if syl.startswith(ini) and len(syl) > len(ini):
            return ini, syl[len(ini):]
    return "", syl


def _similar(a: str, b: str) -> bool:
    pair = {a, b}
    return any(pair <= s for s in SIMILAR_PHONEMES)


def syllable_cost(a: str, b: str) -> float:
    """0.0 identical, 0.5 for a known confusion, 1.0 unrelated."""
    if a == b:
        return 0.0
    ai, af = _split_syllable(a)
    bi, bf = _split_syllable(b)
    init_ok = ai == bi or _similar(ai, bi)
    final_ok = af == bf or _similar(af, bf)
    if init_ok and final_ok:
        return 0.5
    # The 颚化 pair 乐/络 (le/luo) is a real ASR confusion that no initial/final
    # set captures: the final differs by a glide only.
    if ai == bi and {af, bf} <= {"e", "uo"}:
        return 0.5
    return 1.0


@dataclass
class Unit:
    kind: str          # 'zh' | 'letter' | 'latin'
    value: str         # syllable, single lower-case letter, or lower-case word


@dataclass
class Term:
    canonical: str
    domain: str
    units: tuple[Unit, ...]

    @property
    def n(self) -> int:
        return len(self.units)

    @property
    def pure_chinese(self) -> bool:
        return all(u.kind == "zh" for u in self.units)

    @property
    def flat_latin(self) -> str | None:
        """Concatenated Latin units, or None when the term is pure Chinese."""
        if self.pure_chinese:
            return None
        return "".join(u.value for u in self.units if u.kind != "zh")


@dataclass
class Match:
    term: Term
    start: int
    end: int
    score: float
    span: str = ""

    def as_dict(self) -> dict:
        return {"from": self.span, "to": self.term.canonical, "domain": self.term.domain,
                "confidence": round(self.score, 3)}


@dataclass
class CorrectedText:
    raw: str
    corrected: str
    applied: list[dict] = field(default_factory=list)
    domain: str = "general"
    domain_scores: dict[str, float] = field(default_factory=dict)
    flagged: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def _term_units(term: str) -> tuple[Unit, ...]:
    """`Michaelis-Menten动力学` -> [latin(michaelis), latin(menten), zh(dong), ...]."""
    units: list[Unit] = []
    segments: list[tuple[str, str]] = []
    pos = 0
    for m in _WORD.finditer(term):
        if m.start() > pos:
            segments.append(("zh", term[pos:m.start()]))
        segments.append(("latin", m.group(0)))
        pos = m.end()
    if pos < len(term):
        segments.append(("zh", term[pos:]))

    for kind, text in segments:
        if kind == "latin":
            if len(text) <= 4 and text.isupper():
                units.extend(Unit("letter", ch.lower()) for ch in text)
            else:
                units.append(Unit("latin", text.lower()))
        else:
            kept = "".join(ch for ch in text if ch.isalnum())
            if not kept:
                continue
            units.extend(Unit("zh", syl) for syl in _syllables(kept))
    return tuple(units)


class Terminology:
    def __init__(self, vocab_dir=None,
                 domain_files=("chemistry", "physics", "biology", "names")):
        self.dir = vocab_dir or config.VOCAB
        self.terms: list[Term] = []
        self.rules: list[dict] = []
        self._by_domain: dict[str, list[Term]] = {}
        self._load(domain_files)
        self._load_rules()

    # ---------------------------------------------------------------- loading
    def _load(self, files) -> None:
        for name in files:
            p = self.dir / f"{name}.txt"
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                units = _term_units(line)
                if not units:
                    continue
                term = Term(canonical=line, domain=name, units=units)
                self.terms.append(term)
                self._by_domain.setdefault(name, []).append(term)

    def _load_rules(self) -> None:
        p = self.dir / "corrections.json"
        if not p.exists():
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        for r in data.get("rules", []):
            src, dst = r.get("from"), r.get("to")
            if not src or not dst or src == dst:
                continue
            self.rules.append({"from": src, "to": dst,
                               "domain": r.get("domain") or "general",
                               "confidence": float(r.get("confidence", 0.5))})

    # ------------------------------------------------------------- atomising
    def _atoms(self, text: str) -> list[tuple[Unit, int, int]]:
        atoms: list[tuple[Unit, int, int]] = []
        for m in _WORD.finditer(text):
            word = m.group(0)
            unit = Unit("letter", word.lower()) if len(word) == 1 else Unit("latin", word.lower())
            atoms.append((unit, m.start(), m.end()))
        cjk = [(i, ch) for i, ch in enumerate(text) if ch.isalnum() and not ch.isascii()]
        for (i, _ch), syl in zip(cjk, _syllables("".join(c for _, c in cjk))):
            atoms.append((Unit("zh", syl), i, i + 1))
        atoms.sort(key=lambda a: a[1])
        return atoms

    # --------------------------------------------------------------- matching
    @staticmethod
    def _unit_cost(tu: Unit, au: Unit) -> float:
        if tu.kind == "zh" and au.kind == "zh":
            return syllable_cost(tu.value, au.value)
        if tu.kind == "letter":
            if au.kind == "letter":
                return 0.0 if tu.value == au.value else 1.0
            if au.kind == "zh":
                # A Chinese character whose pinyin is this letter's name ("提" = D).
                return 0.0 if tu.value in NAME_TO_LETTER.get(au.value, ()) else 1.0
            return 1.0
        if tu.kind == "latin":
            if au.kind == "latin":
                return latin_cost(tu.value, au.value)
            return 1.0
        return 1.0

    def _best_match(self, term: Term, atoms: list[tuple[Unit, int, int]]) -> Match | None:
        """Fuzzy substring match of `term` inside the atom sequence.

        Dynamic programming over (term unit, atom) with unit substitution cost
        from `_unit_cost` and 1.0 for insertions/deletions, so a filler word or a
        dropped syllable no longer defeats the match the way a fixed-length
        window did.  Written with full tables on purpose: terms are at most a few
        units and utterances a few dozen atoms, so clarity beats cleverness here.
        """
        n, m = term.n, len(atoms)
        if n == 0 or m == 0 or n > m + max(2, n // 2):
            return None

        inf = float("inf")
        # dist[i][j]  = cost of matching the first i units against the first j atoms
        # start[i][j] = atom index the match began at
        # exact[i][j] = units that matched with cost 0
        # close[i][j] = units that matched with cost <= 0.5 (identical or confusable)
        dist = [[inf] * (m + 1) for _ in range(n + 1)]
        start = [[0] * (m + 1) for _ in range(n + 1)]
        exact = [[0] * (m + 1) for _ in range(n + 1)]
        close = [[0] * (m + 1) for _ in range(n + 1)]
        for j in range(m + 1):                    # a match may begin at any atom
            dist[0][j] = 0.0
            start[0][j] = j
        for i in range(1, n + 1):
            dist[i][0] = float(i)
            start[i][0] = 0

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                cost = self._unit_cost(term.units[i - 1], atoms[j - 1][0])
                options = (
                    (dist[i - 1][j - 1] + cost, start[i - 1][j - 1],
                     exact[i - 1][j - 1] + (1 if cost == 0.0 else 0),
                     close[i - 1][j - 1] + (1 if cost <= 0.5 else 0)),   # substitute
                    (dist[i - 1][j] + 1.0, start[i - 1][j],
                     exact[i - 1][j], close[i - 1][j]),                  # drop a unit
                    (dist[i][j - 1] + 1.0, start[i][j - 1],
                     exact[i][j - 1], close[i][j - 1]),                  # skip an atom
                )
                d, s, e, c2 = min(options, key=lambda t: t[0])
                dist[i][j], start[i][j], exact[i][j], close[i][j] = d, s, e, c2

        # A Chinese term must be mostly *exactly* right - that rule is what stops
        # 属于 from being read as 反应速率.  A Latin term cannot be judged that way
        # (every replacement is a substitution, never an exact hit), so there the
        # bar is that every unit is at least confusable.
        has_cjk = any(u.kind == "zh" for u in term.units)
        if has_cjk:
            need_exact = max(1, math.ceil(n * MIN_EXACT_RATIO))
            need_close = 0
        else:
            need_exact = 0
            need_close = max(1, math.ceil(n * 0.6))

        best: Match | None = None
        for j in range(1, m + 1):
            d = dist[n][j]
            if d == inf:
                continue
            score = 1.0 - (d / n)
            if score < MIN_SCORE or exact[n][j] < need_exact or close[n][j] < need_close:
                continue
            if d > n * (1.0 + MAX_EDIT_RATIO):
                continue
            s_idx = start[n][j]
            if s_idx >= j:
                continue
            span_start = atoms[s_idx][1]
            span_end = atoms[j - 1][2]
            if best is None or score > best.score:
                best = Match(term, span_start, span_end, score, "")
        return best

    def _match_flat_latin(self, term: Term, atoms: list[tuple[Unit, int, int]]) -> Match | None:
        """Match a Latin-only term as a whole word.

        ASR happily emits `USCIVIT` where `Levi-Civita` was said, collapsing the
        hyphenated pair into one token.  Unit-by-unit matching cannot see that,
        so the term's concatenated letters are compared against each Latin token
        directly, with a contiguous anchor required to keep ordinary English
        words from being rewritten into technical terms.
        """
        flat = term.flat_latin
        if not flat or len(flat) < 4:
            return None
        best: Match | None = None
        for u, s, e in atoms:
            # Three letters is enough: ASR drops one from a four-letter acronym
            # often enough that requiring four would miss `EDT` for `EDTA`.
            if u.kind != "latin" or len(u.value) < 3:
                continue
            # A collapsed token must be about as long as the term it stands for.
            # Without this `proper` matches the term `proper time` and the word
            # gets duplicated in the output.
            if abs(len(flat) - len(u.value)) > max(1, LATIN_LEN_TOLERANCE * len(flat)):
                continue
            cost = latin_cost(flat, u.value)
            score = 1.0 - cost
            if score < MIN_LATIN_SCORE:
                continue
            if best is None or score > best.score:
                best = Match(term, s, e, score, "")
        return best

    def find_matches(self, text: str, include_exact: bool = False) -> list[Match]:
        """Vocabulary hits in `text`, best first, non-overlapping.

        With `include_exact=True` a term that is *already* spelled correctly is
        reported too.  Such a hit must not rewrite anything, but it is valuable
        evidence that the sentence belongs to that domain - `proper time` being
        present correctly is what tells us Minkowski is a safe correction here.
        """
        atoms = self._atoms(text)
        if not atoms:
            return []
        known = {t.canonical.lower() for t in self.terms}
        found: list[Match] = []
        for term in self.terms:
            if term.n < MIN_UNITS_FOR_FUZZY and term.pure_chinese:
                continue
            candidates = [self._best_match(term, atoms)]
            if not term.pure_chinese:
                candidates.append(self._match_flat_latin(term, atoms))
            m = max((c for c in candidates if c is not None),
                    key=lambda c: c.score, default=None)
            if m is None:
                continue
            m.span = text[m.start:m.end]
            if m.span.lower() == term.canonical.lower():
                if include_exact:
                    found.append(m)
                continue
            # Never rewrite text that is already a vocabulary term.  One wrong
            # unit out of four is tolerated on purpose (that is what lets 阿密顿粮
            # become 哈密顿量), but that tolerance must not turn the correct term
            # 单齿配体 into the different term 多齿配体.
            if m.span.lower() in known:
                continue
            # The span must contain real characters: never rewrite whitespace-only.
            if not m.span.strip():
                continue
            found.append(m)
        found.sort(key=lambda x: (-x.score, -(x.end - x.start)))
        chosen: list[Match] = []
        for m in found:
            if any(not (m.end <= c.start or m.start >= c.end) for c in chosen):
                continue
            chosen.append(m)
        return chosen

    # ----------------------------------------------------------------- domain
    def detect_domain(self, text: str) -> tuple[str, dict[str, float]]:
        hits: dict[str, float] = {}
        for m in self.find_matches(text, include_exact=True):
            if m.term.domain == "names":
                continue
            hits[m.term.domain] = hits.get(m.term.domain, 0.0) + m.score * m.term.n
        for r in self.rules:
            if r["from"] in text and r["domain"] != "general":
                hits[r["domain"]] = hits.get(r["domain"], 0.0) + 1.0
        if not hits:
            return "general", {}
        best = max(hits.items(), key=lambda kv: kv[1])
        if best[1] < MIN_DOMAIN_EVIDENCE:
            return "general", hits
        return best[0], hits

    # ------------------------------------------------------------------- main
    def correct(self, text: str, domain: str | None = None) -> CorrectedText:
        if not text:
            return CorrectedText(raw=text, corrected=text)
        inferred, scores = self.detect_domain(text)
        dom = domain or inferred
        out = text
        applied: list[dict] = []

        def rule_allowed(r: dict) -> bool:
            if r["domain"] == "general":
                return True
            if domain == r["domain"]:
                return True
            return scores.get(r["domain"], 0.0) >= MIN_RULE_EVIDENCE

        for r in sorted(self.rules, key=lambda r: -r["confidence"]):
            if r["confidence"] < 0.6 or r["from"] not in out:
                continue
            if not rule_allowed(r):
                continue
            out = out.replace(r["from"], r["to"])
            applied.append({"from": r["from"], "to": r["to"], "domain": r["domain"],
                            "confidence": r["confidence"], "source": "rule"})

        # Fuzzy matches are applied right-to-left so earlier offsets stay valid
        # while the string is rewritten underneath them.
        for m in sorted(self.find_matches(out), key=lambda m: -m.start):
            if m.term.domain == "names":
                continue
            if m.term.domain != "general" and m.term.domain not in (dom, inferred):
                continue
            if out[m.start:m.end] == m.term.canonical:
                continue
            out = out[: m.start] + m.term.canonical + out[m.end:]
            d = m.as_dict()
            d["source"] = "fuzzy"
            applied.append(d)

        return CorrectedText(raw=text, corrected=out, applied=applied, domain=dom,
                             domain_scores=scores, flagged=self._flag_unknown_latin(out))

    # ---------------------------------------------------------------- helpers
    def _flag_unknown_latin(self, text: str) -> list[str]:
        known = {t.canonical.lower() for t in self.terms}
        known |= {u.value for t in self.terms for u in t.units if u.kind != "zh"}
        common = {"the", "and", "for", "with", "that", "this", "is", "of", "a", "in",
                  "to", "it", "you", "i", "we", "on", "at", "as", "be", "are", "time",
                  "proper", "not", "but", "so", "ok", "okay"}
        out = []
        for tok in _WORD.findall(text):
            low = tok.lower()
            if low in known or low in common or len(low) < 3:
                continue
            out.append(tok)
        return out

    def hotwords(self, domain: str, limit: int = 200) -> list[str]:
        terms = list(self._by_domain.get(domain, []))
        if domain != "general":
            terms += self._by_domain.get("general", [])
        return [t.canonical for t in terms[:limit]]

    def known_terms(self) -> list[str]:
        return [t.canonical for t in self.terms]


@lru_cache(maxsize=1)
def default() -> Terminology:
    return Terminology()


def correct(text: str, domain: str | None = None) -> CorrectedText:
    return default().correct(text, domain=domain)
