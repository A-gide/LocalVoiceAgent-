"""CI test groups (v1.2.1 PR-022).

Defines the named test groups the frozen plan asks for, so CI and local runs use
exactly the same definitions. Groups are intentionally explicit rather than
"run everything", because the repository currently carries two layers:

* **v1.2 layer groups** - the shipped implementation's suites. These are green
  today and are what ``scripts/verify_release_gates.py`` executes.
* **v1.2.1 groups** - ``harness`` (instrument self-tests, must be green) and
  ``red-v121`` (gap reproductions, **expected to fail** until R03-R14 land).

Usage::

    .venv/Scripts/python tests/run_groups.py --list
    .venv/Scripts/python tests/run_groups.py contract invariants harness
    .venv/Scripts/python tests/run_groups.py --all
    .venv/Scripts/python tests/run_groups.py --layer v121  # harness + red-v121
    .venv/Scripts/python tests/run_groups.py --layer v12   # shipped suites

Exit code is 0 only when every selected group passed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Group:
    name: str
    layer: str          # "v12" | "v121"
    targets: tuple[str, ...]
    expect_green: bool  # False = RED by design until the owning slice lands
    slice: str          # owning fix slice
    description: str


GROUPS: tuple[Group, ...] = (
    Group("contract", "v12", ("tests/contract",), True, "PR-001", "JSON Schema + generated-artifact round-trip"),
    Group("invariants", "v12", ("tests/invariants",), True, "PR-009/010", "I01-I20 invariant matrix"),
    Group("unit", "v12", ("tests/unit",), True, "PR-001", "contracts, commands, effects, observability"),
    Group("fault", "v12", ("tests/fault",), True, "PR-022", "fault matrix"),
    Group("integration", "v12", ("tests/integration",), True, "PR-012/013", "Hub streaming, transport resilience, benchmarks"),
    Group("migration", "v12", ("tests/migration",), True, "PR-017", "legacy Journal migration"),
    Group("ux", "v12", ("tests/ux",), True, "PR-035", "UX gates and legacy-deletion convergence"),
    # The harness self-test lives beside the RED suite because it imports the
    # harness module from that directory. It is listed here as well so that the
    # "harness self-tests must stay green" acceptance line is actually enforced:
    # inside the red-v121 group a broken self-test would be masked by the
    # expected RED failures of the surrounding files.
    Group(
        "harness",
        "v121",
        ("tests/harness", "tests/red_v121/test_harness_selftest.py"),
        True,
        "PR-022",
        "instrument self-tests (WASAPI scaffold, redaction rig, CAS/turn probes)",
    ),
    Group("red-v121", "v121", ("tests/red_v121",), False, "R03-R14", "v1.2.1 gap reproductions (RED by design)"),
)

BY_NAME = {g.name: g for g in GROUPS}


def run_group(group: Group, extra: tuple[str, ...] = ()) -> tuple[bool, str, str]:
    cmd = [sys.executable, "-m", "pytest", *group.targets, "-q", "--no-header", "-p", "no:cacheprovider", *extra]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=3600)
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else "(no output)"
    if proc.returncode == 0:
        return True, summary, ""
    # A bare "....." progress line cannot be diagnosed, so a failing group keeps
    # the full captured output (stdout plus stderr) for the report.
    detail = "\n".join(
        part for part in ((proc.stdout or "").strip(), (proc.stderr or "").strip()) if part
    )
    return False, summary, detail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("groups", nargs="*", help="group names to run")
    ap.add_argument("--all", action="store_true", help="run every group")
    ap.add_argument("--layer", choices=("v12", "v121"), help="run every group in a layer")
    ap.add_argument("--list", action="store_true", help="list groups and exit")
    args = ap.parse_args(argv)

    if args.list:
        print(f"{'group':<14}{'layer':<7}{'expect':<8}{'slice':<10}description")
        for g in GROUPS:
            expect = "green" if g.expect_green else "RED"
            print(f"{g.name:<14}{g.layer:<7}{expect:<8}{g.slice:<10}{g.description}")
        return 0

    if args.all:
        selected = list(GROUPS)
    elif args.layer:
        selected = [g for g in GROUPS if g.layer == args.layer]
    elif args.groups:
        unknown = [n for n in args.groups if n not in BY_NAME]
        if unknown:
            print(f"unknown group(s): {unknown}", file=sys.stderr)
            return 2
        selected = [BY_NAME[n] for n in args.groups]
    else:
        ap.print_help()
        return 2

    print("=" * 72)
    print("  LocalVoiceAgent - CI test groups")
    print("=" * 72)
    failures: list[str] = []
    for g in selected:
        passed, summary, detail = run_group(g)
        verdict = "PASS" if passed else "FAIL"
        if passed != g.expect_green:
            verdict += " (UNEXPECTED)"
        print(f"[{verdict:<18}] {g.name:<12} {summary}")
        if detail:
            print(textwrap.indent(detail, "    | "))
        if not passed:
            failures.append(g.name)

    print("-" * 72)
    unexpected = [g.name for g in selected if (g.name in failures) == g.expect_green]
    if unexpected:
        print(f"UNEXPECTED results in: {unexpected}")
    print("expected-red groups failing:", [g.name for g in selected if not g.expect_green and g.name in failures])
    print("all groups passed" if not failures else f"failing groups: {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
