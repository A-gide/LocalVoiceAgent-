"""Scaffold self-tests for the PR-022 harness (expected GREEN).

These exercise the hardware-free parts of the WASAPI loopback gate so that CI
can validate the measurement rig without an audio device. A green result here
means the *instrument* is trustworthy; it says nothing about the product.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.wasapi_loopback import (  # noqa: E402
    PEAK_CEILING_DBFS,
    RMS_CEILING_DBFS,
    SILENCE_WINDOW_MS,
    SyntheticRecorder,
    find_silence_onset,
    measure_noise_floor,
    peak,
    percentiles,
    rms,
    run_gate,
    silence_thresholds,
    to_dbfs,
)

SR = 48_000


# ------------------------------------------------------------------ dB math
def test_to_dbfs_reference_points():
    assert to_dbfs(1.0) == pytest.approx(0.0)
    assert to_dbfs(0.5) == pytest.approx(-6.0206, abs=1e-3)
    assert to_dbfs(0.0) == float("-inf")


def test_rms_and_peak():
    assert rms([1.0, -1.0, 1.0, -1.0]) == pytest.approx(1.0)
    assert rms([]) == 0.0
    assert peak([0.2, -0.9, 0.3]) == pytest.approx(0.9)


# ------------------------------------------------------------ frozen rule
def test_silence_thresholds_follow_frozen_rule():
    # noise floor high -> margin wins
    rms_limit, peak_limit = silence_thresholds(-50.0)
    assert rms_limit == pytest.approx(-44.0)
    assert peak_limit == PEAK_CEILING_DBFS == -45.0

    # noise floor very low -> the -60 dBFS absolute floor wins
    rms_limit2, _ = silence_thresholds(-90.0)
    assert rms_limit2 == pytest.approx(RMS_CEILING_DBFS) == -60.0


def test_find_silence_onset_locates_first_qualifying_window():
    # 1 s loud, then digital silence; T0 at 0
    loud = 0.5
    frames = [[loud, loud] for _ in range(SR // 2)] + [[0.0, 0.0] for _ in range(SR // 2)]
    onset = find_silence_onset(frames, SR, t0_frame=0, noise_floor_rms_dbfs=-90.0)
    assert onset is not None
    # the window must begin at/after the transition and be exactly one 50 ms window
    assert onset >= SR // 2
    assert onset - SR // 2 < int(SR * SILENCE_WINDOW_MS / 1000) + 1


def test_find_silence_onset_returns_none_when_never_silent():
    frames = [[0.5, 0.5] for _ in range(SR)]
    assert find_silence_onset(frames, SR, t0_frame=0, noise_floor_rms_dbfs=-90.0) is None


def test_silence_window_length_is_50ms():
    # a 40 ms silent gap must NOT qualify; a 60 ms gap must
    loud = 0.5
    short_gap = (
        [[loud, loud] for _ in range(1000)]
        + [[0.0, 0.0] for _ in range(int(SR * 0.040))]
        + [[loud, loud] for _ in range(1000)]
    )
    long_gap = (
        [[loud, loud] for _ in range(1000)]
        + [[0.0, 0.0] for _ in range(int(SR * 0.060))]
        + [[loud, loud] for _ in range(1000)]
    )
    assert find_silence_onset(short_gap, SR, 0, -90.0) is None
    assert find_silence_onset(long_gap, SR, 0, -90.0) is not None


def test_noise_floor_measurement():
    frames = [[1e-5, -1e-5] for _ in range(1000)]
    nf_rms, nf_peak = measure_noise_floor(frames)
    assert nf_rms < -90.0
    assert nf_peak < -90.0


# -------------------------------------------------------------- statistics
def test_percentiles_interpolate_positions():
    vals = [float(i) for i in range(1, 101)]
    p = percentiles(vals)
    assert p["p50"] == pytest.approx(50.0, abs=1.0)
    assert p["p95"] == pytest.approx(95.0, abs=1.0)
    assert p["p99"] == pytest.approx(99.0, abs=1.0)


def test_percentiles_empty_is_zero():
    assert percentiles([]) == {"p50": 0.0, "p95": 0.0, "p99": 0.0}


# ------------------------------------------------- end-to-end (synthetic)
def test_run_gate_end_to_end_with_synthetic_fixture():
    # playback for the first eighth, then silence
    t0 = SR // 8
    rec = SyntheticRecorder(sample_rate=SR, block_frames=1024, t0_frame=t0, loud_amplitude=0.5)
    result = run_gate(rec, samples=5, t0_frame=t0, playback_frames=SR // 4)
    assert result.status == "OK", result.reason
    assert result.samples == 5
    assert result.invalid == 0
    assert result.playback_trials == 5
    summary = result.summary()
    assert summary["analysis_version"]
    assert summary["thresholds"]["peak_ceiling_dbfs"] == -45.0
    assert "software WASAPI loopback gate" in summary["protocol"]
    assert summary["environment"]["sample_rate"] == SR


def test_run_gate_reports_no_silence_when_playback_never_stops():
    # loud both before and after T0 => playback never becomes silent
    rec = SyntheticRecorder(sample_rate=SR, loud_amplitude=0.5, quiet_amplitude=0.5)
    result = run_gate(rec, samples=3, t0_frame=0, playback_frames=SR // 4)
    assert result.status == "NO_SILENCE_DETECTED"
    assert result.samples == 0
    assert result.invalid == 3
    assert result.playback_trials == 3


def test_run_gate_flags_missing_playback_instead_of_false_green():
    """No playback energy => the 0 ms result would be meaningless; must not be OK."""
    rec = SyntheticRecorder(sample_rate=SR, loud_amplitude=0.0, quiet_amplitude=0.0)
    result = run_gate(rec, samples=3, t0_frame=0, playback_frames=SR // 4)
    assert result.status == "NO_PLAYBACK_DETECTED"
    assert result.playback_trials == 0
    assert "meaningless" in result.reason
    assert result.summary()["thresholds"]["playback_floor_dbfs"] == -50.0


def test_summary_never_claims_physical_hearing():
    t0 = SR // 8
    rec = SyntheticRecorder(sample_rate=SR, t0_frame=t0, loud_amplitude=0.5)
    note = run_gate(rec, samples=1, t0_frame=t0, playback_frames=SR // 4).summary()["note"]
    assert "does NOT prove what a human hears" in note
    assert "protocol B" in note


# ------------------------------------------- hardware-absence degradation
def test_loopback_device_probe_returns_reason():
    from benchmarks.wasapi_loopback import loopback_device_available

    ok, why = loopback_device_available()
    assert isinstance(ok, bool)
    assert isinstance(why, str) and why, "the probe must always explain itself"


def test_main_writes_unavailable_report_when_no_device(monkeypatch, tmp_path):
    """A hardware-free host must yield a report + exit 1, never a crash."""
    import benchmarks.wasapi_loopback as wl

    monkeypatch.setattr(wl, "loopback_device_available", lambda: (False, "no device on this host"))
    report = tmp_path / "gate.json"
    rc = wl.main(["--samples", "1", "--report", str(report)])

    assert rc == 1, "UNAVAILABLE must not exit 0 (that would be a false green)"
    assert report.exists(), "a report must be written even when the device is missing"
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "UNAVAILABLE"
    assert "no device on this host" in payload["reason"]
    assert payload["thresholds"]["playback_floor_dbfs"] == -50.0


def test_main_reports_unavailable_when_capture_start_fails(monkeypatch, tmp_path):
    """Enumeration succeeds but opening the stream fails -> UNAVAILABLE, not a traceback."""
    import benchmarks.wasapi_loopback as wl

    monkeypatch.setattr(wl, "loopback_device_available", lambda: (True, "device present"))

    class Boom:
        def __init__(self, *a, **k):
            pass

        def open(self):
            raise OSError("device busy")

        def close(self):
            pass

    monkeypatch.setattr(wl, "WasapiLoopbackRecorder", Boom)
    report = tmp_path / "gate2.json"
    rc = wl.main(["--samples", "1", "--report", str(report)])

    assert rc == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "UNAVAILABLE"
    assert "device busy" in payload["reason"]


def test_synthetic_cli_guard_and_success_paths(tmp_path):
    """Hardware-free CI path, both branches of the guard."""
    import benchmarks.wasapi_loopback as wl

    # (a) no playback at all (t0=0 => the synthetic fixture is silent throughout)
    no_pb = tmp_path / "no_playback.json"
    rc = wl.main(["--synthetic", "--samples", "3", "--playback-frames", "4800",
                  "--t0-frame", "0", "--report", str(no_pb)])
    payload = json.loads(no_pb.read_text(encoding="utf-8"))
    assert rc == 1, "no playback => must not exit 0"
    assert payload["status"] == "NO_PLAYBACK_DETECTED"
    assert payload["playback_trials"] == 0

    # (b) playback for the first 600 frames, then silence => a real measurement
    ok = tmp_path / "ok.json"
    rc2 = wl.main(["--synthetic", "--samples", "3", "--playback-frames", "4800",
                   "--t0-frame", "600", "--report", str(ok)])
    payload2 = json.loads(ok.read_text(encoding="utf-8"))
    assert rc2 == 0, f"synthetic playback-then-silence must measure cleanly: {payload2}"
    assert payload2["status"] == "OK"
    assert payload2["playback_trials"] == 3
    assert payload2["samples"] == 3