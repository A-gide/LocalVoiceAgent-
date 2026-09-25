"""RED: B5 signal visibility + honest `hub.refresh` label (R24).

Reviewer verdict on B5: keep the semantics (loading does not require stopping the
old model) but stop hiding the conflict in a log line -- `MODEL_CONFLICT_REQUIRES
_CONFIRMATION` is otherwise a dead error code that no caller or UI can observe.

Also from the same review: `hub.refresh` is routed through the scheduler and comes
back labelled `delegated_to_saga`, but the scheduled coroutine does nothing for it.
The label overstates what happened.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
SAGA = LVA / "providers" / "hub_runtime.py"
RUNTIME = LVA / "core" / "runtime.py"


# ============================================ B5: the conflict must be visible
def test_conflict_is_recorded_not_only_logged():
    """The conflict code must reach the binding, not just the log."""
    src = read_text(SAGA)
    block = re.search(r"was preexisting/unknown; stopping requires confirmation", src)
    assert block, "the conflict branch must exist"

    # The branch must write the conflict somewhere observable.
    branch = src[block.start() - 600 : block.start() + 200]
    assert re.search(r"last_error\s*=|conflict|_record_", branch), (
        "the conflict is only logged; `MODEL_CONFLICT_REQUIRES_CONFIRMATION` is a "
        "dead code because no caller or UI can observe it"
    )


def test_conflict_survives_the_subsequent_status_updates():
    """A later `_update_status` must not wipe the recorded conflict.

    `_update_status` assigns `last_error` from its argument (defaulting to None),
    so a naive `last_error = ...` in the conflict branch would be cleared by the
    very next `_update_status("loading")`.
    """
    src = read_text(SAGA)
    assert "self._conflict" in src or "pending_conflict" in src or "keep_last_error" in src, (
        "the conflict needs its own field (or a carry-forward rule) or the next "
        "status update erases it"
    )


def test_conflict_does_not_block_the_load():
    """Reviewer ruling: semantics stay -- loading does not require stopping the old.

    The old model keeps its VRAM; that is intended.  Only visibility changes.
    """
    src = read_text(SAGA)
    # The conflict branch must not raise or return early.
    branch = re.search(
        r"was preexisting/unknown; stopping requires confirmation(.*?)\n\s*# Step 3",
        src,
        re.S,
    )
    assert branch, "the conflict branch must fall through to Step 3"
    assert "raise" not in branch.group(1), (
        "the conflict must not abort the load: plan 5.5 only requires confirmation "
        "for *stopping* a preexisting model, not for loading a new one"
    )


# ==================================== the scheduled label must match what happens
def test_refresh_is_not_labelled_as_delegated_when_nothing_is_delegated():
    """`hub.refresh` has no saga step, so the label must not claim one."""
    src = read_text(RUNTIME)
    block = re.search(r"def _schedule_hub_saga(.*?)\n    def ", src, re.S)
    assert block, "the scheduler must exist"
    body = block.group(1)
    assert "hub.refresh" in body, (
        "the scheduler must recognise `hub.refresh` explicitly instead of "
        "claiming it delegated work that does not exist"
    )

