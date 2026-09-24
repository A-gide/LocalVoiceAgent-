"""Fixture + marker registration for the v1.2.1 RED suite.

The suite is mixed: R03b is closed, and later fix slices still have RED cases:

* R05 -> auth fail-closed
* R06 -> Core bootstrap + supervisor wiring
* R09 -> I22 conversation-entry unification
* R10 -> I21 Hub authority
* R13 -> Standby / managed capture
* R14 -> Output Mute

Run the v1.2.1 suite (remaining gaps are expected to fail):

    pytest tests/red_v121 -q

Run the v1.2 baseline that is currently green (RED suite excluded):

    pytest tests --ignore=tests/red_v121 -q

The release-gate runner keeps targeting the v1.2 layer directories, so G0-G8
are unaffected by this suite's RED state.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from harness import (  # noqa: E402
    ArtifactWriter,
    DeterministicClock,
    EventRecorder,
    FakeProviderSet,
)

# CI keeps the default upload path; constrained local runs may use a writable
# scratch directory without changing the artifact redaction path.
ARTIFACT_DIR = Path(os.environ.get("LVA_TEST_ARTIFACT_DIR", str(_HERE / "_artifacts")))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "red_v121: RED test reproducing a v1.2.1 gap (expected to fail until fixed)",
    )


@pytest.fixture
def clock() -> DeterministicClock:
    return DeterministicClock()


@pytest.fixture
def recorder() -> EventRecorder:
    return EventRecorder()


@pytest.fixture
def providers() -> FakeProviderSet:
    return FakeProviderSet()


@pytest.fixture
def artifacts() -> ArtifactWriter:
    return ArtifactWriter(ARTIFACT_DIR)


# ------------------------------------------------------- failure artifacts (I20)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    """On failure, persist a REDACTED artifact so a red result is diagnosable.

    The payload goes through ``ArtifactWriter``, which asserts that no token,
    absolute path or raw transcript reaches disk before writing.
    """
    if call.when != "call" or call.excinfo is None:
        return

    writer = ArtifactWriter(ARTIFACT_DIR)
    payload = {
        "test": item.nodeid,
        "phase": call.when,
        "exception_type": call.excinfo.typename,
        "message": str(call.excinfo.value),
        "source_file": str(item.fspath),
    }
    safe_name = item.nodeid.replace("/", "_").replace("\\", "_").replace("::", "__") + ".json"
    try:
        writer.write(safe_name, payload)
    except AssertionError:
        # Redaction could not guarantee safety: record the fact, never the payload.
        writer.write(
            safe_name,
            {"test": item.nodeid, "redaction": "UNSAFE_PAYLOAD_WITHHELD"},
        )
