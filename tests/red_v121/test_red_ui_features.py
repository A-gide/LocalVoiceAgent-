"""RED: PR-027/028/029/032 UI feature acceptance (R33).

These four sections had skeletons but not the behaviour their acceptance lines
require.  Each assertion below quotes the plan line it comes from.

PR-027 (L1402-1410): mic test, ASR model/language/domain, voice/preview,
  advanced collapse, validation; "不支持能力不显示"; "试听可取消";
  "不改变默认 ASR/TTS engine".
PR-028 (L1412-1420): typed send, stream render, cancel, turn identity, history,
  advanced trace; "stale response 不渲染"; "Core restart 清理 pending";
  "Open Chat 一动作".
PR-029 (L1422-1430): pagination/search, raw/current/revisions/provenance/timezone,
  manual correction, audited delete; "raw 不可编辑"; "correction creates revision";
  "parse degraded state 可见".
PR-032 (L1452-1460): identity/readiness/retry, redacted event/latency/queue,
  support bundle export; "normal Services 无 PID/port/raw endpoint";
  "export 无 secret/transcript/path".
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

UI = REPO_ROOT / "apps" / "desktop-ui" / "src"
HEARING = UI / "features" / "settings" / "HearingSection.vue"
SPEECH = UI / "features" / "settings" / "SpeechSection.vue"
CHAT = UI / "features" / "chat" / "ChatView.vue"
CHAT_STORE = UI / "stores" / "chat.ts"
MEMORY = UI / "features" / "memory" / "MemoryView.vue"
MEMORY_STORE = UI / "stores" / "memory.ts"
SERVICES = UI / "features" / "services" / "ServicesView.vue"
DIAGNOSTICS = UI / "features" / "settings" / "DiagnosticsSection.vue"


def _read(path) -> str:
    assert path.exists(), path.name + " must exist"
    return read_text(path)


# =================================================================== PR-027
def test_hearing_offers_a_microphone_test():
    """L1404 Steps: mic test."""
    src = _read(HEARING)
    assert re.search(r"mic.*test|测试|试音|level", src, re.I), (
        "Hearing must offer a microphone test rather than only displaying values"
    )


def test_speech_offers_a_preview_that_can_be_cancelled():
    """L1404: voice/preview; L1408 acceptance: 试听可取消."""
    src = _read(SPEECH)
    assert re.search(r"preview|试听|试播", src, re.I), "Speech must offer a voice preview"
    assert re.search(r"cancel|取消|stop|停止", src, re.I), (
        "a preview that cannot be cancelled is the acceptance failure L1408 names"
    )


def test_unsupported_capabilities_are_not_rendered():
    """L1408 acceptance: 不支持能力不显示."""
    src = _read(HEARING) + _read(SPEECH)
    assert re.search(r"providers|capabilit|supports", src, re.I), (
        "Hearing/Speech must be driven by the reported provider capability, not "
        "by a hard-coded engine list"
    )


def test_hearing_speech_do_not_change_the_default_engines():
    """L1408 acceptance: 不改变默认 ASR/TTS engine."""
    blob = _read(HEARING) + _read(SPEECH)
    for forbidden in ("settings.update_public", "asr_provider", "tts_provider"):
        assert forbidden not in blob, (
            "a display section must not write " + repr(forbidden) + ": the default "
            "engines are not a Hearing/Speech setting (L1408)"
        )


def test_advanced_settings_are_collapsed():
    """L1404: advanced collapse."""
    src = _read(HEARING) + _read(SPEECH)
    assert re.search(r"advanced|高级|collapse|details", src, re.I), (
        "advanced options must be collapsible, not always expanded"
    )


# =================================================================== PR-028
def test_chat_send_is_a_typed_command():
    """L1414: typed send; L1416: typed command/event chat."""
    src = _read(CHAT_STORE)
    assert "turn.send_text" in src, "chat must send the typed command"


def test_stale_responses_are_not_rendered():
    """L1418 acceptance: stale response 不渲染."""
    src = _read(CHAT_STORE)
    assert re.search(r"activeTurn|turnId", src), (
        "chat must track the active turn identity so a stale response is dropped"
    )
    assert re.search(r"sequence", src), (
        "turn identity is the TurnId sequence; without it two turns cannot be told apart"
    )


def test_core_restart_clears_pending_state():
    """L1418 acceptance: Core restart 清理 pending."""
    src = _read(CHAT_STORE)
    assert re.search(r"reset|clear|runtime_instance_id|instanceId", src), (
        "a Core restart must clear pending/streaming state, or the UI keeps "
        "waiting for a turn that died with the previous Core"
    )


def test_chat_shows_turn_identity_and_history():
    """L1414: turn identity; history."""
    src = _read(CHAT)
    assert re.search(r"turn", src, re.I), "each message must carry its turn identity"
    assert re.search(r"messages", src), "the transcript must be rendered"


def test_chat_has_an_advanced_trace_panel():
    """L1414: advanced trace panel."""
    src = _read(CHAT)
    assert re.search(r"trace|诊断|diagnostic", src, re.I), (
        "the advanced trace panel must exist and be reachable"
    )


# =================================================================== PR-029
def test_memory_raw_text_is_not_editable():
    """L1426 acceptance: raw 不可编辑."""
    src = _read(MEMORY)
    assert "raw_text" in src, "the raw text must be displayed"
    for block in re.findall(r"raw_text[^>]*", src):
        assert "v-model" not in block, (
            "raw transcript is immutable (I06): it must never be bound to an input"
        )


def test_memory_correction_targets_the_current_revision():
    """L1426 acceptance: correction creates revision (CAS on current_revision)."""
    src = _read(MEMORY_STORE)
    assert "memory_event" in src, (
        "a correction must quote the event aggregate so a concurrent edit is refused"
    )
    assert re.search(r"revision", src), "the correction must carry the revision it saw"


def test_memory_shows_provenance_and_timezone():
    """L1424: raw/current/revisions/provenance/timezone."""
    src = _read(MEMORY) + _read(MEMORY_STORE)
    assert re.search(r"provenance|source", src, re.I), "provenance must be shown"
    assert re.search(r"timezone|时区|occurred_at", src, re.I), (
        "the event time and its timezone context must be shown"
    )


def test_memory_search_is_paginated():
    """L1424: pagination/search."""
    src = _read(MEMORY_STORE) + _read(MEMORY)
    assert re.search(r"limit", src), "the search must be bounded rather than unbounded"


def test_memory_delete_is_audited_and_confirmed():
    """L1424: audited delete confirmation."""
    src = _read(MEMORY) + _read(MEMORY_STORE)
    assert "memory.hard_delete" in src, "the audited delete command must be used"
    assert re.search(r"reason_code", src), "the delete must carry its audit reason code"
    assert re.search(r"confirm|确认", src, re.I), "the delete must be confirmed first"


def test_memory_parse_degraded_state_is_visible():
    """L1426 acceptance: parse degraded state 可见."""
    src = _read(MEMORY) + _read(MEMORY_STORE)
    assert re.search(r"degraded|unparsed|parse_failed|降级", src, re.I), (
        "a temporal expression the parser could not resolve must be visible rather "
        "than silently dropped"
    )


# =================================================================== PR-032
def test_normal_services_hide_pid_port_and_endpoint():
    """L1458 acceptance / L993: 普通 Services 不显示 PID、端口、raw endpoint."""
    src = _read(SERVICES)
    for token in ("svc.pid", "svc.port", "svc.endpoint", ".pid", ".port", ".endpoint"):
        assert token not in src, (
            "the normal Services view must not render " + repr(token) + "; those "
            "belong to Diagnostics only (plan L993)"
        )


def test_services_show_identity_readiness_and_retry():
    """L1454: identity/readiness/retry."""
    src = _read(SERVICES)
    assert re.search(r"state|状态", src), "readiness must be shown"
    assert re.search(r"service.retry", src), "a retry must be offered"


def test_diagnostics_exports_a_redacted_bundle():
    """L1454 / L1458: support bundle export with no secret/transcript/path."""
    src = _read(DIAGNOSTICS)
    assert "diagnostics.export_redacted" in src, "the redacted export command must be used"
    assert re.search(r"latency|queue|event", src, re.I), (
        "the diagnostics surface must show the redacted event/latency/queue data"
    )

