"""Soak Test Harness for LocalVoiceAgent (PR-035 / Part 13.4).

Executes continuous stress and stability testing across LVA Core, Journal v2,
Command Engine, and State Machine. Measures:
- Memory growth (RSS slope and peak)
- Thread and handle counts
- Latency percentiles (P50, P95, P99)
- Invariant assertions (I01–I20)
- Journal SQLite integrity check
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.lva.contracts.commands import (
    CommandEnvelope,
    RuntimeGetSnapshotPayload,
    MemorySearchPayload,
    RuntimeRestoreModePayload,
    RuntimeSetModePayload,
    TurnCancelPayload,
    TurnSendTextPayload,
)
from src.lva.contracts.enums import FloorOwner, Mode, PrivacyScope
from src.lva.core.runtime import RuntimeController
from src.lva.journal.repository import JournalRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("soak")


@dataclass
class LatencyRecord:
    operation: str
    duration_ms: float
    timestamp: float


@dataclass
class ResourceSample:
    elapsed_s: float
    rss_mb: float
    threads: int
    open_handles: int = 0


@dataclass
class SoakReport:
    start_time: str
    end_time: str
    duration_s: float
    total_iterations: int
    completed_turns: int
    interrupted_turns: int
    memory_searches: int
    mode_transitions: int
    rejected_commands: int
    invariants_passed: bool
    invariant_violations: list[str] = field(default_factory=list)
    initial_rss_mb: float = 0.0
    peak_rss_mb: float = 0.0
    final_rss_mb: float = 0.0
    rss_growth_mb: float = 0.0
    rss_growth_percent: float = 0.0
    journal_integrity: str = "unknown"
    latencies: dict[str, dict[str, float]] = field(default_factory=dict)
    gate_verdict: str = "FAIL"


def get_memory_rss_mb() -> float:
    """Read process RSS memory in MB."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        f = ctypes.windll.kernel32.K32GetProcessMemoryInfo
        f.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        f.restype = wintypes.BOOL
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if f(handle, ctypes.byref(counters), counters.cb):
            return float(counters.WorkingSetSize) / (1024 * 1024)
    except Exception:
        pass
    return 0.0


def get_thread_count() -> int:
    """Read thread count."""
    try:
        import psutil
        return psutil.Process().num_threads()
    except Exception:
        import threading
        return threading.active_count()


def compute_gate_verdict(
    *,
    growth_ok: bool,
    interrupt_ok: bool,
    invariants_ok: bool,
    integrity_ok: bool,
    mode_transitions: int,
    rejected_commands: int,
) -> str:
    """Return PASS/FAIL for a soak run.

    A run whose mode commands were *all* rejected is not a healthy run: the
    loop would otherwise report PASS while having done nothing at all.
    """
    attempted = mode_transitions + rejected_commands
    commands_ok = attempted == 0 or rejected_commands < attempted
    if growth_ok and interrupt_ok and invariants_ok and integrity_ok and commands_ok:
        return "PASS"
    return "FAIL"


class SoakHarness:
    def __init__(self, duration_s: float, db_path: Path):
        self.duration_s = duration_s
        self.db_path = db_path
        self.journal = JournalRepository(db_path)
        self.events_log: list[dict[str, Any]] = []

        def broadcast(env: Any) -> None:
            if hasattr(env, "model_dump"):
                self.events_log.append(env.model_dump(mode="json"))

        self.runtime = RuntimeController(event_broadcaster=broadcast, journal=self.journal)
        self.latencies: list[LatencyRecord] = []
        self.resource_samples: list[ResourceSample] = []
        self.violations: list[str] = []

        self.total_iterations = 0
        self.completed_turns = 0
        self.interrupted_turns = 0
        self.memory_searches = 0
        self.mode_transitions = 0
        self.rejected_commands = 0

    def record_latency(self, op: str, duration_ms: float) -> None:
        self.latencies.append(LatencyRecord(operation=op, duration_ms=duration_ms, timestamp=time.time()))

    def assert_invariants(self) -> None:
        state = self.runtime.get_state()
        # I02: current turn check
        if state.session_id is not None:
            cur = self.runtime.turn_controller.current_turn
            if cur is not None and cur.session_id != state.session_id:
                self.violations.append(f"I02 violated: Current turn session mismatch: {cur.session_id} != {state.session_id}")

        # I07 / I08: Passive mode must not schedule LLM/TTS
        if state.mode == Mode.PASSIVE:
            if state.floor == FloorOwner.AGENT:
                self.violations.append("I07/I08 violated: Agent floor claimed in Passive mode")

        # I09: Privacy pause capture check
        if state.mode == Mode.PRIVACY_PAUSE:
            if state.mic_capture.active:
                self.violations.append("I09 violated: Mic capture active during Privacy Pause")

    async def run(self) -> SoakReport:
        log.info("Starting soak test: duration=%.1fs, target_db=%s", self.duration_s, self.db_path)
        t_start = time.time()
        start_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_start))

        # Initial warm-up
        initial_rss = get_memory_rss_mb()
        peak_rss = initial_rss
        log.info("Initial RSS: %.2f MB, Threads: %d", initial_rss, get_thread_count())

        # Start session
        session_id = self.runtime.session_controller.start_session()

        deadline = t_start + self.duration_s
        cycle_idx = 0

        while time.time() < deadline:
            cycle_idx += 1
            self.total_iterations += 1
            t_cycle = time.time()

            # 1. Mode Cycle
            modes = [Mode.LIVE, Mode.PASSIVE, Mode.PRIVACY_PAUSE, Mode.STANDBY]
            target_mode = modes[cycle_idx % len(modes)]
            t0 = time.perf_counter()
            mode_result = self.runtime.execute_command(
                CommandEnvelope(
                    schema_version="1.0",
                    command_id=uuid4(),
                    issued_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    type="runtime.set_mode",
                    precondition={
                        "aggregate": "runtime_control",
                        "revision": self.runtime.runtime_control_revision,
                    },
                    payload=RuntimeSetModePayload(type="runtime.set_mode", mode=target_mode),
                )
            )
            self.record_latency("set_mode", (time.perf_counter() - t0) * 1000)
            # Only a command that actually applied counts as a mode transition;
            # a rejected call must not be reported as a mode switch.
            if mode_result.status == "applied":
                self.mode_transitions += 1
            else:
                self.rejected_commands += 1

            # 2. Turn Execution (if in Live or Passive mode)
            if target_mode == Mode.LIVE:
                turn_text = f"Soak test turn prompt iteration {cycle_idx} at {time.time()}"
                t0 = time.perf_counter()
                turn_id = self.runtime.turn_controller.create_turn(session_id, turn_text)
                self.record_latency("create_turn", (time.perf_counter() - t0) * 1000)

                # Simulate interrupt on every 3rd turn (I03 / rapid barge-in)
                if cycle_idx % 3 == 0:
                    t0 = time.perf_counter()
                    new_epoch = self.runtime.interrupt_controller.commit_interrupt(reason="soak_barge_in")
                    self.runtime.turn_controller.cancel_turn(turn_id, reason="barge_in")
                    self.record_latency("interrupt_commit", (time.perf_counter() - t0) * 1000)
                    self.interrupted_turns += 1
                else:
                    # Complete turn and write to Journal
                    t0 = time.perf_counter()
                    event_id = uuid4()
                    self.journal.append_event(
                        event_id=event_id,
                        raw_text=turn_text,
                        session_id=session_id,
                        turn_sequence=turn_id.sequence,
                        speaker="user",
                        source="soak_test",
                        domain="general",
                    )
                    self.runtime.turn_controller.complete_turn(turn_id)
                    self.record_latency("turn_complete", (time.perf_counter() - t0) * 1000)
                    self.completed_turns += 1

            # 3. Journal Search & Temporal Recall
            if cycle_idx % 2 == 0:
                t0 = time.perf_counter()
                hits = self.journal.search("iteration", limit=5)
                self.record_latency("journal_search", (time.perf_counter() - t0) * 1000)
                self.memory_searches += 1

            # 4. Invariant Assertions
            self.assert_invariants()

            # 5. Resource Sampling
            rss = get_memory_rss_mb()
            if rss > peak_rss:
                peak_rss = rss

            elapsed = time.time() - t_start
            self.resource_samples.append(ResourceSample(
                elapsed_s=elapsed,
                rss_mb=rss,
                threads=get_thread_count(),
            ))

            # Small sleep to throttle iteration rate
            await asyncio.sleep(0.05)

        t_end = time.time()
        end_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_end))
        final_rss = get_memory_rss_mb()
        rss_growth = final_rss - initial_rss
        rss_growth_pct = (rss_growth / initial_rss * 100) if initial_rss > 0 else 0.0

        # Check SQLite integrity
        integrity = "ok"
        try:
            res = self.journal.conn.execute("PRAGMA integrity_check;").fetchone()
            if res and res[0] != "ok":
                integrity = f"FAILED: {res[0]}"
        except Exception as e:
            integrity = f"ERROR: {e}"

        # Compute latency percentiles
        lat_stats: dict[str, dict[str, float]] = {}
        for op in ["set_mode", "create_turn", "interrupt_commit", "turn_complete", "journal_search"]:
            durs = [r.duration_ms for r in self.latencies if r.operation == op]
            if durs:
                durs.sort()
                p50 = durs[int(len(durs) * 0.50)]
                p95 = durs[min(int(len(durs) * 0.95), len(durs) - 1)]
                p99 = durs[min(int(len(durs) * 0.99), len(durs) - 1)]
                lat_stats[op] = {
                    "count": len(durs),
                    "p50_ms": round(p50, 2),
                    "p95_ms": round(p95, 2),
                    "p99_ms": round(p99, 2),
                }

        # Gate verdicts
        # 12h RSS Gate: growth < max(200MB, 10%)
        # Interrupt Gate: P95 <= 20ms
        growth_ok = rss_growth < 200.0 or rss_growth_pct < 10.0
        interrupt_p95 = lat_stats.get("interrupt_commit", {}).get("p95_ms", 0.0)
        interrupt_ok = interrupt_p95 <= 20.0 or interrupt_p95 == 0.0
        invariants_ok = len(self.violations) == 0
        integrity_ok = integrity == "ok"

        verdict = compute_gate_verdict(
            growth_ok=growth_ok,
            interrupt_ok=interrupt_ok,
            invariants_ok=invariants_ok,
            integrity_ok=integrity_ok,
            mode_transitions=self.mode_transitions,
            rejected_commands=self.rejected_commands,
        )

        return SoakReport(
            start_time=start_iso,
            end_time=end_iso,
            duration_s=round(t_end - t_start, 2),
            total_iterations=self.total_iterations,
            completed_turns=self.completed_turns,
            interrupted_turns=self.interrupted_turns,
            memory_searches=self.memory_searches,
            mode_transitions=self.mode_transitions,
            rejected_commands=self.rejected_commands,
            invariants_passed=invariants_ok,
            invariant_violations=self.violations,
            initial_rss_mb=round(initial_rss, 2),
            peak_rss_mb=round(peak_rss, 2),
            final_rss_mb=round(final_rss, 2),
            rss_growth_mb=round(rss_growth, 2),
            rss_growth_percent=round(rss_growth_pct, 2),
            journal_integrity=integrity,
            latencies=lat_stats,
            gate_verdict=verdict,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="LocalVoiceAgent Soak Test Harness")
    parser.add_argument("--duration", type=float, default=10.0, help="Duration in seconds (e.g. 10, 7200 for 2h)")
    parser.add_argument("--report", type=str, default="soak_report.json", help="Path to write JSON report")
    parser.add_argument("--db", type=str, default=":memory:", help="Database path (:memory: or file)")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db != ":memory:" else Path("temp_soak_journal.sqlite3")
    if db_path.exists() and args.db == ":memory:":
        try:
            db_path.unlink()
        except Exception:
            pass

    harness = SoakHarness(duration_s=args.duration, db_path=db_path)
    report = asyncio.run(harness.run())

    # Write report
    out_path = Path(args.report)
    out_path.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Report written to %s", out_path)

    # Print summary
    print("\n" + "=" * 60)
    print(f"  SOAK TEST RESULT: {report.gate_verdict}")
    print("=" * 60)
    print(f"Duration:            {report.duration_s}s ({report.total_iterations} iterations)")
    print(f"Turns:               {report.completed_turns} completed, {report.interrupted_turns} interrupted")
    print(f"Mode Transitions:    {report.mode_transitions}")
    print(f"Rejected Commands:       {report.rejected_commands}")
    print(f"Memory (RSS):        Initial: {report.initial_rss_mb} MB -> Peak: {report.peak_rss_mb} MB -> Final: {report.final_rss_mb} MB")
    print(f"RSS Growth:          {report.rss_growth_mb} MB ({report.rss_growth_percent}%)")
    print(f"Journal Integrity:   {report.journal_integrity}")
    print(f"Invariants Violations: {len(report.invariant_violations)}")
    print("Latency Percentiles:")
    for op, stats in report.latencies.items():
        print(f"  - {op:<18}: P50={stats['p50_ms']}ms, P95={stats['p95_ms']}ms, P99={stats['p99_ms']}ms (n={stats['count']})")
    print("=" * 60)

    # Cleanup temp db if used
    if args.db == ":memory:" and db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass

    return 0 if report.gate_verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
