"""RED: PR-014 dispatch/commit wiring defects found by source audit (R23).

A source-level audit of the saga wiring found that the Hub control commands
return success without doing anything.  All ten findings below were verified
against the source before this file was written.

B1 (high): `hub.bind_model` / `hub.sleep_bound_model` reach the saga branch and
  return `{"status": "delegated_to_saga"}` -- but nothing is delegated.
  `execute_command` is synchronous while `switch_model` is async, and there is no
  caller.  So the command reports `applied` and the model never switches.
  Same shape as the 8089 defect: the tests call `switch_model` directly, so the
  dispatch path was never exercised.
B2 (high): the saga COMMIT step never calls `inference.bind_model()`, so
  `bound_model_id` stays None and the `X-LVA-Bound-Model` header is never sent --
  the anti-misrouting guard the module documents never takes effect.
B4 (medium): verification uses substring matching (`target in m`) while conflict
  resolution uses exact set membership, so `qwen3-4b` would be accepted when only
  `qwen3-4b-instruct` is loaded.
B8 (low): a dead `if False:` block remains in the dispatcher.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
RUNTIME = LVA / "core" / "runtime.py"
SAGA = LVA / "providers" / "hub_runtime.py"
SERVER = LVA / "server.py"


# ===================================================== B1: the dispatch is dead
def test_hub_control_commands_actually_reach_the_saga():
    """`delegated_to_saga` must mean the saga is really invoked.

    The scheduling itself lives in a helper (a synchronous dispatcher cannot await
    an async saga), so this asserts the branch *calls* that helper rather than
    merely reporting success.
    """
    src = read_text(RUNTIME)
    block = re.search(
        r"if self\._hub_saga is not None:(.*?)(?=\n            if c_type)",
        src,
        re.S,
    )
    assert block, "the saga branch must exist"
    body = block.group(1)
    assert re.search(r"_schedule_hub_saga\s*\(", body), (
        "the saga branch returns `delegated_to_saga` without ever invoking the "
        "saga; `execute_command` is synchronous and `switch_model` is async, so "
        "the model switch never happens"
    )


def test_the_scheduler_actually_creates_a_task():
    """The helper must schedule the coroutine, not just claim it did."""
    src = read_text(RUNTIME)
    block = re.search(r"def _schedule_hub_saga(.*?)\n    def ", src, re.S)
    assert block, "the scheduler helper must exist"
    body = block.group(1)
    assert re.search(r"create_task|ensure_future|run_coroutine_threadsafe", body), (
        "the helper must hand the coroutine to an event loop"
    )
    assert "get_running_loop" in body, (
        "the helper must require a running loop, so a synchronous caller is told "
        "the command could not be scheduled instead of getting a false success"
    )


def test_saga_has_an_invocation_helper():
    """A synchronous dispatcher needs a way to hand work to the async saga."""
    src = read_text(RUNTIME)
    assert re.search(r"def\s+\w*(dispatch|schedule|invoke)\w*hub\w*|def\s+\w*hub\w*(dispatch|schedule)", src, re.I), (
        "there must be an explicit hand-off from the synchronous dispatcher to "
        "the asynchronous saga"
    )


# ================================================ B2: commit must bind inference
def test_commit_step_binds_the_inference_client():
    """The COMMIT step must pin the model on the inference client."""
    src = read_text(SAGA)
    assert re.search(r"\.inference\.bind_model\(", src), (
        "the saga commits the binding without calling `inference.bind_model()`, "
        "so `bound_model_id` stays None and the X-LVA-Bound-Model header is never "
        "sent -- the documented anti-misrouting guard never takes effect"
    )


# ============================================ B4: verification must be exact
def test_verification_uses_exact_model_identity():
    """Substring matching accepts a different model that merely contains the id."""
    src = read_text(SAGA)
    substring = re.search(r"any\(\s*target_model_id\s+in\s+m", src)
    assert not substring, (
        "verification uses substring matching while conflict resolution uses "
        "exact set membership; `qwen3-4b` would pass while only "
        "`qwen3-4b-instruct` is loaded"
    )


# ==================================================== B3: the api key is wired
def test_server_passes_the_hub_api_key():
    """The real Hub enforces an API key; the clients must receive it."""
    src = read_text(SERVER)
    assert "api_key=" in src, (
        "server.py constructs the Hub clients without an API key, so every "
        "management request would 401 against a Hub with apiKeyEnabled"
    )


# ================================================== B8: no dead code remains
def test_dispatcher_has_no_dead_code_block():
    src = read_text(RUNTIME)
    assert "if False:" not in src, (
        "a dead `if False:` block remains in the dispatcher; it should be "
        "deleted rather than disabled"
    )


# ============================================== B6: no deprecated event loop API
def test_saga_uses_the_running_loop_not_the_deprecated_api():
    src = read_text(SAGA)
    # Check for an actual *call*, not a comment explaining why it was removed.
    assert not re.search(r"(?<!`)\bget_event_loop\(\)", src), (
        "`asyncio.get_event_loop()` is deprecated; use `get_running_loop()` or a "
        "monotonic clock"
    )
