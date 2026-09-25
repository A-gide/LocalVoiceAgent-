"""RED: single source of truth for the Hub port (B7, R25).

The R20 incident showed why duplicated constants are dangerous: the same fact
(the Hub control port) lived in six places, one of them wrong, and nothing tied
them together.  R21 added guards that *detect* drift; this slice removes the
duplication itself so there is nothing left to drift.

Authority: `src/lva/config.py` is the single Python source.  The provider modules
must not carry a port literal of their own -- they default to the configured Hub
endpoint.  The Rust side cannot import Python, so it keeps one constant and the
existing cross-language guard (R21) keeps it honest.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
PROVIDERS = LVA / "providers"


def test_providers_do_not_carry_their_own_port_literal():
    """A provider must default to the configured endpoint, not a copy of it."""
    offenders: list[str] = []
    for name in ("hub_control.py", "hub_inference.py", "openai_compatible.py"):
        src = read_text(PROVIDERS / name)
        for match in re.finditer(r"127\.0\.0\.1:\d{2,5}", src):
            offenders.append(f"{name} -> {match.group(0)}")
    assert not offenders, (
        "these provider modules still hardcode a loopback endpoint; the port must "
        f"come from config so there is one place to change: {offenders}"
    )


def test_providers_default_to_the_configured_hub_url():
    """The default must be derived, not absent -- the client still has to work."""
    for name in ("hub_control.py", "hub_inference.py"):
        src = read_text(PROVIDERS / name)
        assert "hub_base_url" in src or "HUB_BASE_URL" in src or "config" in src, (
            f"{name} must default to the configured Hub endpoint"
        )


def test_config_exposes_one_hub_url_helper():
    """A single helper keeps the derivation in one place."""
    cfg = read_text(LVA / "config.py")
    assert re.search(r"def\s+hub_base_url\s*\(", cfg), (
        "config.py should expose `hub_base_url()` so callers do not each build the "
        "URL from SERVICE_HOST and HUB_PORT themselves"
    )


def test_server_uses_the_helper():
    """The Core wiring must use the helper, not re-derive the URL."""
    src = read_text(LVA / "server.py")
    assert "hub_base_url()" in src, (
        "server.py builds the Hub URL by hand; use the config helper"
    )


def test_rust_keeps_exactly_one_port_constant():
    """Rust cannot share Python code, so it keeps one constant -- and only one."""
    lib = read_text(REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src" / "lib.rs")
    assert len(re.findall(r"HUB_CONTROL_PORT", lib)) >= 2, (
        "the constant must be declared and used"
    )
    # Count code, not prose: a comment may legitimately mention the number.
    code_lines = [
        line for line in lib.splitlines()
        if not line.lstrip().startswith("//")
    ]
    code = "\n".join(code_lines)
    assert len(re.findall(r"\b8080\b", code)) == 1, (
        "the port literal must appear exactly once in lib.rs code (the constant), "
        "so there is a single place to change"
    )


def test_config_llm_endpoint_derives_from_the_hub_url():
    """`LLM_BASE_URL` is the same fact as the Hub endpoint -- derive, don't copy."""
    cfg = read_text(LVA / "config.py")
    assert not re.search(r"127\.0\.0\.1:\d{2,5}", cfg), (
        "config.py still hardcodes a loopback endpoint; even the LLM default must "
        "come from `hub_base_url()` so the Hub port has one source"
    )
    line = next(
        (ln for ln in cfg.splitlines() if ln.startswith("LLM_BASE_URL")), None
    )
    assert line is not None, "LLM_BASE_URL must still exist (PR-015 keeps it)"
    assert "hub_base_url" in line, (
        "LLM_BASE_URL must derive from `hub_base_url(with_v1=True)` so changing "
        f"the Hub port changes it too; got: {line.strip()}"
    )
