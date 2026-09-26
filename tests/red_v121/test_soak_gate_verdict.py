"""Isolated soak gate test: a run whose mode commands are all rejected must FAIL.

Everything the soak writes is redirected into a temporary directory, so the
test never touches the repository's own `temp_soak_journal.sqlite3` or
`soak_report.json`.
"""
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

# soak writes these relative to its working directory, which is scripts/.
REPO_ARTIFACTS = [
    REPO / "scripts" / "temp_soak_journal.sqlite3",
    REPO / "scripts" / "soak_report.json",
]


def _run_soak(tmp_path: pathlib.Path, *, reject_all: bool) -> subprocess.CompletedProcess:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    db = sandbox / "soak.sqlite3"
    report = sandbox / "soak_report.json"

    shim = sandbox / "shim.py"
    shim.write_text(
        "import sys\n"
        f"sys.path.insert(0, r'{REPO / 'scripts'}')\n"
        "import soak\n"
        f"REJECT = {reject_all!r}\n"
        "if REJECT:\n"
        "    _orig = soak.RuntimeController.execute_command\n"
        "    def _reject(self, cmd):\n"
        "        # A genuinely rejected command: it is never dispatched, so it can\n"
        "        # have no effect on the runtime.\n"
        "        from lva.contracts.commands import CommandResult\n"
        "        from lva.contracts.errors import ErrorEnvelope\n"
        "        from lva.contracts.enums import ErrorCode\n"
        "        return CommandResult(\n"
        "            command_id=cmd.command_id, status='rejected',\n"
        "            snapshot_version=self.snapshot_version,\n"
        "            error=ErrorEnvelope(code=ErrorCode.STALE_REVISION, message='rejected',\n"
        "                                retryable=True, severity='warning',\n"
        "                                component='test', correlation_id=cmd.command_id),\n"
        "        )\n"
        "    soak.RuntimeController.execute_command = _reject\n"
        f"sys.argv = ['soak', '--duration', '2', '--db', r'{db}', '--report', r'{report}']\n"
        "sys.exit(soak.main())\n",
        encoding="utf-8",
    )

    env = {**os.environ, "PYTHONPATH": str(REPO / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, "-B", str(shim)],
        capture_output=True, text=True, cwd=str(sandbox), env=env,
    )


def test_soak_fails_when_every_mode_command_is_rejected(tmp_path):
    repo_artifacts = REPO_ARTIFACTS
    before = {p: (p.read_bytes() if p.exists() else None) for p in repo_artifacts}

    proc = _run_soak(tmp_path, reject_all=True)

    assert "SOAK TEST RESULT: FAIL" in proc.stdout, (
        f"soak reported PASS with every command rejected:\n{proc.stdout[-900:]}"
    )
    assert "Rejected Commands:" in proc.stdout

    after = {p: (p.read_bytes() if p.exists() else None) for p in repo_artifacts}
    assert before == after, (
        "the soak test must not touch the repository's own run artifacts"
    )


def test_soak_passes_when_commands_are_not_rejected(tmp_path):
    repo_artifacts = REPO_ARTIFACTS
    before = {p: (p.read_bytes() if p.exists() else None) for p in repo_artifacts}

    proc = _run_soak(tmp_path, reject_all=False)

    assert "SOAK TEST RESULT: PASS" in proc.stdout, proc.stdout[-900:]
    after = {p: (p.read_bytes() if p.exists() else None) for p in repo_artifacts}
    assert before == after