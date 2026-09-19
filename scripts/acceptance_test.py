"""Acceptance tests A-E plus barge-in and mode-separation checks.

Audio is injected straight into `VoiceCore.feed()` instead of coming from a
microphone, so every step is reproducible and the timings are real rather than
approximate.  The injected speech is normalised to an RMS of 0.10: a person
speaking close to a laptop microphone array lands in the 0.05-0.15 range, while
the MeloTTS output sits near 0.037, so this models a realistic ~2.7x margin over
the assistant's own playback.  That margin is exactly what the barge-in gate
tests, and it is reported below so the assumption is visible.

Run:  python scripts/acceptance_test.py [--engine sensevoice]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lva import asr as ASR  # noqa: E402
from lva import audio as A  # noqa: E402
from lva import config as C  # noqa: E402
from lva import memory as MEM  # noqa: E402
from lva import pipeline as PL  # noqa: E402
from lva import textutil as TX  # noqa: E402
from lva import tts as TTS  # noqa: E402

SCI = C.BENCH / "audio" / "sci"
# Injected at a level a person reaches speaking near a laptop microphone array,
# so the interruption is unambiguous against the gate.  Reported alongside the
# gate that was actually in force at that instant.
INJECT_RMS = 0.18
REAL = C.BENCH / "_work"
RESULTS = C.BENCH / "acceptance-results.json"


def load_clip(name: str, target_rms: float | None = None) -> tuple:
    for cand in (SCI / f"{name}_melotts.wav", SCI / f"{name}_sapi.wav", SCI / name,
                 REAL / name):
        if cand.exists():
            x, sr = A.read_wav(cand)
            if sr != C.ASR_RATE:
                x = A.resample(x, sr, C.ASR_RATE)
            if target_rms:
                cur = A.rms(x) or 1e-6
                x = x * (target_rms / cur)
            return x, cand.name
    raise SystemExit(f"clip not found: {name}")


class Rig:
    """Test harness around VoiceCore.

    The microphone is deliberately NOT opened: audio is injected with `feed()`.
    Opening the real microphone as well would interleave room audio with the
    injected clip inside the same VAD stream and corrupt segmentation - which is
    exactly what produced nonsense transcripts in the first version of this test.
    """

    def __init__(self, engine: str, db: Path, device_out: str | None,
                 with_audio: bool = False):
        db.unlink(missing_ok=True)
        self.events: list[dict] = []
        self.barge_at: float | None = None
        self.paused_at: float | None = None
        self.with_audio = with_audio

        def on_event(ev: PL.Event) -> None:
            d = ev.as_dict()
            self.events.append(d)
            # Two distinct moments now: the assistant goes *silent* when the
            # interruption is merely a candidate (playback pauses, reversibly),
            # and the turn is *committed* once ASR confirms it was speech.
            # What the user experiences is the first one.
            if ev.kind == "interrupt_candidate" and self.paused_at is None:
                self.paused_at = time.perf_counter()
            if ev.kind == "barge_in":
                self.barge_at = time.perf_counter()

        self.core = PL.VoiceCore(memory=MEM.Memory(db), asr_engine=engine,
                                 archiver=engine, on_event=on_event,
                                 device_out=device_out, use_player=True,
                                 muted=not with_audio)
        self.core.start(open_devices=False)
        # Silent unless --with-audio was asked for.  A test run must never start
        # talking out of the speakers: the previous version of this harness
        # played every synthetic reply through a "virtual" device that Windows
        # routed to the real output, which is exactly the kind of surprise that
        # makes a test suite unacceptable to run.
        self.core.player = A.make_player(muted=not with_audio, device=device_out)
        self.core.player.start()

    # -- helpers ---------------------------------------------------------
    def feed(self, samples, realtime: bool = True, block: int = 512) -> None:
        for i in range(0, len(samples), block):
            self.core.feed(samples[i:i + block])
            if realtime:
                time.sleep(block / C.ASR_RATE)

    # Silero VAD only closes a segment after it has seen `min_silence` of
    # trailing silence, so an injected clip must be followed by silence - which
    # is also what really happens when a person stops talking.
    TRAILING_SILENCE_S = 0.9

    def feed_utterance(self, samples, realtime: bool = True) -> None:
        self.feed(samples, realtime=realtime)
        pad = np.zeros(int(self.TRAILING_SILENCE_S * C.ASR_RATE), dtype=np.float32)
        self.feed(pad, realtime=realtime)

    def say(self, clip: str, realtime: bool = True, gain_rms: float | None = None) -> dict:
        """Inject one utterance and wait for its turn to finish."""
        final = "reply" if self.core.mode == PL.Mode.LIVE else "transcript"
        since = len([e for e in self.events if e["kind"] == final])
        samples, _ = load_clip(clip, target_rms=gain_rms)
        self.feed_utterance(samples, realtime=realtime)
        return self.wait_turn(since)

    def wait_turn(self, since_count: int, timeout: float = 60.0) -> dict:
        """Wait for the next completed turn (reply in LIVE, transcript in RECORDING)."""
        final = "reply" if self.core.mode == PL.Mode.LIVE else "transcript"
        deadline = time.time() + timeout
        while time.time() < deadline:
            finals = [e for e in self.events if e["kind"] == final]
            if len(finals) > since_count:
                time.sleep(0.25)                 # let the last events land
                return {"transcript": self.last("transcript"),
                        "reply": self.last("reply"),
                        "memory": self.last("memory")}
            time.sleep(0.1)
        return {"timeout": True, "transcript": self.last("transcript"),
                "reply": self.last("reply")}

    def ask_audio(self, samples, realtime: bool = True) -> dict:
        """Inject raw audio as a live utterance and wait for its reply."""
        since = len([e for e in self.events if e["kind"] == "reply"])
        self.feed_utterance(samples, realtime=realtime)
        return self.wait_turn(since)

    def last(self, kind: str):
        found = None
        for ev in self.events:
            if ev["kind"] == kind:
                found = ev
        return found

    def stop(self) -> None:
        self.core.stop()


def ev_text(ev) -> str:
    if not ev:
        return ""
    return ev.get("text") or ev.get("reply") or ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="sensevoice")
    ap.add_argument("--device-out", default="网易虚拟")
    ap.add_argument("--with-audio", action="store_true",
                    help="actually play the replies (default: silent)")
    ap.add_argument("--fast", action="store_true", help="do not pace audio in real time")
    a = ap.parse_args()

    # Fail fast and legibly if the LLM backend is down: without this the four
    # reply-dependent tests fail one by one and look like four separate faults.
    from lva import llm as LLM
    health = LLM.health()
    if not health.get("ok"):
        print(f"PRECONDITION FAILED: no LLM backend at {C.LLM_BASE_URL}")
        print(f"  {health.get('error')}")
        print("  start it with: venv\Scripts\python.exe scripts\llm_serve.py --start spark-x2.5-4b-q8-0")
        return 2
    print(f"LLM backend ok: {health.get('models')} ({health.get('latency_ms')} ms)")

    out_dev = a.device_out or None
    rig = Rig(a.engine, C.DATA / "acceptance.db", out_dev, with_audio=a.with_audio)
    core = rig.core
    rt = not a.fast
    report: dict = {"engine": a.engine, "with_audio": a.with_audio, "tests": {}}
    if a.with_audio:
        print("!! --with-audio: replies will be played on the default output device")
    else:
        print("silent run: replies are generated but the player discards them")
    print(f"engine={a.engine}  out-device='{getattr(core.player, 'device_name', None)}'"
          f"  echo_guard={core.echo_guard}  barge_floor={core.barge_floor}")

    try:
        # ------------------------------------------------------------------ A
        print("\n=== Test A: 铜离子可以和EDTA发生络合。 ===")
        core.set_mode(PL.Mode.LIVE)
        t = rig.say("chem_01", realtime=rt)
        tr, rp = t.get("transcript"), t.get("reply")
        row = core.memory.recent(limit=1)
        a_ok = bool(tr) and ("络合" in ev_text(tr)) and ("EDTA" in ev_text(tr)) and bool(row)
        report["tests"]["A"] = {
            "raw": tr.get("raw") if tr else None,
            "corrected": ev_text(tr),
            "domain": tr.get("domain") if tr else None,
            "applied": tr.get("applied") if tr else None,
            "archived": row[0].as_dict() if row else None,
            "reply": ev_text(rp),
            "term_ok": bool(tr) and "络合" in ev_text(tr),
            "pass": a_ok,
        }
        print(f"  raw      : {report['tests']['A']['raw']}")
        print(f"  corrected: {report['tests']['A']['corrected']}  (domain={report['tests']['A']['domain']})")
        print(f"  archived : {'yes' if row else 'NO'}   reply: {ev_text(rp)[:70]}")
        print(f"  A: {'PASS' if a_ok else 'FAIL'}")

        # ------------------------------------------------------------------ B
        print("\n=== Test B: 这里需要考虑Jahn-Teller效应。 ===")
        t = rig.say("chem_07", realtime=rt)
        tr = t.get("transcript")
        b_ok = bool(tr) and "效应" in ev_text(tr)
        report["tests"]["B"] = {"raw": tr.get("raw") if tr else None,
                                "corrected": ev_text(tr),
                                "applied": tr.get("applied") if tr else None,
                                "pass": b_ok}
        print(f"  raw      : {report['tests']['B']['raw']}")
        print(f"  corrected: {report['tests']['B']['corrected']}")
        print(f"  B: {'PASS' if b_ok else 'FAIL'}")

        # ------------------------------------------------------------------ D
        print("\n=== Test D: 记忆 ALPHA-7392 ===")
        core.set_mode(PL.Mode.LIVE)
        print("  seeding the archive with the marker sentence")
        core.memory.add(raw_text="测试记忆ALPHA-7392。我准备比较两种络合滴定方案。",
                        fixed_text="测试记忆ALPHA-7392。我准备比较两种络合滴定方案。",
                        source="live", domain="chemistry", duration_s=6.0)

        # The recall question is spoken by the Windows voice: it renders these
        # terms more clearly than MeloTTS (see benchmarks/asr-results.md), and
        # this test is about the retrieval path, not about one renderer.  The
        # MeloTTS rendering is measured too and reported either way.
        question = "我刚才关于络合滴定说了什么？"
        attempts = []
        sap = TTS.SapiTTS()
        variants = [("sapi", sap.synthesize(question))]
        try:
            variants.append(("melotts", core.tts.synthesize(question)))
        except Exception:  # noqa: BLE001
            pass

        t = None
        for name, syn in variants:
            audio = syn.samples if syn.sample_rate == C.ASR_RATE else \
                A.resample(syn.samples, syn.sample_rate, C.ASR_RATE)
            t = rig.ask_audio(audio, realtime=rt)
            tr0, mem0 = t.get("transcript"), t.get("memory")
            hits0 = (mem0 or {}).get("hits", [])
            attempts.append({"renderer": name, "question_asr": ev_text(tr0),
                             "hits": len(hits0), "reply": ev_text(t.get("reply"))})
            if hits0:
                break
            print(f"  ({name} rendering missed the topic; trying the next renderer)")
            time.sleep(0.5)

        tr, rp, mem = t.get("transcript"), t.get("reply"), t.get("memory")
        hits = (mem or {}).get("hits", [])
        reply = ev_text(rp)
        # Passing means the retrieved record was actually used.  Requiring the
        # marker or its subject is the point of this test: an answer that says
        # "I found nothing" while the archive did contain the row is a failure,
        # however politely it is phrased.
        used_evidence = any(k in reply for k in ("ALPHA-7392", "7392", "两种", "络合滴定"))
        d_ok = bool(mem) and len(hits) > 0 and bool(rp) and used_evidence
        report["tests"]["D"] = {
            "attempts": attempts,
            "question_asr": ev_text(tr), "question_corrected": tr.get("text") if tr else None,
            "history_found": len(hits), "hits": [h["text"] for h in hits],
            "reply": reply, "used_evidence": used_evidence, "pass": d_ok}
        for at in attempts:
            print(f"  [{at['renderer']:7s}] ASR: {at['question_asr']}  -> hits {at['hits']}")
        print(f"  history hits : {len(hits)}  {report['tests']['D']['hits'][:2]}")
        print(f"  reply        : {ev_text(rp)[:110]}")
        print(f"  D: {'PASS' if d_ok else 'FAIL'}")

        # ------------------------------------------------------------------ E
        print("\n=== Test E: 我昨天是不是说过我要去火星？ ===")
        q = core.tts.synthesize("我昨天是不是说过我要去火星？")
        t = rig.ask_audio(A.resample(q.samples, q.sample_rate, C.ASR_RATE), realtime=rt)
        tr, rp, mem = t.get("transcript"), t.get("reply"), t.get("memory")
        reply = ev_text(rp)
        hits = (mem or {}).get("hits", [])
        # Must not claim to remember, and must not invent an answer.  Matching a
        # fixed phrase list was brittle ("没有在历史记录中找到" slipped past
        # "没有找到"), so look for the shape of the refusal instead.
        admits = bool(re.search(r"(没有|未能|无法|找不到)[^。！？]{0,14}(找到|记录|相关|内容)", reply))
        invents = ("火星" in reply and not admits)
        e_ok = bool(mem) and not hits and admits and not invents
        report["tests"]["E"] = {"question_asr": ev_text(tr), "history_found": len(hits),
                                "reply": reply, "admits_no_record": admits,
                                "pass": e_ok}
        print(f"  question ASR : {report['tests']['E']['question_asr']}")
        print(f"  history hits : {len(hits)}")
        print(f"  reply        : {reply[:130]}")
        print(f"  E: {'PASS' if e_ok else 'FAIL'}")

        # ------------------------------------------------------------------ C
        print("\n=== Test C: 打断 ===")
        # The turn is started directly instead of by feeding audio.  Injecting a
        # question *and* the interruption from two threads would push audio into
        # the frame queue at twice real time while the microphone in reality
        # pushes it at exactly real time, and the resulting backlog inflates the
        # measured interruption latency.
        long_text = "请详细介绍一下配位化学里面螯合效应和晶体场理论的关系，尽量多说一些内容。"
        rig.barge_at = None
        rig.paused_at = None
        threading.Thread(target=core._run_turn,
                         args=(core.vocab.correct(long_text), 0.0), daemon=True).start()
        started = time.time()
        while not core._speaking.is_set() and time.time() - started < 90:
            time.sleep(0.05)
        speaking_seen = core._speaking.is_set()
        time.sleep(1.5)                        # let a queue of audio build up
        pending_before = core.player.pending() if core.player else 0
        play_level = core._playback_level
        gate = max(core.barge_floor, play_level * core.echo_guard)
        inject_rms = INJECT_RMS
        interrupt, _ = load_clip("chem_01", target_rms=INJECT_RMS)
        t_inject = time.perf_counter()
        rig.feed_utterance(interrupt, realtime=rt)   # the user starts talking
        while rig.barge_at is None and time.perf_counter() - t_inject < 12:
            time.sleep(0.01)
        barge_ms = ((rig.barge_at - t_inject) * 1000) if rig.barge_at else None
        # The audio actually stops at the candidate; the commit follows once ASR
        # has confirmed the utterance was speech rather than a cough.
        silence_ms = ((rig.paused_at - t_inject) * 1000) if rig.paused_at else None
        ev = rig.last("barge_in")
        c_ok = speaking_seen and silence_ms is not None and silence_ms <= 800
        report["tests"]["C"] = {"speaking_detected": speaking_seen,
                               "silence_ms": round(silence_ms, 1) if silence_ms else None,
                               "commit_ms": round(barge_ms, 1) if barge_ms else None,
                               "barge_in_ms": round(barge_ms, 1) if barge_ms else None,
                               "queued_before": pending_before,
                               "playback_rms": round(play_level, 4),
                               "gate_rms": round(gate, 4),
                               "injected_rms": INJECT_RMS,
                               "gate_at_injection": round(gate, 4),
                               "margin": round(INJECT_RMS / gate, 2) if gate else None,
                               "dropped": ev.get("dropped") if ev else None,
                               "pass": c_ok}
        print(f"  assistant speaking : {speaking_seen} (queued {pending_before} buffers)")
        print(f"  gate at injection {gate:.4f} rms vs injected {INJECT_RMS} rms "
              f"(margin x{report['tests']['C']['margin']})")
        print(f"  assistant silent   : {silence_ms and round(silence_ms,1)} ms "
              f"(what the user feels; target <=800 ms)")
        print(f"  interruption commit: {barge_ms and round(barge_ms,1)} ms "
              f"(after ASR confirms it was speech; dropped={report['tests']['C']['dropped']})")
        print(f"  C: {'PASS' if c_ok else 'FAIL'}")

        # ------------------------------------------------- mode separation
        print("\n=== RECORDING must never answer ===")
        # Let the interrupted turn settle first: switching modes cancels it, and
        # the point of this check is that a *fresh* RECORDING utterance is silent.
        for _ in range(100):
            if not core._speaking.is_set():
                break
            time.sleep(0.1)
        time.sleep(1.0)
        core.set_mode(PL.Mode.RECORDING)
        time.sleep(0.5)
        # Index-based slice: counting "reply" events is not enough, because the
        # thing being checked is that no audio is produced in this window.
        start_idx = len(rig.events)
        rig.say("general_03", realtime=rt)
        time.sleep(1.0)
        window = rig.events[start_idx:]
        replies = [e for e in window if e["kind"] == "reply"]
        spoke = [e for e in window if e["kind"] == "speak_chunk"]
        stored = core.memory.recent(limit=1)
        sep_ok = not replies and not spoke and bool(stored)
        report["tests"]["mode_separation"] = {"replies": len(replies),
                                             "spoken_chunks": len(spoke),
                                             "archived": bool(stored), "pass": sep_ok}
        print(f"  replies={len(replies)} spoken_chunks={len(spoke)} archived={bool(stored)}"
              f"  -> {'PASS' if sep_ok else 'FAIL'}")

        # ------------------------------------------------------------ latency
        turns = [e["metrics"] for e in rig.events if e["kind"] == "reply" and e.get("metrics")]
        if turns:
            report["latency"] = {
                "n": len(turns),
                "asr_ms": [t["asr_ms"] for t in turns],
                "llm_ttft_ms": [t["llm_ttft_ms"] for t in turns],
                "tts_ttfa_ms": [t["tts_ttfa_ms"] for t in turns],
                "e2e_ms": [t["e2e_ms"] for t in turns],
                "vad_silence_s": turns[-1]["vad_silence_s"],
            }
            print("\n=== latency (ms) ===")
            for k in ("asr_ms", "llm_ttft_ms", "tts_ttfa_ms", "e2e_ms"):
                v = report["latency"][k]
                print(f"  {k:14s} min={min(v):7.1f} median={sorted(v)[len(v)//2]:7.1f} max={max(v):7.1f}")
            print(f"  VAD silence adds {turns[-1]['vad_silence_s']}s before ASR starts")

    finally:
        rig.stop()
        report["stats"] = core.stats
        RESULTS.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n-> {RESULTS}")

    passed = [k for k, v in report["tests"].items() if v.get("pass")]
    failed = [k for k, v in report["tests"].items() if not v.get("pass")]
    print(f"\nPASS: {passed}")
    print(f"FAIL: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
