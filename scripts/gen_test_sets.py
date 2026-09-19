"""Build the ASR test sets.

Two sets are produced so results can be read honestly:

* `real`    - genuine human Mandarin from AISHELL-1 (downloaded separately),
              used for CER / RTF / resource numbers on natural speech.
* `sci`     - the scientific sentences.  No human recording of these exact
              sentences exists, so they are synthesised.  Each sentence is
              rendered by two independent synthesisers (MeloTTS and the Windows
              voice); if every engine mis-hears the same term on *both*
              renderings the cause is the term itself, and if they disagree the
              cause is the synthesiser's pronunciation.  The manifests record
              which renderer produced each clip.

Run:  python scripts/gen_test_sets.py [--real-limit N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lva import audio as A  # noqa: E402
from lva import config as C  # noqa: E402
from lva import tts as T  # noqa: E402

BENCH_AUDIO = C.BENCH / "audio"

# --------------------------------------------------------------- sci corpus
# (id, domain, reference text, terms that must survive recognition)
SCI: list[tuple[str, str, str, list[str]]] = [
    ("general_01", "general", "你好，我想测试一下本地语音识别系统。", []),
    ("general_02", "general", "今天下午我要整理一下实验数据。", []),
    ("general_03", "general", "你好，我现在正在测试本地语音助手。", []),
    ("chem_01", "chemistry", "铜离子可以与EDTA发生络合。", ["络合", "EDTA"]),
    ("chem_02", "chemistry", "这里需要考虑配体的配位数。", ["配体", "配位数"]),
    ("chem_03", "chemistry", "这个反应属于Favorskii重排。", ["Favorskii", "重排"]),
    ("chem_04", "chemistry", "Baeyer-Villiger氧化通常涉及迁移能力差异。", ["Baeyer-Villiger", "氧化"]),
    ("chem_05", "chemistry", "Michaelis-Menten动力学可以使用稳态近似处理。", ["Michaelis-Menten", "动力学"]),
    ("chem_06", "chemistry", "铜离子与EDTA形成稳定的络合物。", ["络合", "EDTA"]),
    ("chem_07", "chemistry", "这里需要考虑Jahn-Teller效应。", ["Jahn-Teller", "效应"]),
    ("chem_08", "chemistry", "配位数是六的时候晶场分裂能更大。", ["配位数", "晶场分裂"]),
    ("chem_09", "chemistry", "这个反应的Hammett常数是正值。", ["Hammett"]),
    ("chem_10", "chemistry", "Cannizzaro反应需要浓碱条件。", ["Cannizzaro"]),
    ("chem_11", "chemistry", "螯合物的稳定性通常高于单齿配体。", ["螯合", "配体"]),
    ("phys_01", "physics", "这里可以使用Levi-Civita联络。", ["Levi-Civita", "联络"]),
    ("phys_02", "physics", "这是Minkowski时空中的proper time。", ["Minkowski", "proper time"]),
    ("phys_03", "physics", "哈密顿量必须是厄米算符。", ["哈密顿量", "厄米"]),
    ("phys_04", "physics", "布里渊区边界处的能带结构需要仔细计算。", ["布里渊区", "能带"]),
    ("phys_05", "physics", "狄拉克方程描述了自旋二分之一的粒子。", ["狄拉克"]),
    ("phys_06", "physics", "拉格朗日量对时间的积分给出作用量。", ["拉格朗日量"]),
    ("bio_01", "biology", "GPCR激活后通过G蛋白调控下游信号。", ["GPCR", "G蛋白"]),
    ("bio_02", "biology", "这里涉及JAK-STAT信号通路。", ["JAK-STAT", "通路"]),
    ("bio_03", "biology", "MAPK和PI3K通路都会影响细胞增殖。", ["MAPK", "PI3K"]),
    ("bio_04", "biology", "泛素化与磷酸化是两种常见的翻译后修饰。", ["泛素化", "磷酸化"]),
    ("bio_05", "biology", "糖异生主要发生在肝脏。", ["糖异生"]),
    ("mixed_01", "chemistry", "Favorskii rearrangement是一种重要的有机重排反应。",
     ["Favorskii", "rearrangement"]),
]


def load_transcripts(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            out[parts[0]] = "".join(parts[1:])
    return out


def build_real(limit: int) -> dict:
    wav_root = C.BENCH / "_work" / "aishell"
    transcript = wav_root / "transcript.txt"
    if not transcript.exists():
        raise SystemExit(f"missing {transcript}; download the AISHELL-1 transcript first")
    refs = load_transcripts(transcript)

    # Extract the speaker archives that are present in the work dir.
    for tgz in sorted(wav_root.glob("S*.tar.gz")):
        marker = wav_root / (".extracted_" + tgz.stem)
        if not marker.exists():
            with tarfile.open(tgz) as t:
                t.extractall(wav_root)
            marker.write_text("ok", encoding="utf-8")

    wavs = sorted(wav_root.rglob("*.wav"))
    items = []
    for w in wavs:
        utt = w.stem
        if utt not in refs:
            continue
        items.append({"id": utt, "wav": str(w), "ref": refs[utt], "domain": "real",
                      "variant": "human", "terms": []})
    # Even sample across the speaker so we do not measure one voice only.
    step = max(1, len(items) // limit)
    items = items[::step][:limit]
    if not items:
        raise SystemExit("no real utterances matched the transcript")
    return {"name": "real", "source": "AISHELL-1", "items": items}


def build_sci() -> dict:
    out_dir = BENCH_AUDIO / "sci"
    out_dir.mkdir(parents=True, exist_ok=True)
    engines: list[tuple[str, object]] = []
    melo = T.load("melotts")
    engines.append(("melotts", melo))
    try:
        sapi = T.load("sapi")
        sapi.synthesize("测试")          # probe: fail early if the voice is absent
        engines.append(("sapi", sapi))
    except Exception as e:  # noqa: BLE001
        print(f"[warn] Windows SAPI unavailable, sci set gets MeloTTS only: {e}")

    items = []
    for sid, domain, ref, terms in SCI:
        for eng_name, eng in engines:
            path = out_dir / f"{sid}_{eng_name}.wav"
            if not path.exists():
                syn = eng.synthesize(ref)
                A.write_wav(path, syn.samples, syn.sample_rate)
            items.append({"id": f"{sid}_{eng_name}", "wav": str(path), "ref": ref,
                          "domain": domain, "variant": eng_name, "terms": terms,
                          "base_id": sid})
    return {"name": "sci", "source": "synthesised", "items": items}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-limit", type=int, default=60)
    args = ap.parse_args()

    C.BENCH.mkdir(parents=True, exist_ok=True)
    manifolds = {}

    real = build_real(args.real_limit)
    (C.BENCH / "manifest_real.json").write_text(
        json.dumps(real, ensure_ascii=False, indent=1), encoding="utf-8")
    manifolds["real"] = real
    print(f"real: {len(real['items'])} utterances")

    sci = build_sci()
    (C.BENCH / "manifest_sci.json").write_text(
        json.dumps(sci, ensure_ascii=False, indent=1), encoding="utf-8")
    manifolds["sci"] = sci
    print(f"sci:  {len(sci['items'])} clips "
          f"({len({i['base_id'] for i in sci['items']})} sentences x renderers)")


if __name__ == "__main__":
    main()
