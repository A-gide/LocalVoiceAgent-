"""RED: diagnostic redaction floor (I20 / v1.2.1 §4.5, §5.8).

Frozen rule:
* Error details and diagnostic exports must never contain a token, API key,
  full user text, an absolute personal path or raw audio.
* §5.8 additionally requires query/header/profile redaction for Hub logging.

Current state: ``lva.observability.redact`` is key-based and value-scans only a
few shapes. A DPAPI blob stored under a non-obvious key survives untouched, and
an absolute path is only partially masked (the tail is left intact).
"""
from __future__ import annotations

import json

import pytest

from lva.observability.redact import redact_dict

pytestmark = pytest.mark.red_v121


def test_redactor_scrubs_dpapi_blobs():
    blob = "dpapi:AQAAANCMnd8BFdERjHoAwE/Cl+sBAAAA" + "A" * 200
    out = json.dumps(redact_dict({"provider_state": blob}))
    assert "dpapi:" not in out, (
        "a DPAPI ciphertext stored under a non-sensitive key survives redaction; "
        "diagnostic exports must not carry credential material (v1.2.1 §4.5)"
    )


def test_redactor_removes_whole_absolute_paths():
    out = json.dumps(redact_dict({"where": r"C:\Users\alice\AppData\Local\VoiceAgent\logs"}))
    assert "AppData" not in out and "VoiceAgent" not in out, (
        "absolute path redaction only masks the user segment and leaves the rest "
        f"of the personal path intact: {out}"
    )


def test_redactor_scrubs_posix_home_paths_fully():
    out = json.dumps(redact_dict({"where": "/home/alice/secret/voice.log"}))
    assert "secret" not in out, (
        f"POSIX home path redaction leaves the trailing path intact: {out}"
    )


def test_redactor_handles_bearer_and_sk_tokens():
    out = json.dumps(
        redact_dict({"a": "Bearer abcdef123456", "b": "sk-abcdefghijklmnopqrstuvwxyz"})
    )
    assert "abcdef123456" not in out
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in out


def test_error_envelope_details_cannot_carry_a_path():
    """ErrorEnvelope.redacted_details must be safe by construction."""
    from lva.contracts.errors import ErrorEnvelope
    from lva.contracts.enums import ErrorCode
    from uuid import uuid4

    env = ErrorEnvelope(
        code=ErrorCode.JOURNAL_BUSY,
        message="busy",
        component="core.journal",
        correlation_id=uuid4(),
        redacted_details={"db": r"C:\Users\alice\AppData\Local\VoiceAgent\data\journal.sqlite3"},
    )
    dumped = json.dumps(env.model_dump(mode="json"))
    assert "alice" not in dumped, (
        "ErrorEnvelope.redacted_details accepted a personal absolute path; the "
        "contract must enforce redaction rather than trusting the caller"
    )