"""R40 T02 — `stop-all.ps1` must refuse a PID it cannot still identify (I04/I16).

The script's process-identity logic is already implemented; this proves the
behaviour by *executing* it against a fixture `pids.json`, rather than searching
its source text.  A recorded PID whose process is no longer the expected service
must not be stopped.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from harness import REPO_ROOT

pytestmark = pytest.mark.red_v121

SCRIPT = REPO_ROOT / "scripts" / "stop-all.ps1"
POWERSHELL = "powershell"


def _run_stop_all(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-Root",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_reused_pid_is_refused_not_stopped(tmp_path):
    """A recorded PID now owned by an unrelated process must not be stopped.

    PID 4 (System) is always alive and is never the expected `python` service, so
    it stands in for a recycled PID.  A correct guard refuses it: the process is
    never a stop target, and the run stays safe.
    """
    root = tmp_path
    data = root / "data"
    data.mkdir()
    (data / "pids.json").write_text(
        json.dumps({"lva_core": 4}),
        encoding="utf-8",
    )

    proc = _run_stop_all(root)
    combined = (proc.stdout or "") + (proc.stderr or "")

    assert proc.returncode == 0, f"stop-all.ps1 failed to run: {combined}"
    assert "refusing to stop" in combined.lower() or "not the recorded" in combined.lower(), (
        "stop-all.ps1 did not report that it refused the reused PID; output: "
        f"{combined!r}"
    )


def test_stop_all_exposes_a_data_parameter_for_the_fixture():
    """The guard must be reachable without touching the user's real data dir."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "param(" in text, "stop-all.ps1 must take parameters"
    assert "Root" in text, (
        "stop-all.ps1 must accept a -Root path so the identity guard is testable "
        "against an isolated fixture"
    )
