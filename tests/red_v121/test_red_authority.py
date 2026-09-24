"""RED: v1.2.1 authority invariants I21 and I22 (feeds R09 / R10).

I21 - "Hub lifecycle/control operation may only originate from LVA Core":
    Rust/TS must not carry Hub management clients or direct model lifecycle.
I22 - "Every user conversation entry goes through CommandDispatcher/TurnController":
    compatibility routes must only adapt into commands; they must not call
    providers, playback or Journal side effects directly.
"""
from __future__ import annotations

import pytest

from harness import (
    REPO_ROOT,
    conversation_bypasses,
    forbidden_endpoint_hits,
    iter_source_files,
    read_text,
    route_call_map,
)

pytestmark = pytest.mark.red_v121

LIB_RS = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src" / "lib.rs"
SERVER = REPO_ROOT / "src" / "lva" / "server.py"

# Tauri commands that hand model lifecycle to the desktop shell instead of Core.
DIRECT_MODEL_LIFECYCLE = (
    "scan_models",
    "refresh_models",
    "switch_llm_model",
    "unload_vram",
    "cold_start_llm",
)

# Hub management surface that must never appear outside Core.
HUB_MANAGEMENT_ENDPOINTS = (
    "/api/models/load",
    "/api/models/stop",
    "/api/models/refresh",
    "/api/sys/version",
    "/api/models/config/get",
)


# ----------------------------------------------------------------------- I21
def test_rust_exposes_no_direct_model_lifecycle_commands():
    src = read_text(LIB_RS)
    present = [name for name in DIRECT_MODEL_LIFECYCLE if f"fn {name}(" in src]
    assert not present, (
        "I21 / PR-015: the Tauri shell still owns direct model lifecycle "
        f"({present}); model runtime must be reached only via Core -> Hub"
    )


def test_no_hub_management_client_outside_core():
    offenders: list[str] = []
    for path in iter_source_files(
        ["apps/desktop-shell/src-tauri/src", "apps/desktop-ui/src"], (".rs", ".ts", ".vue")
    ):
        text = read_text(path)
        for endpoint in forbidden_endpoint_hits(text, HUB_MANAGEMENT_ENDPOINTS):
            offenders.append(f"{path.relative_to(REPO_ROOT)} -> {endpoint}")
    assert not offenders, (
        "I21: Hub management endpoints must be reachable only from LVA Core; "
        f"found: {offenders}"
    )


def test_core_actually_wires_a_hub_saga():
    src = read_text(SERVER)
    assert "hub_saga=" in src, (
        "I21/PR-014: the Core never passes a hub_saga into RuntimeController, so "
        "Hub control has no runtime origin at all"
    )


def test_legacy_1234_default_is_gone():
    cfg = read_text(REPO_ROOT / "src" / "lva" / "config.py")
    assert "127.0.0.1:1234" not in cfg, (
        "PR-015: the 1234 / LM Studio default endpoint must be removed; "
        "the default must target the Hub inference face"
    )


# ----------------------------------------------------------------------- I22
# Endpoints that are NOT user conversation entries, by owner ruling of
# 2026-09-24: `tts_say` synthesizes arbitrary text and returns a WAV, so it is a
# developer/debug tool rather than a conversation entry.  I22 governs
# conversation entries; excluding a debug endpoint here keeps the assertion at
# full strength for the routes I22 actually covers.
DEBUG_ENDPOINTS = {"tts_say"}


def test_no_route_bypasses_the_command_dispatcher():
    """Conversation entries must adapt into commands, not call providers directly."""
    offenders = [
        entry
        for entry in conversation_bypasses(
            read_text(SERVER),
            {"stream", "append_event", "synthesize", "barge_in", "set_mode"},
        )
        if not any(entry.startswith(f"{name}()") for name in DEBUG_ENDPOINTS)
    ]
    assert not offenders, (
        "I22: these route handlers perform conversation/provider/journal side "
        f"effects directly instead of dispatching a command: {offenders}"
    )


def test_ask_route_adapts_into_a_command():
    src = read_text(SERVER)
    assert "execute_command" in src, "the server must expose the command dispatcher"
    routes = route_call_map(src)
    if "ask" in routes:
        called = routes["ask"]
        assert "execute_command" in called, (
            "I22: /api/ask must adapt into a CommandEnvelope and go through "
            "RuntimeController.execute_command"
        )
