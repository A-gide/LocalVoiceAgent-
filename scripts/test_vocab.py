"""Terminology-corrector regression test.

Each case is a *real* ASR output observed in benchmarks/asr-*.json, so this test
fails if the corrector stops fixing the errors that actually occur on this
machine.  The last group guards the opposite direction: ordinary speech must
come out untouched.

Run:  python scripts/test_vocab.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lva import vocab  # noqa: E402

# (raw ASR output, session domain or None, substrings that MUST appear after)
CASES: list[tuple[str, str | None, list[str]]] = [
    ("铜离子可以与一地T发生落合。", "chemistry", ["络合"]),
    ("铜离子可以与EDDA发生络合。", "chemistry", ["络合"]),
    ("红离子与EDDA形成稳定的络合物。", "chemistry", ["络合"]),
    ("配位数是6的时候经场分裂能更大。", "chemistry", ["晶场分裂"]),
    ("这里需要考虑配题的配位数。", "chemistry", ["配体"]),
    ("薄合物的稳定性通常高于单指配体。", "chemistry", ["螯合物", "配体"]),
    ("这是MINTWSKI时空中的proper time。", None, ["Minkowski"]),
    ("阿密顿粮必须收恶弥散服。", "physics", ["哈密顿量", "厄米算符"]),
    ("物理院区边界处的能带结构需要仔细计算。", None, ["布里渊区"]),
    ("把和朗日量对时间的积分给出作用料。", None, ["拉格朗日量"]),
    ("好医生主要发生在肝脏。", "biology", ["糖异生"]),
    ("反俗化与磷酸化是两种常见的翻译后修饰。", "biology", ["泛素化", "磷酸化"]),
    ("伊拉克方程描述了自学2分之1的例子。", "physics", ["狄拉克方程"]),
    # Latin terms: whole-word letter-similarity matching (see latin_cost).  These
    # need the domain, because that is what makes a Latin rewrite safe.
    ("这里可以使用的USCIVIT有联络。", "physics", ["Levi-Civita"]),
    ("这个反应属于FDOSKI正盘。", "chemistry", ["Favorskii"]),
    ("这是MINTWSKI时空中的proper time。", "physics", ["Minkowski"]),
    ("铜离子和EDDA形成的络合物很稳定。", "chemistry", ["EDTA"]),
]

# Ordinary speech: no domain, no vocabulary hits -> must be left alone.
# The last four are regression cases for false corrections that were actually
# observed: 属于 was rewritten as 速率, `proper` was expanded to `proper time`,
# 熵 replaced 商 (single-character terms), and `windows` was turned into
# `Minkowski` by an over-eager Latin anchor rule.
UNCHANGED = [
    "而对楼市成交抑制作用最大的限购。",
    "通过财政补贴手段鼓励购房的地区也在不断增加。",
    "强化地方调控主体责任。",
    "今天下午我要整理一下实验数据。",
    "你好，我想测试一下本地语音识别系统。",
    "这个反应属于有机化学的范畴。",
    "这是proper time的另一种写法。",
    "我今天打开了windows系统更新。",
    "普通熵品住房和商用的区别需要说明。",
    "这个反应的ham常数是正值。",          # a truncated term is not a licence to guess
    "HOMO和LUMO的能级差需要计算。",
]

# Explicitly rejected over-correction: too distorted to repair honestly.  These
# are listed so the limitation is visible rather than silently hidden.
ALLOWED_MISSES = [
    ("这个反应属于FNRSPI中盘。", "Favorskii/重排"),   # only 2 contiguous letters survive
    ("马玉府沪敖排废区Mm宁告凯团链坚欧元。", "Hammett"),  # fragmentary
]


def main() -> int:
    t = vocab.default()
    print(f"vocabulary: {len(t.terms)} terms, {len(t.rules)} explicit rules\n")

    failures = 0
    for raw, dom, wants in CASES:
        res = t.correct(raw, domain=dom)
        missing = [w for w in wants if w.lower() not in res.corrected.lower()]
        status = "FAIL" if missing else "ok  "
        if missing:
            failures += 1
        print(f"[{status}] domain={res.domain:9s} {raw}")
        print(f"       -> {res.corrected}")
        if res.applied:
            print(f"       applied={[a['from'] + '=>' + a['to'] for a in res.applied]}")
        if missing:
            print(f"       MISSING: {missing}")

    print("\n--- must stay unchanged ---")
    for raw in UNCHANGED:
        res = t.correct(raw)
        ok = res.corrected == raw
        if not ok:
            failures += 1
        print(f"[{'ok  ' if ok else 'FAIL'}] {raw}")
        if not ok:
            print(f"       -> {res.corrected}  {res.applied}")

    print("\n--- known unrecoverable (documented, not a failure) ---")
    for raw, term in ALLOWED_MISSES:
        res = t.correct(raw, domain="chemistry")
        print(f"       {raw}  -> {res.corrected}   (term {term} not recovered)")

    print(f"\n{'PASS' if failures == 0 else f'{failures} FAILURES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
