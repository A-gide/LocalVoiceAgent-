"""RED: v1.2.1 PR-010 remainder -- turn orchestration belongs to Core (R13).

Frozen rule (L1228-1236, PR-010 ``Interrupt transaction, stale gates, unified ask``):

* `Current -> target`: interrupt / late effects / ``api/ask`` paths are not unified
  -> transactional cancel plus three gates.
* `Files/new`: ``core/interrupt.py``, ``core/effects.py``; modify ``pipeline.py`` / ``server.py``.
* `Tests / acceptance`: I01/I03/I05/**I22**; five consecutive barge-ins; old
  token/audio/history/memory all dropped; **``/api/ask`` and every compatibility
  entry only enter the dispatcher/TurnController**.

State when this file was written: R10 landed option (甲) -- ``/api/ask`` *opens* the
turn through ``turn.send_text`` -- but the provider/playback/journal orchestration
still lives inside the route body, so ``test_no_route_bypasses_the_command_dispatcher``
still reports ``ask() calls ['append_event', 'stream', 'synthesize']``.

This file covers the remainder: the orchestration moves into a Core-owned executor
and the route becomes a thin adapter.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
CORE = LVA / "core"
EXECUTOR = CORE / "turn_executor.py"
RUNTIME = CORE / "runtime.py"
SERVER = LVA / "server.py"


# ------------------------------------------------------------- Core ownership
def test_core_owns_a_turn_executor():
    assert EXECUTOR.is_file(), (
        "PR-010 remainder: the turn orchestration has no Core-side home. It still "
        "lives in `server.py`'s route body, which is exactly what I22 forbids."
    )
    src = read_text(EXECUTOR)
    assert re.search(r"class\s+TurnExecutor\b", src), (
        "the executor must be a named type so it can be injected and tested"
    )
    assert re.search(r"def\s+run_text_turn\b", src), (
        "the executor must expose the text-turn entry point the route delegates to"
    )


def test_executor_applies_the_stale_gates():
    """PR-010: the three gates are part of the transaction, not the caller's job."""
    src = read_text(EXECUTOR)
    assert "check_gate2_in_stream" in src, (
        "gate 2 (in-stream) must be applied inside the executor; if the caller has "
        "to remember it, a new entry point can silently skip it"
    )
    assert "check_gate3_pre_side_effect" in src, (
        "gate 3 (pre-side-effect) must guard the TTS and Journal effects inside "
        "the executor"
    )


def test_executor_owns_the_journal_commit_and_turn_completion():
    src = read_text(EXECUTOR)
    assert "append_event" in src, (
        "the Journal commit is a turn side effect and must happen in Core"
    )
    assert "complete_turn" in src, (
        "completing the turn is part of the same transaction"
    )


# ----------------------------------------------------------------- injection
def test_runtime_accepts_an_injected_turn_executor():
    """Core reaches the executor by injection, not by importing the pipeline."""
    src = read_text(RUNTIME)
    assert "turn_executor" in src, (
        "RuntimeController must accept a turn executor so the route can delegate "
        "without the Core importing concrete clients"
    )


def test_core_does_not_import_concrete_clients():
    """The decoupling that made option (乙) non-trivial must be preserved."""
    offenders: list[str] = []
    for path in CORE.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        src = read_text(path)
        for bad in ("import llm", "from .. import llm", "import tts", "from .. import tts"):
            if bad in src:
                offenders.append(f"{path.name}: {bad}")
    assert not offenders, (
        "Core must stay free of concrete provider/pipeline imports; the executor "
        f"receives narrow callables instead. Found: {offenders}"
    )


# ------------------------------------------------------------- route is thin
def test_ask_route_delegates_instead_of_orchestrating():
    """The route may call the dispatcher and the executor -- nothing else."""
    src = read_text(SERVER)
    match = re.search(
        r'@app\.post\("/api/ask"\)\s*\nasync def ask\(.*?\n(?=@app\.)', src, re.S
    )
    assert match, "the ask route must be present"
    body = match.group(0)
    for forbidden in ("append_event", "LLM.stream", ".synthesize("):
        assert forbidden not in body, (
            f"PR-010 remainder: the ask route still performs `{forbidden}` directly; "
            "the orchestration belongs to the Core-side executor"
        )
    assert "execute_command" in body, (
        "the route must still enter the dispatcher (I22 entry rule)"
    )


def test_server_constructs_the_executor():
    src = read_text(SERVER)
    assert "TurnExecutor(" in src, (
        "something in production must build the executor, otherwise it is dead code"
    )
