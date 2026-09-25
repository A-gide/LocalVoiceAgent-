"""Cross-language / cross-layer consistency guards (defence-in-depth, R21).

Why this file exists: a real bug shipped in R08 and survived until R20 --
`lib.rs::HUB_CONTROL_PORT` was 8089 while the Hub control face (and Core) use
8080.  It survived because:

1. the same fact was hardcoded in two languages with nothing tying them
   together, and
2. the Rust unit fixtures used the *same* wrong number, so they were
   self-consistent and stayed green.

The guards below make both failure modes detectable: each duplicated fact gets an
explicit equality assertion, and the Rust attestation fixtures must not carry a
port literal that disagrees with the constant.
"""
from __future__ import annotations

import json
import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
TAURI = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri"
TAURI_SRC = TAURI / "src"


def _rust_const(source: str, name: str) -> int:
    match = re.search(rf"const\s+{name}\s*:\s*u(?:16|32)\s*=\s*(\d+)", source)
    assert match, f"Rust constant `{name}` must be declared as an integer"
    return int(match.group(1))


def _py_int_const(source: str, name: str) -> int:
    match = re.search(rf'{name}\s*=.*?["\'](\d+)["\']', source)
    assert match, f"Python constant `{name}` must be declared"
    return int(match.group(1))


# ---------------------------------------------------- fact 1: the Hub control face
def test_hub_port_agrees_across_languages():
    """Rust attestation port == Core Hub port (plan L527: default entry 8080)."""
    rust = _rust_const(read_text(TAURI_SRC / "lib.rs"), "HUB_CONTROL_PORT")
    python = _py_int_const(read_text(LVA / "config.py"), "HUB_PORT")
    assert rust == python, (
        f"the Hub control face is declared as {rust} in Rust and {python} in "
        "Core; probing a port with no listener yields UNVERIFIED_BIND and closes "
        "the control gate permanently"
    )


def test_hub_port_matches_the_frozen_default():
    """Plan L527: the Hub default entry is 8080; children get 8081+."""
    rust = _rust_const(read_text(TAURI_SRC / "lib.rs"), "HUB_CONTROL_PORT")
    python = _py_int_const(read_text(LVA / "config.py"), "HUB_PORT")
    assert rust == 8080 and python == 8080, (
        f"plan L527 fixes the Hub entry at 8080 (got rust={rust}, python={python})"
    )


# ------------------------------------------- fact 2: Core service port (8765)
def test_core_service_port_agrees_across_languages():
    """Rust defaults that point at Core must use the Core declared port.

    `settings.rs` and `settings.default.json` ship an ASR base URL that targets
    Core.  If the Core port changes and these defaults do not, the shipped default
    silently points at nothing.
    """
    core_port = _py_int_const(read_text(LVA / "config.py"), "SERVICE_PORT")

    settings_rs = read_text(TAURI_SRC / "settings.rs")
    rust_defaults = {int(m) for m in re.findall(r"127\.0\.0\.1:(\d+)/api/", settings_rs)}
    assert rust_defaults, "settings.rs must carry a Core-facing default URL"
    assert rust_defaults == {core_port}, (
        f"settings.rs targets Core on {sorted(rust_defaults)} but Core declares "
        f"{core_port}"
    )

    shipped = read_text(TAURI / "settings.default.json")
    shipped_ports = {int(m) for m in re.findall(r"127\.0\.0\.1:(\d+)/api/", shipped)}
    assert shipped_ports == {core_port}, (
        f"settings.default.json targets Core on {sorted(shipped_ports)} but Core "
        f"declares {core_port}"
    )


# ------------------------------------ fact 3: bootstrap protocol version (1)
def test_bootstrap_protocol_version_agrees_across_languages():
    """The LVA_READY handshake version must match on both sides."""
    py_src = read_text(LVA / "bootstrap.py")
    rs_src = read_text(TAURI_SRC / "core_supervisor.rs")

    py_versions = {int(v) for v in re.findall(r"protocol_version\s*!=\s*(\d+)", py_src)}
    rs_versions = {int(v) for v in re.findall(r"protocol_version\s*!=\s*(\d+)", rs_src)}
    assert py_versions and rs_versions, "both sides must validate protocol_version"
    assert py_versions == rs_versions, (
        f"bootstrap protocol_version disagrees: Core {sorted(py_versions)} vs "
        f"shell {sorted(rs_versions)}"
    )


# ------------------------------- fixture-leak guard: no self-referential port
def test_attestation_fixtures_do_not_disagree_with_the_constant():
    """A fixture that repeats a wrong constant keeps the suite green.

    This is exactly how the 8089 bug survived R08-R19: the unit fixtures used the
    same wrong number as the constant.  Every port literal in the attestation test
    module must therefore agree with `HUB_CONTROL_PORT`.
    """
    src = read_text(TAURI_SRC / "network_attestation.rs")
    constant = _rust_const(read_text(TAURI_SRC / "lib.rs"), "HUB_CONTROL_PORT")

    fixture_ports = {int(m) for m in re.findall(r"\bport:\s*(\d{2,5})", src)}
    assert fixture_ports, "the attestation fixtures must set an explicit port"
    assert fixture_ports == {constant}, (
        f"the attestation fixtures use ports {sorted(fixture_ports)} but the "
        f"production constant is {constant}; a fixture that mirrors a wrong "
        "constant cannot detect the error"
    )


def test_netstat_fixture_rows_use_the_real_hub_port():
    """The sample listener table must describe the real Hub port."""
    src = read_text(TAURI_SRC / "network_attestation.rs")
    constant = _rust_const(read_text(TAURI_SRC / "lib.rs"), "HUB_CONTROL_PORT")
    table_ports = {int(m) for m in re.findall(r"TCP\s+[\d.\[\]:]+:(\d{2,5})\s", src)}
    assert table_ports, "the fixture must contain a netstat listener table"
    assert constant in table_ports, (
        f"the sample listener table has no row for the real Hub port {constant}; "
        f"it only carries {sorted(table_ports)}"
    )


# ------------------------- fact 4: the Hub port is duplicated inside Python too
def test_python_provider_defaults_agree_with_the_hub_port():
    """Every Python provider default must use the declared Hub port.

    The R15/R17 retro-audit found the Hub port hardcoded in five Python places
    (`config.py`, two provider defaults, the OpenAI-compatible default and
    `server.py`).  Each is a place the port can drift, and a drifted default
    points at nothing while every unit test stays green.
    """
    hub_port = _py_int_const(read_text(LVA / "config.py"), "HUB_PORT")

    offenders: list[str] = []
    for path in LVA.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        src = read_text(path)
        for match in re.finditer(r"127\.0\.0\.1:(\d{2,5})", src):
            port = int(match.group(1))
            # 3030 is the Screenpipe importer's own service, not the Hub.
            if port in (hub_port, 3030):
                continue
            offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()} -> {port}")
    assert not offenders, (
        f"these Python modules hardcode a loopback port that is neither the Hub "
        f"({hub_port}) nor Screenpipe (3030): {offenders}"
    )


def test_python_provider_defaults_actually_use_the_hub_port():
    """The providers must reach the Hub port through config, not by copying it.

    Before R25 each provider carried its own literal default.  That is what made
    the R20 wrong-port bug possible, so the property is now the opposite: the
    provider must carry **no** port literal and must default through
    `config.hub_base_url()`.  (This assertion was inverted when the single source
    of truth landed -- the old form required the duplication that R25 removes.)
    """
    for name in ("hub_control.py", "hub_inference.py", "openai_compatible.py"):
        src = read_text(LVA / "providers" / name)
        assert not re.search(r"127\.0\.0\.1:\d{2,5}", src), (
            f"providers/{name} still hardcodes a loopback endpoint; the port must "
            "come from config so there is exactly one place to change it"
        )
        assert "hub_base_url" in src, (
            f"providers/{name} must default through `config.hub_base_url()`"
        )
