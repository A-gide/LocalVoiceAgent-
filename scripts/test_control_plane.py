"""Control-plane invariants, checked without a sound card.

These are the rules that stop the failures every comparable project has shipped
at least one of: audio from an interrupted turn playing anyway, a reply that
cannot be interrupted, a cough opening a turn, a backchannel killing a sentence,
a queue that grows without bound.

The interesting one is INV-1.  Checking a generation *before* queueing audio is
not enough, because the interruption can land in the window between that check
and the enqueue - Vocalis has exactly this hole (the check and the send are
separated by an await) and so did this project until the player started rejecting
blocks from a superseded generation where they are *used*.  So the test drives the
production callback directly with a stale block and asserts silence comes out.

    python scripts/test_control_plane.py
"""
from __future__ import annotations

import queue
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lva import audio as A  # noqa: E402
from lva import config as C  # noqa: E402
from lva import memory as MEM  # noqa: E402
from lva import pipeline as PL  # noqa: E402

_cores = 0


def fresh_core() -> PL.VoiceCore:
    """A VoiceCore with no devices, no TTS engine and its own throwaway database.

    A fresh file per core, because SQLite keeps a handle open and deleting the
    file underneath a live connection fails on Windows.
    """
    global _cores
    _cores += 1
    db = C.DATA / f"control_plane_test_{_cores}.db"
    core = PL.VoiceCore(memory=MEM.Memory(db), tts_engine="none",
                        use_player=True, muted=True)
    core.player = A.make_player(muted=True)
    return core

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:34s} {detail}")


def call_output(player, frames: int = 1024) -> np.ndarray:
    """Drive the production output callback once and return what it wrote."""
    out = np.zeros((frames, 1), dtype=np.float32)
    player._callback(out, frames, None, None)
    return out[:, 0]


# ---------------------------------------------------------------- INV-1
def inv1_stale_audio_never_plays() -> None:
    p = A.Player(device=None)                 # no stream opened
    gen = p.generation
    p.play(np.full(1600, 0.5, dtype=np.float32), p.rate, gen=gen)
    before = np.abs(call_output(p)).max()
    p.flush()                                  # interruption
    p.play(np.full(1600, 0.5, dtype=np.float32), p.rate, gen=gen)   # late producer
    after = np.abs(call_output(p)).max()
    p.play(np.full(1600, 0.4, dtype=np.float32), p.rate, gen=p.generation)
    current = np.abs(call_output(p)).max()
    check("INV-1 stale block never plays", before > 0 and after == 0.0 and current > 0,
          f"before={before:.2f} after-flush={after:.2f} current={current:.2f} "
          f"stale_dropped={p.stale_dropped}")

    n = A.make_player(muted=True)
    g = n.generation
    n.play(np.zeros(16000, dtype=np.float32), 16000, gen=g)
    n.flush()
    n.play(np.zeros(16000, dtype=np.float32), 16000, gen=g)
    time.sleep(0.05)
    check("INV-1 null player drops too", n.pending() == 0 and n.stale_dropped == 1,
          f"pending={n.pending()} stale_dropped={n.stale_dropped}")


# ---------------------------------------------------------------- INV-2
def inv2_pause_is_reversible() -> None:
    p = A.Player(device=None)
    p.play(np.full(1600, 0.4, dtype=np.float32), p.rate, gen=p.generation)
    p.pause()
    muted = np.abs(call_output(p)).max()
    kept = p.pending()
    p.resume()
    resumed = np.abs(call_output(p)).max()
    check("INV-2 pause keeps queue and position", muted == 0.0 and kept > 0 and resumed > 0,
          f"paused_out={muted:.2f} pending={kept} resumed_out={resumed:.2f}")


# ---------------------------------------------------------------- INV-3
def inv3_generation_monotonic_and_ordered() -> None:
    core = fresh_core()
    snapshots = [core._generation]
    core._generation += 1; snapshots.append(core._generation)     # turn start path
    core.cancel_turn(); snapshots.append(core._generation)
    core.barge_in(); snapshots.append(core._generation)
    monotonic = all(b >= a for a, b in zip(snapshots, snapshots[1:]))
    strictly_after_cancel = snapshots[-1] > snapshots[-2] or snapshots[-2] > snapshots[-3]
    check("INV-3 generation monotonic", monotonic and strictly_after_cancel,
          f"sequence={snapshots}")

    # The ordering rule itself: after barge_in, the player's generation has
    # already moved past the generation of the turn being interrupted.
    core._generation += 1
    turn_gen = core._generation
    core.player.play(np.zeros(8000, dtype=np.float32), 16000, gen=turn_gen)
    core.barge_in()
    core.player.play(np.zeros(8000, dtype=np.float32), 16000, gen=turn_gen)
    time.sleep(0.05)
    check("INV-3 barge-in bumps before flush", core.player.pending() == 0,
          f"pending={core.player.pending()} gen={core._generation}")


# ---------------------------------------------------------------- INV-4
def inv4_preroll_is_an_exchange() -> None:
    core = fresh_core()
    core.player = A.make_player(muted=True)
    for _ in range(10):
        core._preroll.append(np.ones(512, dtype=np.float32))
    core.barge_in()
    first = len(core._prepend)
    left = len(core._preroll)
    core.barge_in()
    second = len(core._prepend)
    check("INV-4 pre-roll exchanged once", first > 0 and left == 0 and second == 0,
          f"first={first} ring_after={left} second_handover={second}")


# ---------------------------------------------------------------- INV-5
def inv5_bounded_queues_drop_oldest() -> None:
    stats: dict = {}
    q: queue.Queue = queue.Queue(maxsize=4)
    for i in range(10):
        PL.VoiceCore._offer(q, i, "dropped", stats)
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    check("INV-5 overflow drops oldest, counts", len(items) == 4 and items == [6, 7, 8, 9]
          and stats.get("dropped") == 6,
          f"kept={items} dropped={stats.get('dropped')}")

    core = fresh_core()
    check("INV-5 core queues are bounded",
          core._frame_q.maxsize == C.FRAME_QUEUE_MAX and core._turn_q.maxsize == C.TURN_QUEUE_MAX,
          f"frame={core._frame_q.maxsize} turn={core._turn_q.maxsize}")


# ---------------------------------------------------------------- INV-6
def inv6_short_segment_is_not_a_turn() -> None:
    core = fresh_core()
    short = np.zeros(int((C.MIN_UTTERANCE_S - 0.05) * C.ASR_RATE), dtype=np.float32)
    long = np.zeros(int((C.MIN_UTTERANCE_S + 0.25) * C.ASR_RATE), dtype=np.float32)
    kept_short = core._accept_segment(short)
    kept_long = core._accept_segment(long)
    check("INV-6 short segment rejected", (not kept_short) and kept_long
          and core.stats.get("short_segments") == 1,
          f"min={C.MIN_UTTERANCE_S}s short_kept={kept_short} long_kept={kept_long}")


# ---------------------------------------------------------------- INV-7
def inv7_backchannel_resumes_instead_of_killing() -> None:
    core = fresh_core()
    core._speaking.set()
    core.player.play(np.zeros(16000, dtype=np.float32), 16000, gen=core._generation)
    core._candidate_interrupt(0.2)
    paused = core.player.paused and core._candidate_pending
    core._resume_after_candidate("backchannel")
    resumed = (not core.player.paused) and (not core._candidate_pending)
    still_armed = core._speaking.is_set()
    check("INV-7 candidate pauses, resume restores",
          paused and resumed and still_armed,
          f"paused={paused} resumed={resumed} re-armed={still_armed}")

    # A candidate that never becomes an utterance must not leave it paused.
    core._candidate_interrupt(0.2)
    core._candidate_deadline = time.time() - 1
    core._on_block(np.zeros(C.VAD_WINDOW, dtype=np.float32))
    check("INV-7 unresolved candidate times out",
          not core.player.paused and not core._candidate_pending,
          f"paused={core.player.paused} pending={core._candidate_pending}")


def main() -> int:
    print("=== control-plane invariants (no audio device used) ===")
    print()
    inv1_stale_audio_never_plays()
    inv2_pause_is_reversible()
    inv3_generation_monotonic_and_ordered()
    inv4_preroll_is_an_exchange()
    inv5_bounded_queues_drop_oldest()
    inv6_short_segment_is_not_a_turn()
    inv7_backchannel_resumes_instead_of_killing()
    bad = [n for n, ok, _ in RESULTS if not ok]
    print()
    print(f"=== {len(RESULTS) - len(bad)}/{len(RESULTS)} invariants hold ===")
    if bad:
        print("failed: " + ", ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
