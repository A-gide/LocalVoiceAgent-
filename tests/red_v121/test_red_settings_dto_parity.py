"""RED: the front-end settings DTO must match the Rust one (PR-025).

`get_public_settings` is a Tauri command, so the WebView never sees a schema
for it: TypeScript checks the call against a hand-written interface.  When that
interface drifts from the Rust struct the compiler cannot notice, and the UI
reads `undefined` at runtime.

That is the shipped state.  The Rust `PublicAppSettings` returns

    cloud_api_key_configured / asr_api_key_configured / tts_api_key_configured
    settings_revision, llm_mode, active_character, ...

while the front-end interface declared

    has_openai_key / has_screenpipe_key / autostart

None of those three exist on the wire, so every secret shows "not configured"
however many are set, and `autostart` is always `undefined`.  A configured key
is therefore indistinguishable from an absent one in the UI -- which is exactly
the "configured flag" the plan asks PR-025 to surface (L1387).

What these tests pin down:

1. every field the front end declares exists in the Rust DTO;
2. the three configured flags are the ones Rust actually sends;
3. no secret *value* is declared, only booleans (plan L993).
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

BRIDGE = REPO_ROOT / "apps" / "desktop-ui" / "src" / "bridge" / "tauri-bridge.ts"
SETTINGS_RS = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src" / "settings.rs"


def _rust_public_fields() -> set[str]:
    src = read_text(SETTINGS_RS)
    m = re.search(r"pub struct PublicAppSettings \{(.*?)\n\}", src, re.S)
    assert m, "settings.rs must define PublicAppSettings"
    return set(re.findall(r"pub (\w+):", m.group(1)))


def _frontend_public_fields() -> set[str]:
    src = read_text(BRIDGE)
    m = re.search(r"export interface PublicAppSettings \{(.*?)\n\}", src, re.S)
    assert m, "tauri-bridge.ts must declare the PublicAppSettings it receives"
    return set(re.findall(r"^\s*(\w+)[?]?:", m.group(1), re.M))


def test_every_frontend_field_exists_on_the_wire() -> None:
    """A field the Rust DTO does not send is always undefined at runtime."""
    rust = _rust_public_fields()
    frontend = _frontend_public_fields()
    missing = sorted(frontend - rust)
    assert not missing, (
        f"the front end declares {missing} but get_public_settings does not send "
        f"them; those reads are always undefined.  Rust sends: {sorted(rust)}"
    )


def test_the_configured_flags_are_the_ones_rust_sends() -> None:
    """The plan asks for a configured flag per secret (L1387/L993)."""
    frontend = _frontend_public_fields()
    for flag in ("cloud_api_key_configured", "asr_api_key_configured", "tts_api_key_configured"):
        assert flag in frontend, (
            f"{flag} is missing from the front-end DTO, so the settings UI cannot "
            "tell a configured secret from an absent one"
        )


def test_no_secret_value_is_declared_in_the_frontend_dto() -> None:
    """Plan L993: the UI shows configured/not-configured, never the value."""
    frontend = _frontend_public_fields()
    leaks = [
        name for name in frontend
        if "key" in name and not name.endswith("_configured")
    ]
    assert not leaks, (
        f"these fields would carry secret material rather than a flag: {leaks}"
    )


def test_the_settings_revision_is_exposed_to_the_frontend() -> None:
    """A stale-revision write must be preventable from the UI (plan L397)."""
    assert "settings_revision" in _frontend_public_fields(), (
        "the front end cannot send a CAS precondition for settings writes without "
        "the revision it must quote"
    )

