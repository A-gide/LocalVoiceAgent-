"""Benchmark verification tests ensuring performance criteria meet Part 13.4 gates:

1. callback duration: P99 < 1ms under heavy load.
2. interrupt commit -> playback stop request: P95 <= 20ms.
3. Journal v2 search & integrity under scale: P95 <= 50ms, integrity_check=ok.
4. Bounded queue enforcement: bounded memory, zero backlog growth, strict drop accounting.
"""
from __future__ import annotations

import queue
import time
from datetime import datetime, timezone
from uuid import uuid4

import numpy as np
import pytest

from lva.contracts.enums import FloorOwner, Mode
from lva.core.floor import FloorController
from lva.core.interrupt import InterruptController
from lva.core.runtime import RuntimeController
from lva.core.turn import TurnController
from lva.journal.repository import JournalRepository
from lva.pipeline import VoiceCore


def test_benchmark_audio_callback_duration():
    """Gate: audio callback duration P99 < 1ms."""
    q: queue.Queue = queue.Queue(maxsize=10)
    stats: dict[str, int] = {}
    latencies_ms: list[float] = []

    # 5,000 iterations to get a robust percentile distribution
    for i in range(5000):
        dummy_block = np.zeros(160, dtype=np.float32)
        t0 = time.perf_counter()
        VoiceCore._offer(q, dummy_block, "frames_dropped", stats)
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000)

    p50 = np.percentile(latencies_ms, 50)
    p95 = np.percentile(latencies_ms, 95)
    p99 = np.percentile(latencies_ms, 99)

    print(f"\n[Benchmark] Audio callback: P50={p50:.4f}ms, P95={p95:.4f}ms, P99={p99:.4f}ms")
    assert p99 < 1.0, f"P99 callback latency was {p99:.3f}ms, must be < 1.0ms"
    assert stats.get("frames_dropped", 0) > 4000


def test_benchmark_interrupt_barge_in_latency():
    """Gate: interrupt commit -> playback stop / cancel request P95 <= 20ms."""
    latencies_ms: list[float] = []

    for _ in range(50):
        turn_ctrl = TurnController()
        floor_ctrl = FloorController()
        floor_ctrl.set_owner(FloorOwner.AGENT)
        interrupt_ctrl = InterruptController(
            turn_controller=turn_ctrl,
            floor_controller=floor_ctrl,
        )

        session_id = uuid4()
        turn_ctrl.create_turn(session_id, user_text="Speaking...")

        t0 = time.perf_counter()
        # Commit interrupt
        interrupt_ctrl.commit_interrupt(reason="barge_in")
        t1 = time.perf_counter()

        latencies_ms.append((t1 - t0) * 1000)
        assert floor_ctrl.owner == FloorOwner.USER
        assert turn_ctrl.current_turn is None

    p95 = np.percentile(latencies_ms, 95)
    print(f"\n[Benchmark] Interrupt commit latency: P95={p95:.4f}ms")
    assert p95 <= 20.0, f"P95 interrupt latency was {p95:.3f}ms, must be <= 20ms"


def test_benchmark_journal_v2_scale_and_search():
    """Gate: Journal v2 scale performance, FTS5 + temporal search latency, and integrity."""
    repo = JournalRepository()  # in-memory SQLite WAL

    # Populate 1,000 events with mixed Chinese text, dates, and terms
    anchor_base = 1789000000_000000  # microseconds
    sample_texts = [
        "明天做络合滴定实验",
        "今天讨论了关于有机化学的机理",
        "昨天我们一起吃了火锅",
        "请帮我计算一下反应速率常数",
        "关于量子力学中的测不准原理",
        "今天天气真不错，出去散步了",
        "上周记录的实验数据需要重新整理",
        "什么是配位化合物的配位数？",
    ]

    for i in range(1000):
        t = sample_texts[i % len(sample_texts)]
        repo.append_event(
            event_id=uuid4(),
            raw_text=f"{t} (编号 {i})",
            occurred_at_utc_us=anchor_base + i * 60_000_000,
        )

    # Measure search latency across 100 queries
    queries = [
        "络合滴定",
        "火锅",
        "今天有什么安排",
        "明天做实验",
        "量子力学",
        "非对称合成",
    ]
    latencies_ms: list[float] = []

    for i in range(100):
        q = queries[i % len(queries)]
        t0 = time.perf_counter()
        hits = repo.search(q, limit=10)
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000)

    p50 = np.percentile(latencies_ms, 50)
    p95 = np.percentile(latencies_ms, 95)
    print(f"\n[Benchmark] Journal search (1,000 records): P50={p50:.2f}ms, P95={p95:.2f}ms")

    assert p95 <= 50.0, f"P95 search latency was {p95:.2f}ms, must be <= 50ms"

    # Verify integrity
    cur = repo.conn.execute("PRAGMA integrity_check;")
    assert cur.fetchone()[0] == "ok"


def test_benchmark_bounded_queue_backlog_recovery():
    """Gate: Bounded queues drop on full without persistent backlog or memory growth."""
    q: queue.Queue = queue.Queue(maxsize=20)
    stats: dict[str, int] = {}

    # Rapidly push 1,000 blocks into a queue with capacity 20
    for i in range(1000):
        VoiceCore._offer(q, f"chunk-{i}", "frames_dropped", stats)

    # Queue must strictly be bounded at maxsize=20
    assert q.qsize() == 20
    # Overflows must be accounted for accurately
    assert stats["frames_dropped"] == 980

    # Draining queue retrieves newest chunks
    drained = []
    while not q.empty():
        drained.append(q.get_nowait())
    assert len(drained) == 20
    assert drained[-1] == "chunk-999"
