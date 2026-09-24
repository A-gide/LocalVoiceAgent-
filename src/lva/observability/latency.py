"""Latency tracing for turn and provider instrumentation (PR-022).

Frozen plan references:

* line 1353 - the root harness must carry a ``LatencyTrace`` next to the
  deterministic clock / provider fakes and the redacted artifacts;
* line 970 - the diagnostics window reports redacted events / latency / queues.

Three properties keep this instrument trustworthy:

* **Durations only.** A trace stores span names, a turn identity, a provider
  epoch and numbers. User text, audio and absolute paths have nowhere to go,
  and span names are validated so a transcript cannot be smuggled in through a
  label.
* **Deterministic.** The time source is injected, so replaying a scenario with
  the harness ``DeterministicClock`` reproduces identical numbers.
* **Bounded.** Retention is capped per trace. Drops are counted and flagged
  instead of letting a queue grow silently (frozen plan line 1647).
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

from .redact import redact_dict

__all__ = ["DEFAULT_MAX_SPANS", "LatencyTrace", "Span"]

DEFAULT_MAX_SPANS = 512

# Diagnostics labels are identifiers, never content.
_NAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


def _validated(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("span name must be a non-empty string")
    if not set(name) <= _NAME_CHARS:
        raise ValueError(
            f"span name {name!r} contains characters outside [A-Za-z0-9._-]; "
            "diagnostics labels must not carry user content"
        )
    return name


@dataclass(frozen=True)
class Span:
    """A completed interval, in milliseconds relative to the trace start."""

    name: str
    start_ms: float
    end_ms: float

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms


class LatencyTrace:
    """Per-turn span timeline.

    ``clock`` must return monotonic seconds (``time.perf_counter`` by default).
    The harness passes its deterministic clock so a replay is reproducible.
    """

    def __init__(
        self,
        *,
        turn_id: str | None = None,
        provider_epoch: int = 0,
        clock: Callable[[], float] | None = None,
        max_spans: int = DEFAULT_MAX_SPANS,
    ) -> None:
        if max_spans <= 0:
            raise ValueError("max_spans must be positive")
        self.turn_id = turn_id
        self.provider_epoch = provider_epoch
        self._clock: Callable[[], float] = clock or time.perf_counter
        self._max_spans = max_spans
        self._origin = self._clock()
        self._spans: list[Span] = []
        self._open: dict[str, float] = {}
        self.dropped_spans = 0
        self.retention_warning = False

    # ------------------------------------------------------------- timeline
    def _now(self) -> float:
        return (self._clock() - self._origin) * 1000.0

    def _append(self, span: Span) -> None:
        self._spans.append(span)
        if len(self._spans) > self._max_spans:
            # Bounded retention: drop the oldest interval, count the loss.
            self._spans.pop(0)
            self.dropped_spans += 1
            self.retention_warning = True

    def mark(self, name: str) -> float:
        """Record an instantaneous point and return it in milliseconds."""
        name = _validated(name)
        now = self._now()
        self._append(Span(name, now, now))
        return now

    def start(self, name: str) -> float:
        name = _validated(name)
        now = self._now()
        self._open[name] = now
        return now

    def stop(self, name: str) -> Span | None:
        """Close an open span. Returns ``None`` when it was never started."""
        name = _validated(name)
        began = self._open.pop(name, None)
        if began is None:
            return None
        span = Span(name, began, self._now())
        self._append(span)
        return span

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        self.start(name)
        try:
            yield
        finally:
            self.stop(name)

    # -------------------------------------------------------------- readout
    def spans(self) -> tuple[Span, ...]:
        return tuple(self._spans)

    def names(self) -> list[str]:
        return sorted({s.name for s in self._spans})

    def durations(self, name: str) -> list[float]:
        return [s.duration_ms for s in self._spans if s.name == name]

    def total_ms(self) -> float:
        return self._now()

    def percentiles(
        self, name: str, qs: Iterable[float] = (0.5, 0.95, 0.99)
    ) -> dict[str, float]:
        """Nearest-rank percentiles.

        The convention is identical to ``benchmarks/wasapi_loopback.percentiles``
        so the acoustic gate and the turn trace report comparable numbers.
        """
        values = sorted(self.durations(name))
        out: dict[str, float] = {}
        for q in qs:
            key = f"p{int(round(q * 100))}"
            if not values:
                out[key] = 0.0
                continue
            if len(values) == 1:
                out[key] = values[0]
                continue
            idx = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
            out[key] = values[idx]
        return out

    def summary(self) -> dict[str, Any]:
        """JSON-serialisable view: counts, percentiles and totals only."""
        spans: dict[str, dict[str, float | int]] = {}
        for name in self.names():
            values = self.durations(name)
            pct = self.percentiles(name)
            spans[name] = {
                "count": len(values),
                "last_ms": round(values[-1], 3),
                "p50_ms": round(pct["p50"], 3),
                "p95_ms": round(pct["p95"], 3),
                "p99_ms": round(pct["p99"], 3),
            }
        return {
            "turn_id": self.turn_id,
            "provider_epoch": self.provider_epoch,
            "span_count": len(self._spans),
            "dropped_spans": self.dropped_spans,
            "retention_warning": self.retention_warning,
            "total_ms": round(self.total_ms(), 3),
            "spans": spans,
        }

    def redacted(self) -> dict[str, Any]:
        """Summary passed through the shared redactor (defence in depth)."""
        return redact_dict(self.summary())

    def __len__(self) -> int:
        return len(self._spans)
