"""RED: real-Hub response shapes (R22).

These assertions came from running against the **actual** llama.cpp-hub
0.9.8.3 (the user started it; the sandbox cannot start the bundled JVM because
its `java.net.http.HttpClient` fails to create a loopback self-pipe).

Two real defects were found that every fixture-level test had missed:

1. `/api/sys/version` returns `{"success":true,"data":{"version":"0.9.8.3"}}` --
   the version is nested under `data`.  `probe_handshake()` read the top level,
   so a **perfectly healthy pinned Hub was classified DEGRADED**.
2. The fixture written for that endpoint did not match the real response, which
   is why the mis-parse survived: the fixture encoded the same wrong assumption.

Kept as guards so the shapes cannot silently drift back.
"""
from __future__ import annotations

import json

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "hub"


def test_version_fixture_matches_the_real_hub_envelope():
    """The pinned fixture must mirror the real response envelope.

    Real response (verified against Hub 0.9.8.3):
        {"success": true, "data": {"createdTime": ..., "tag": "v0.9.8.3",
         "version": "0.9.8.3"}}
    """
    data = json.loads(read_text(FIXTURES / "version_0_9_8_3.json"))
    assert "data" in data, (
        "the real /api/sys/version nests the payload under `data`; a fixture "
        "without it encodes the wrong shape and hides parser bugs"
    )
    assert data["data"].get("version") == "0.9.8.3"
    assert "version" not in data or data.get("version") is None, (
        "the fixture must not also carry a top-level `version`, or it would "
        "keep the wrong assumption alive"
    )


def test_handshake_reads_the_nested_version():
    """`probe_handshake` must look inside `data`, not only at the top level."""
    src = read_text(LVA / "providers" / "hub_control.py")
    assert "data" in src, (
        "the handshake must unwrap the `data` envelope; reading only the top "
        "level classifies a healthy pinned Hub as DEGRADED"
    )


def test_unknown_version_fixture_matches_the_same_envelope():
    data = json.loads(read_text(FIXTURES / "version_unknown.json"))
    assert "data" in data, "the unknown-version fixture must use the real envelope"
    assert data["data"].get("version") != "0.9.8.3"

