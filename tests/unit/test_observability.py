"""Unit tests for Observability and Redaction per Part 4.5, Part 8.4, and Invariant I20.

Verifies:
1. redact_string masks API keys (sk-...), Bearer tokens, and user home directory paths.
2. redact_dict recursively removes sensitive keys and values from nested structures.
3. export_redacted_diagnostics exports a clean support bundle with zero secret leaks.
"""
from __future__ import annotations

from lva.core.runtime import RuntimeController
from lva.journal.repository import JournalRepository
from lva.observability.diagnostics import export_redacted_diagnostics
from lva.observability.redact import redact_dict, redact_string


def test_redact_string():
    """Verify string redaction of API keys, bearer tokens, and user home paths."""
    # 1. API key redaction
    s1 = "Connecting to OpenAI with key sk-1234567890abcdef12345678"
    assert redact_string(s1) == "Connecting to OpenAI with key sk-[REDACTED]"

    # 2. Bearer token redaction
    s2 = "Authorization: Bearer my-secret-token.123"
    assert redact_string(s2) == "Authorization: Bearer [REDACTED]"

    # 3. Windows user profile path redaction
    s3 = r"Log file stored at C:\Users\alice\AppData\Local\LocalVoiceAgent\data.db"
    assert redact_string(s3) == r"Log file stored at <REDACTED_PATH>"

    # 4. Unix user profile path redaction
    s4 = "/home/developer/.config/lva/settings.json"
    assert "<REDACTED_PATH>" == redact_string(s4)


def test_redact_dict():
    """Verify recursive dictionary redaction of sensitive keys and values."""
    payload = {
        "service": "llama.cpp-hub",
        "api_key": "sk-secret12345678",
        "token": "bearer-token-val",
        "nested": {
            "password": "super-secret-pass",
            "normal_field": "public_data",
            "path": r"C:\Users\john\project\file.txt",
        },
        "items": [
            {"user_text": "Sensitive user utterance"},
            {"count": 42},
        ],
    }

    redacted = redact_dict(payload)

    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["token"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["normal_field"] == "public_data"
    assert redacted["nested"]["path"] == "<REDACTED_PATH>"
    assert redacted["items"][0]["user_text"] == "[REDACTED]"
    assert redacted["items"][1]["count"] == 42


def test_export_redacted_diagnostics():
    """Verify export_redacted_diagnostics bundle contains no secrets or user transcripts."""
    repo = JournalRepository()
    rt = RuntimeController(journal=repo)

    # Add an event with user text
    repo.append_event("ev-1", "我的银行卡密码是123456", occurred_at_utc_us=1000000)

    bundle = export_redacted_diagnostics(rt, repo)

    bundle_str = str(bundle)
    assert "银行卡密码" not in bundle_str
    assert "sk-" not in bundle_str
    assert "password" not in bundle_str
    assert bundle["schema_version"] == "1.0"
    assert bundle["journal_summary"]["events_count"] == 1
    assert bundle["journal_summary"]["integrity_check"] == "ok"
