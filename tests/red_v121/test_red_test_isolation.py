"""RED: the attestation wiring test must not depend on suite ordering (R33).

`test_server_wiring_does_not_recurse` (test_red_bind_attestation.py) builds a
real `get_runtime()` against a temporary `LVA_ROOT`.  It sets that variable with
`os.environ.setdefault`, but `lva.config` resolves `ROOT` **once at import time**,
so when another test has already imported the module the assignment is a no-op
and the Journal is created at the repository root instead.  In this sandbox that
root is read-only, so the test fails with "unable to open database file" --
purely as a function of which directory ran first.

Observed: `pytest tests/invariants tests/red_v121/test_red_bind_attestation.py`
fails; `pytest tests/red_v121` alone passes.  A test whose result depends on the
order of unrelated suites cannot be evidence for anything.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

TEST_FILE = REPO_ROOT / "tests" / "red_v121" / "test_red_bind_attestation.py"
SETDEFAULT_PATTERN = r"setdefault\(\s*[" + chr(39) + chr(34) + r"]LVA_ROOT[" + chr(39) + chr(34) + r"]"


def test_the_wiring_test_does_not_rely_on_setdefault():
    """setdefault cannot redirect a module-level constant that is already bound."""
    src = read_text(TEST_FILE)
    assert re.search(SETDEFAULT_PATTERN, src) is None, (
        "LVA_ROOT is resolved once when lva.config is imported, so setdefault() "
        "silently does nothing whenever another suite imported it first; the test "
        "then writes to the repository root and fails by suite ordering"
    )


def test_the_wiring_test_pins_the_root_unconditionally():
    """The root must be forced, not defaulted."""
    src = read_text(TEST_FILE)
    assert re.search(r"os\.environ\[\s*[" + chr(39) + chr(34) + r"]LVA_ROOT[" + chr(39) + chr(34) + r"]\s*\]\s*=", src), (
        "the test must assign LVA_ROOT rather than defaulting it"
    )


def test_the_wiring_test_proves_where_the_journal_lands():
    """The failure was a Journal write to a read-only root, so the path must be shown."""
    src = read_text(TEST_FILE)
    assert "get_journal" in src or "DATA" in src, (
        "the test must show where the Journal is created, or the same "
        "read-only-root failure returns under a different ordering"
    )

