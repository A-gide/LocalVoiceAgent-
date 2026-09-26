"""T08 micro-benchmarks for the paths T01-T04 touched (no hardware required).

The frozen plan's T08 gate metrics (speech onset-to-silence, audio callback
duration, VRAM peak, 12h soak) need real devices and a live model and are NOT
measured here.  What this records is the codeable part: importer throughput and
Core command dispatch latency on synthetic data, so a regression in the paths
these slices changed is visible without a device rig.

Usage::

    python benchmarks/t08_codeable_latency.py --records 2000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))


class _Client:
    def __init__(self, items):
        self.items = items

    async def search(self, limit=50, offset=0, start_time=None, end_time=None):
        lo = datetime.fromisoformat(start_time) if start_time else None
        hi = datetime.fromisoformat(end_time) if end_time else None
        visible = []
        for item in self.items:
            occurred = datetime.fromisoformat(item["content"]["timestamp"])
            if lo is not None and occurred < lo:
                continue
            if hi is not None and occurred >= hi:
                continue
            visible.append(item)
        return visible[offset : offset + limit]


def _records(count: int):
    base = datetime(2026, 9, 25, tzinfo=timezone.utc)
    return [
        {
            "id": f"capture-{i}",
            "content": {
                "transcription": f"synthetic utterance {i}",
                "timestamp": (base + timedelta(seconds=i)).isoformat(),
            },
        }
        for i in range(count)
    ]


def measure_import(count: int, limit: int) -> dict:
    from lva.journal.repository import JournalRepository
    from lva.screenpipe_importer.worker import ScreenpipeImportWorker

    repo = JournalRepository(":memory:")
    worker = ScreenpipeImportWorker(_Client(_records(count)), repo)
    t0 = time.perf_counter()
    imported = asyncio.run(worker.import_page(limit=limit))
    elapsed = time.perf_counter() - t0
    return {
        "records": count,
        "imported": imported,
        "elapsed_s": round(elapsed, 4),
        "records_per_s": round(imported / elapsed, 1) if elapsed else None,
    }


def measure_command_dispatch(iterations: int) -> dict:
    from lva.contracts.commands import CommandEnvelope, RuntimeSetModePayload
    from lva.contracts.enums import Mode
    from lva.core.runtime import RuntimeController

    rt = RuntimeController()
    samples_ms: list[float] = []
    for i in range(iterations):
        mode = Mode.LIVE if i % 2 == 0 else Mode.STANDBY
        cmd = CommandEnvelope(
            type="runtime.set_mode",
            payload=RuntimeSetModePayload(type="runtime.set_mode", mode=mode),
        )
        t0 = time.perf_counter()
        rt.execute_command(cmd)
        samples_ms.append((time.perf_counter() - t0) * 1000.0)
    samples_ms.sort()

    def pct(p):
        idx = min(len(samples_ms) - 1, int(round(p / 100.0 * (len(samples_ms) - 1))))
        return round(samples_ms[idx], 4)

    return {
        "iterations": iterations,
        "p50_ms": pct(50),
        "p95_ms": pct(95),
        "p99_ms": pct(99),
        "mean_ms": round(statistics.fmean(samples_ms), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=2000)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--iterations", type=int, default=2000)
    args = parser.parse_args()

    result = {
        "schema": "lva-t08-codeable/1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "import": measure_import(args.records, args.limit),
        "command_dispatch": measure_command_dispatch(args.iterations),
        "not_measured": [
            "simulated_speech_onset_to_silence",
            "physical_onset_to_acoustic_silence",
            "audio_callback_duration",
            "standby_cpu",
            "rss_12h",
            "vram_peak_gb",
        ],
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
