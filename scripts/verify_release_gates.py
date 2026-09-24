"""Comprehensive Acceptance Gates Verification Runner (Part 14 / PR-035).

Verifies Gates G0 through G8 per ARCHITECTURE-PLAN-2026-09-v1.2-COMPOSITE.md.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_cmd(args: list[str], cwd: Path = REPO_ROOT) -> tuple[int, str]:
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        elapsed = time.perf_counter() - t0
        return proc.returncode, f"({elapsed:.2f}s) {proc.stdout}"
    except Exception as e:
        return 1, str(e)


def main() -> int:
    print("=" * 60)
    print("  LocalVoiceAgent — Release Gates Verification Suite (G0–G8) ")
    print("=" * 60)

    python_exe = REPO_ROOT / "venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        python_exe = Path(sys.executable)

    gates = [
        ("G0", "Contract & Schema Roundtrip", [str(python_exe), "-m", "pytest", "tests/contract"]),
        ("G1", "Secure IPC & Invariants Matrix (I01–I20)", [str(python_exe), "-m", "pytest", "tests/invariants"]),
        ("G2", "Single Core Turn & Fault Matrix", [str(python_exe), "-m", "pytest", "tests/fault", "tests/unit"]),
        ("G3", "Hub Streaming & Integration", [str(python_exe), "-m", "pytest", "tests/integration"]),
        ("G4", "Journal v2 & Legacy Migration", [str(python_exe), "-m", "pytest", "tests/migration"]),
        ("G5", "Privacy & UX Gates", [str(python_exe), "-m", "pytest", "tests/ux"]),
        ("G6", "Frontend Build & Live2D Embed (PR-023..PR-034)", ["npm.cmd", "run", "build"]),
        ("G7", "Soak Stability Gate (PR-035)", [str(python_exe), "scripts/soak.py", "--duration", "5", "--report", "release_soak_report.json"]),
        ("G8", "Legacy Deletion & Shell Convergence (PR-036..PR-038)", [str(python_exe), "-m", "pytest", "tests/ux/test_ux_gates.py", "-k", "LegacyDeletion"]),
    ]

    all_passed = True
    results = {}

    for gate_id, gate_name, cmd in gates:
        print(f"\n[{gate_id}] Verifying {gate_name}...")
        cwd = REPO_ROOT / "apps" / "desktop-ui" if gate_id == "G6" else REPO_ROOT
        code, out = run_cmd(cmd, cwd=cwd)
        status = "PASS" if code == 0 else "FAIL"
        results[gate_id] = {"name": gate_name, "status": status}
        if code != 0:
            all_passed = False
            print(f"  -> {gate_id} FAILED:\n{out[:500]}")
        else:
            print(f"  -> {gate_id} PASSED.")

    print("\n" + "=" * 60)
    print("  ACCEPTANCE GATES SUMMARY")
    print("=" * 60)
    for gate_id, info in results.items():
        print(f"  [{info['status']}] {gate_id}: {info['name']}")
    print("=" * 60)

    overall = "ALL GATES PASSED (G0–G8 GREEN)" if all_passed else "SOME GATES FAILED"
    print(f"\nFinal Verdict: {overall}\n")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
