"""WASAPI loopback acoustic-silence gate — v1.2.1 §13.5 protocol A scaffold.

This is the **software gate** half of the frozen acoustic measurement protocol.
It is deliberately separate from protocol B (the physical dual-channel
benchmark), which requires a target device, a reference microphone and a real
speaker, and therefore cannot run in CI.

Protocol A (frozen, verbatim requirements):

1. The production playback path plays a fixed calibration/voice fixture while a
   deterministic input fixture injects the barge-in onset at ``T0``.
2. Capture the PCM actually sent to the output device via Windows **WASAPI
   loopback** - never the player's internal queue.
3. Measure the device/format loopback noise floor first; ``silence`` is the
   first contiguous 50 ms window whose RMS is below
   ``max(noise_floor + 6 dB, -60 dBFS)`` and whose peak is below ``-45 dBFS``.
4. ``T_silence - T0`` is one sample; at least 200 samples, reporting
   P50/P95/P99, invalid count, audio device, sample rate, buffer size and the
   analysis-script version.

Design notes
------------
* The pure signal math (dB conversion, noise floor, silence onset, percentiles)
  is hardware-free and unit-tested by ``tests/red_v121/test_wasapi_scaffold.py``.
* Capture sits behind the :class:`Recorder` protocol so tests inject synthetic
  PCM and CI never needs an audio device.
* ``soundcard`` is an **optional** benchmark dependency; if it is missing the
  scaffold reports ``UNAVAILABLE`` with the reason instead of pretending to
  measure anything.

Usage::

    python benchmarks/wasapi_loopback.py --samples 200 --report wasapi-gate.json
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

ANALYSIS_VERSION = "wasapi-loopback-gate/1.0.0"

# --- frozen thresholds (v1.2.1 §13.5 A.3) -----------------------------------
SILENCE_WINDOW_MS = 50.0
NOISE_FLOOR_MARGIN_DB = 6.0
RMS_CEILING_DBFS = -60.0
PEAK_CEILING_DBFS = -45.0

# Below this peak level the loopback carries no meaningful playback energy, so a
# "silence from frame 0" result would be an artefact rather than a measurement.
PLAYBACK_FLOOR_DBFS = -50.0

DEFAULT_SAMPLE_RATE = 48_000
DEFAULT_BLOCK_FRAMES = 1024


# --------------------------------------------------------------------- math
def to_dbfs(amplitude: float) -> float:
    """Convert a linear amplitude (0..1) to dBFS. Zero maps to -inf."""
    if amplitude <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(amplitude)


def rms(samples: Sequence[float]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(float(s) * float(s) for s in samples) / len(samples))


def peak(samples: Sequence[float]) -> float:
    if not samples:
        return 0.0
    return max(abs(float(s)) for s in samples)


def measure_noise_floor(frames: Sequence[Sequence[float]]) -> tuple[float, float]:
    """Return (rms_dbfs, peak_dbfs) of the loopback noise floor."""
    flat = [s for frame in frames for s in frame]
    return to_dbfs(rms(flat)), to_dbfs(peak(flat))


def silence_thresholds(noise_floor_rms_dbfs: float) -> tuple[float, float]:
    """Frozen rule: RMS < max(noise_floor + 6 dB, -60 dBFS) and peak < -45 dBFS."""
    return max(noise_floor_rms_dbfs + NOISE_FLOOR_MARGIN_DB, RMS_CEILING_DBFS), PEAK_CEILING_DBFS


def find_silence_onset(
    frames: Sequence[Sequence[float]],
    sample_rate: int,
    t0_frame: int,
    noise_floor_rms_dbfs: float,
    window_ms: float = SILENCE_WINDOW_MS,
) -> int | None:
    """Frame index where playback first counts as acoustically silent.

    Returns the index of the first frame of the first qualifying window, or
    ``None`` if no window qualifies. Windows start at or after ``t0_frame``.
    """
    win = max(1, int(round(sample_rate * window_ms / 1000.0)))
    rms_limit, peak_limit = silence_thresholds(noise_floor_rms_dbfs)
    n = len(frames)
    start = max(0, t0_frame)
    while start + win <= n:
        block = frames[start : start + win]
        flat = [s for frame in block for s in frame]
        if to_dbfs(rms(flat)) < rms_limit and to_dbfs(peak(flat)) < peak_limit:
            return start
        start += 1
    return None


def percentiles(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    ordered = sorted(values)

    def pick(q: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
        return ordered[idx]

    return {"p50": pick(0.50), "p95": pick(0.95), "p99": pick(0.99)}


# ----------------------------------------------------------------- recorder
class Recorder(Protocol):
    """Minimal loopback capture surface (real device or synthetic fixture)."""

    sample_rate: int
    block_frames: int
    device_name: str

    def capture(self, num_frames: int) -> list[list[float]]:
        ...


@dataclass
class SyntheticRecorder:
    """Deterministic recorder for tests: loud until ``t0``, silent after."""

    sample_rate: int = DEFAULT_SAMPLE_RATE
    block_frames: int = DEFAULT_BLOCK_FRAMES
    device_name: str = "synthetic"
    loud_amplitude: float = 0.5
    quiet_amplitude: float = 0.0
    t0_frame: int = 0

    def capture(self, num_frames: int) -> list[list[float]]:
        out = []
        for i in range(num_frames):
            a = self.loud_amplitude if i < self.t0_frame else self.quiet_amplitude
            out.append([a, a])
        return out


@dataclass
class WasapiLoopbackRecorder:
    """Real WASAPI loopback capture via the optional ``soundcard`` package."""

    sample_rate: int = DEFAULT_SAMPLE_RATE
    block_frames: int = DEFAULT_BLOCK_FRAMES
    device_name: str = ""

    _mic: Any = None
    _ctx: Any = None
    _rec: Any = None

    def open(self) -> None:
        import soundcard as sc  # optional dependency

        speaker = sc.default_speaker()
        mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        self._mic = mic
        self.device_name = getattr(mic, "name", str(speaker.name))
        self._ctx = mic.recorder(samplerate=self.sample_rate)
        self._rec = self._ctx.__enter__()

    def close(self) -> None:
        if self._ctx is not None:
            try:
                self._ctx.__exit__(None, None, None)
            finally:
                self._ctx = None
                self._rec = None

    def capture(self, num_frames: int) -> list[list[float]]:
        if self._rec is None:
            raise RuntimeError("recorder not open")
        data = self._rec.record(numframes=num_frames)
        return [[float(x) for x in frame] for frame in data]


def soundcard_available() -> tuple[bool, str]:
    try:
        import soundcard  # noqa: F401

        return True, "soundcard importable"
    except Exception as exc:  # pragma: no cover - environment dependent
        return False, f"soundcard unavailable: {type(exc).__name__}: {exc}"


def loopback_device_available() -> tuple[bool, str]:
    """Report whether a WASAPI loopback endpoint exists at all.

    A hosted CI runner typically has no audio endpoint. That must surface as
    ``UNAVAILABLE`` with a reason - never as an unexplained crash or a missing
    report file.
    """
    ok, why = soundcard_available()
    if not ok:
        return False, why
    try:
        import soundcard as sc

        mics = sc.all_microphones(include_loopback=True)
        loopbacks = [m for m in mics if getattr(m, "isloopback", False)]
        if not loopbacks:
            return False, "no WASAPI loopback endpoint present on this host"
        return True, f"{len(loopbacks)} loopback endpoint(s) available"
    except Exception as exc:
        return False, f"loopback enumeration failed: {type(exc).__name__}: {exc}"


# ------------------------------------------------------------------- harness
@dataclass
class GateResult:
    status: str
    reason: str = ""
    samples: int = 0
    invalid: int = 0
    playback_trials: int = 0
    latency_ms: list[float] = field(default_factory=list)
    noise_floor_rms_dbfs: float = float("nan")
    noise_floor_peak_dbfs: float = float("nan")
    thresholds: dict[str, float] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        pct = percentiles(self.latency_ms)
        return {
            "analysis_version": ANALYSIS_VERSION,
            "status": self.status,
            "reason": self.reason,
            "protocol": "A (software WASAPI loopback gate)",
            "samples": self.samples,
            "invalid": self.invalid,
            "playback_trials": self.playback_trials,
            "latency_ms": {
                "p50": round(pct["p50"], 3),
                "p95": round(pct["p95"], 3),
                "p99": round(pct["p99"], 3),
                "min": round(min(self.latency_ms), 3) if self.latency_ms else None,
                "max": round(max(self.latency_ms), 3) if self.latency_ms else None,
            },
            "noise_floor": {
                "rms_dbfs": round(self.noise_floor_rms_dbfs, 2)
                if math.isfinite(self.noise_floor_rms_dbfs)
                else None,
                "peak_dbfs": round(self.noise_floor_peak_dbfs, 2)
                if math.isfinite(self.noise_floor_peak_dbfs)
                else None,
            },
            "thresholds": self.thresholds,
            "environment": self.environment,
            "note": (
                "protocol A measures PCM delivered to the output device via WASAPI loopback; "
                "it does NOT prove what a human hears. The physical dual-channel benchmark "
                "(protocol B) is required before G8 and is not run here."
            ),
        }


def environment_snapshot(recorder: Recorder | None) -> dict[str, Any]:
    """Record the environment the frozen protocol requires."""
    env: dict[str, Any] = {
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "analysis_version": ANALYSIS_VERSION,
        "cpu_count": getattr(__import__("os"), "cpu_count")(),
    }
    if recorder is not None:
        env.update(
            {
                "audio_device": recorder.device_name,
                "sample_rate": recorder.sample_rate,
                "block_frames": recorder.block_frames,
            }
        )
    # Tauri / WebView2 / GPU / DPI / HDR are recorded when obtainable; absent
    # keys mean "not measured", never "passed".
    try:
        import subprocess

        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-ItemProperty 'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\"
             "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}').pv"],
            capture_output=True, text=True, timeout=20,
        )
        if out.returncode == 0 and out.stdout.strip():
            env["webview2_runtime"] = out.stdout.strip()
    except Exception:
        env["webview2_runtime"] = "NOT MEASURED"
    env.setdefault("tauri_version", "NOT MEASURED")
    env.setdefault("gpu_driver", "NOT MEASURED")
    env.setdefault("dpi_scale", "NOT MEASURED")
    env.setdefault("hdr", "NOT MEASURED")
    return env


def run_gate(
    recorder: Recorder,
    samples: int,
    t0_frame: int,
    playback_frames: int,
    playback_floor_dbfs: float = PLAYBACK_FLOOR_DBFS,
) -> GateResult:
    """Run ``samples`` trials and report latency statistics.

    Guards against a meaningless green: if the loopback never carries any
    playback energy above ``playback_floor_dbfs``, the gate reports
    ``NO_PLAYBACK_DETECTED`` instead of a trivial 0 ms "OK". Protocol A is only
    meaningful when the production playback path is actually driving the device.
    """
    env = environment_snapshot(recorder)

    # 1. noise floor, measured before anything is played
    nf_frames = recorder.capture(max(recorder.sample_rate // 10, 1))
    nf_rms_db, nf_peak_db = measure_noise_floor(nf_frames)

    result = GateResult(
        status="OK",
        noise_floor_rms_dbfs=nf_rms_db,
        noise_floor_peak_dbfs=nf_peak_db,
        thresholds={
            "silence_window_ms": SILENCE_WINDOW_MS,
            "rms_ceiling_dbfs": max(nf_rms_db + NOISE_FLOOR_MARGIN_DB, RMS_CEILING_DBFS),
            "peak_ceiling_dbfs": PEAK_CEILING_DBFS,
            "playback_floor_dbfs": playback_floor_dbfs,
        },
        environment=env,
    )

    playback_seen = 0
    for _ in range(samples):
        frames = recorder.capture(playback_frames)
        if to_dbfs(peak([s for frame in frames for s in frame])) >= playback_floor_dbfs:
            playback_seen += 1
        idx = find_silence_onset(frames, recorder.sample_rate, t0_frame, nf_rms_db)
        if idx is None:
            result.invalid += 1
            continue
        result.latency_ms.append((idx - t0_frame) / recorder.sample_rate * 1000.0)

    result.samples = len(result.latency_ms)
    result.playback_trials = playback_seen

    if playback_seen == 0:
        result.status = "NO_PLAYBACK_DETECTED"
        result.reason = (
            "loopback captured no energy above the playback floor "
            f"({playback_floor_dbfs} dBFS); protocol A needs the production playback "
            "path to drive the device. A 0 ms result here would be meaningless."
        )
        return result

    if result.samples == 0:
        result.status = "NO_SILENCE_DETECTED"
        result.reason = (
            "no trial produced a qualifying 50 ms silence window; check that playback "
            "actually stopped and that the loopback device is the playback device"
        )
    return result


# ---------------------------------------------------------------------- main
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", type=int, default=200, help="trials (protocol requires >= 200)")
    ap.add_argument("--report", default="wasapi-gate.json")
    ap.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    ap.add_argument("--block-frames", type=int, default=DEFAULT_BLOCK_FRAMES)
    ap.add_argument("--playback-frames", type=int, default=DEFAULT_SAMPLE_RATE, help="frames per trial (1 s default)")
    ap.add_argument("--t0-frame", type=int, default=0)
    ap.add_argument("--synthetic", action="store_true", help="run against the synthetic fixture (no audio device)")
    args = ap.parse_args(argv)

    if args.synthetic:
        recorder: Recorder = SyntheticRecorder(
            sample_rate=args.sample_rate, block_frames=args.block_frames, t0_frame=args.t0_frame
        )
        result = run_gate(recorder, args.samples, args.t0_frame, args.playback_frames)
    else:
        ok, why = loopback_device_available()
        if not ok:
            # Hardware-free hosts (e.g. hosted CI runners) must produce a report
            # with an explicit UNAVAILABLE status, not a crash.
            result = GateResult(
                status="UNAVAILABLE",
                reason=why,
                environment=environment_snapshot(None),
                thresholds={
                    "silence_window_ms": SILENCE_WINDOW_MS,
                    "rms_ceiling_dbfs": RMS_CEILING_DBFS,
                    "peak_ceiling_dbfs": PEAK_CEILING_DBFS,
                    "playback_floor_dbfs": PLAYBACK_FLOOR_DBFS,
                },
            )
        else:
            rec = WasapiLoopbackRecorder(sample_rate=args.sample_rate, block_frames=args.block_frames)
            try:
                rec.open()
                time.sleep(0.2)
                result = run_gate(rec, args.samples, args.t0_frame, args.playback_frames)
            except Exception as exc:
                result = GateResult(
                    status="UNAVAILABLE",
                    reason=f"loopback capture could not start: {type(exc).__name__}: {exc}",
                    environment=environment_snapshot(None),
                    thresholds={
                        "silence_window_ms": SILENCE_WINDOW_MS,
                        "rms_ceiling_dbfs": RMS_CEILING_DBFS,
                        "peak_ceiling_dbfs": PEAK_CEILING_DBFS,
                        "playback_floor_dbfs": PLAYBACK_FLOOR_DBFS,
                    },
                )
            finally:
                try:
                    rec.close()
                except Exception:
                    pass

    payload = result.summary()
    Path(args.report).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("status", "samples", "invalid", "latency_ms")}, ensure_ascii=False, indent=2))
    print(f"report: {args.report}")
    return 0 if result.status == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())