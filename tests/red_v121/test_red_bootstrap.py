"""RED: v1.2.1 Core bootstrap handshake + supervisor wiring (feeds R06).

Frozen rules (v1.2.1 §2.3 + PR-006/PR-007 acceptance):
* Tauri spawns ``python -m lva serve --bootstrap``, writes the bootstrap JSON to
  the child's stdin and immediately closes the write side.
* Core binds ``127.0.0.1:0`` and prints exactly one ``LVA_READY {...}`` line.
* Rust actually calls ``CoreSupervisor::spawn_core`` and
  ``CoreBridge::set_instance``.

Current state: ``__main__.py`` calls ``config.bind_sockets()`` which does not
exist in uvicorn 0.53.0 (only ``bind_socket``), so the handshake crashes before
emitting readiness; and neither ``spawn_core`` nor ``set_instance`` has a caller.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

MAIN = REPO_ROOT / "src" / "lva" / "__main__.py"
LIB_RS = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src" / "lib.rs"
CORE_SUP_RS = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src" / "core_supervisor.rs"
BRIDGE_RS = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src" / "bridge.rs"
SERVICES_DEFAULT = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "services.default.json"


# --------------------------------------------------------------- real handshake
def test_bootstrap_emits_lva_ready_line():
    """Drive the real handshake: stdin bootstrap JSON -> stdout LVA_READY."""
    payload = {
        "protocol_version": 1,
        "token": "red-suite-token-not-a-real-credential",
        "nonce": "red-suite-nonce",
        "parent_pid": os.getpid(),
    }
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")

    proc = subprocess.Popen(
        [sys.executable, "-m", "lva", "serve", "--bootstrap"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    try:
        try:
            out, err = proc.communicate(input=json.dumps(payload) + "\n", timeout=25)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            pytest.fail("bootstrap handshake timed out without emitting LVA_READY")
    finally:
        if proc.poll() is None:
            proc.kill()

    assert "LVA_READY" in out, (
        "Core must print a machine-readable readiness line on stdout; "
        f"exit={proc.returncode} stdout={out[:200]!r} stderr={err.strip().splitlines()[-3:] if err else []}"
    )

    line = next(l for l in out.splitlines() if l.startswith("LVA_READY"))
    body = json.loads(line[len("LVA_READY"):].strip())
    assert body["nonce"] == payload["nonce"], "readiness must echo the bootstrap nonce"
    assert body["protocol_version"] == 1
    assert isinstance(body["port"], int) and body["port"] > 0, "ephemeral port must be reported"
    assert body["port"] != 8765, "bootstrap must bind an ephemeral port, not the fixed dev port"


def test_bootstrap_does_not_use_nonexistent_uvicorn_api():
    src = read_text(MAIN)
    assert "bind_sockets()" not in src, (
        "uvicorn 0.53.0 exposes Config.bind_socket (singular); calling bind_sockets() "
        "raises AttributeError and aborts the bootstrap handshake"
    )


# ------------------------------------------------------------- rust wiring
def test_rust_calls_spawn_core():
    src = read_text(LIB_RS)
    assert "spawn_core(" in src, (
        "lib.rs never calls CoreSupervisor::spawn_core, so the Tauri shell never "
        "starts LVA Core (v1.2.1 PR-007)"
    )


def test_rust_registers_core_instance_with_bridge():
    src = read_text(LIB_RS)
    assert "set_instance(" in src, (
        "lib.rs never calls CoreBridge::set_instance, so every send_core_command "
        "fails with 'LVA Core is not running'"
    )


def test_core_supervisor_rejects_extra_readiness_lines():
    """v1.2.1 §2.3-8: extra readiness lines are a startup failure."""
    src = read_text(CORE_SUP_RS)
    assert "starts_with(\"LVA_READY\")" in src
    assert "extra" in src.lower() or "second" in src.lower(), (
        "core_supervisor.rs skips non-READY stdout lines instead of treating an "
        "unexpected extra readiness line as a startup failure (v1.2.1 §2.3-8)"
    )


def test_services_default_declares_correct_core_argv():
    cfg = json.loads(read_text(SERVICES_DEFAULT))
    core = cfg["services"]["lva_core"]
    args = core["args"]
    assert "serve" in args, (
        "services.default.json declares ['-m','lva','--bootstrap'], but the CLI "
        "requires the 'serve' subcommand; this invocation exits with code 2 "
        f"(actual args: {args})"
    )