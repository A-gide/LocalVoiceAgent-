"""Self-tests for the PR-022 LatencyTrace instrument (expected GREEN).

Frozen plan line 1353 requires the root harness to carry a ``LatencyTrace``
next to the deterministic clock, the provider fakes and the redacted artifacts.
Line 970 requires the diagnostics window to report redacted latency, and line
1647 requires bounded queues with no silent backlog.

These tests prove the *instrument*: determinism, bounded retention, the
content-free summary shape, and compatibility with the harness clock. A green
result here says nothing about product latency.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lva.observability import LatencyTrace  # noqa: E402
from lva.observability.latency import DEFAULT_MAX_SPANS  # noqa: E402
from benchmarks.wasapi_loopback import percentiles as gate_percentiles  # noqa: E402


class FakeClock:
    """Monotonic seconds under explicit control, mirroring DeterministicClock."""

    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, milliseconds: float) -> None:
        self.value += milliseconds / 1000.0


def test_span_duration_is_exact():
    clock = FakeClock()
    trace = LatencyTrace(turn_id="t-1", provider_epoch=3, clock=clock)
    clock.advance(5.0)
    trace.start("asr")
    clock.advance(120.0)
    span = trace.stop("asr")

    assert span is not None
    assert span.name == "asr"
    assert span.duration_ms == pytest.approx(120.0)
    assert span.start_ms == pytest.approx(5.0)
    assert span.end_ms == pytest.approx(125.0)


def test_context_manager_records_and_closes_the_span():
    clock = FakeClock()
    trace = LatencyTrace(clock=clock)
    with trace.span("tts_ttfa"):
        clock.advance(42.5)

    assert trace.names() == ["tts_ttfa"]
    assert trace.durations("tts_ttfa") == [pytest.approx(42.5)]
    # The span is closed, so a second stop finds nothing to close.
    assert trace.stop("tts_ttfa") is None


def test_replay_is_deterministic():
    def scenario() -> dict:
        clock = FakeClock()
        trace = LatencyTrace(turn_id="t-2", provider_epoch=1, clock=clock)
        for duration in (30.0, 45.0, 60.0, 75.0):
            trace.start("llm_ttft")
            clock.advance(duration)
            trace.stop("llm_ttft")
        return trace.summary()

    assert scenario() == scenario()


def test_mark_records_an_instantaneous_point():
    clock = FakeClock()
    trace = LatencyTrace(clock=clock)
    clock.advance(10.0)
    at = trace.mark("interrupt_commit")
    assert at == pytest.approx(10.0)
    assert trace.durations("interrupt_commit") == [0.0]


def test_percentiles_match_the_acoustic_gate_convention():
    clock = FakeClock()
    trace = LatencyTrace(clock=clock)
    samples = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    for sample in samples:
        trace.start("turn")
        clock.advance(sample)
        trace.stop("turn")

    ours = trace.percentiles("turn")
    theirs = gate_percentiles(samples)
    assert ours.keys() == theirs.keys()
    for key in ("p50", "p95", "p99"):
        # Same order statistic; only floating-point accumulation differs.
        assert ours[key] == pytest.approx(theirs[key], abs=1e-6)
    assert ours["p50"] == pytest.approx(50.0, abs=1e-6)
    assert ours["p95"] == pytest.approx(100.0, abs=1e-6)
    assert ours["p99"] == pytest.approx(100.0, abs=1e-6)


def test_retention_is_bounded_and_reported():
    clock = FakeClock()
    trace = LatencyTrace(clock=clock, max_spans=4)
    for _ in range(6):
        trace.mark("tick")

    assert len(trace) == 4
    assert trace.dropped_spans == 2
    assert trace.retention_warning is True
    summary = trace.summary()
    assert summary["span_count"] == 4
    assert summary["dropped_spans"] == 2
    assert summary["retention_warning"] is True


def test_default_retention_matches_the_documented_budget():
    trace = LatencyTrace(clock=FakeClock())
    assert trace._max_spans == DEFAULT_MAX_SPANS  # noqa: SLF001 - budget is the contract
    assert DEFAULT_MAX_SPANS == 512


def test_summary_carries_no_content_and_survives_redaction():
    clock = FakeClock()
    trace = LatencyTrace(turn_id="t-3", provider_epoch=7, clock=clock)
    with trace.span("llm_ttft"):
        clock.advance(88.0)

    summary = trace.summary()
    assert summary["turn_id"] == "t-3"
    assert summary["provider_epoch"] == 7
    assert summary["spans"]["llm_ttft"]["count"] == 1
    assert summary["spans"]["llm_ttft"]["p99_ms"] == pytest.approx(88.0)

    # The redacted view is byte-identical here: there is nothing to strip,
    # because the summary never carried text, audio or a path.
    assert trace.redacted() == summary
    assert json.dumps(trace.redacted())


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        "asr latency",
        "C:\\Users\\alice\\voice.log",
        "用户文本",
        "turn:1",
    ],
)
def test_content_bearing_span_names_are_rejected(bad_name):
    trace = LatencyTrace(clock=FakeClock())
    with pytest.raises(ValueError):
        trace.mark(bad_name)


def test_max_spans_must_be_positive():
    with pytest.raises(ValueError):
        LatencyTrace(clock=FakeClock(), max_spans=0)
