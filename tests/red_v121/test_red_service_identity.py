"""RED: v1.2.1 PR-008 service identity, readiness and effective-bind attestation (R08).

Frozen rule (plan L1208-1216):

* `Files/new`: ``service_registry.rs``, ``network_attestation.rs``; modify
  ``bridge.rs`` / Tauri event mapping.
* `Steps`: service status mapping; runtime instance tracking; crash reason;
  read the Windows IPv4/IPv6 listener table; associate the control port with an
  identified Hub process; publish a typed bind attestation; redacted diagnostic
  snapshot.
* `Tests / acceptance` (L1215): a restart that changes the PID must not be
  misjudged; ``Unknown`` must not offer stop; the four listener classes
  (127.0.0.1-only / 0.0.0.0 / ``::`` / unmappable) must classify correctly;
  observing a PID/port must not create kill authority; UI/Core must receive
  typed service/bind state.

These are structural assertions on the Rust surface.  The behavioural proof for
the four listener fixtures, the restart-PID change, the ``Unknown`` capability
and the no-kill-authority rule lives in the Rust unit tests beside the code
(``cargo test --lib``), because those are the only place the classification can
actually be executed.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

SRC = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src"
ATTESTATION = SRC / "network_attestation.rs"
REGISTRY = SRC / "service_registry.rs"
LIB_RS = SRC / "lib.rs"
SERVER = REPO_ROOT / "src" / "lva" / "server.py"


def _struct_block(source: str, name: str) -> str:
    """Return the body of `pub struct <name> { ... }` or fail loudly."""
    match = re.search(rf"pub struct {name} \{{(.*?)\n\}}", source, re.S)
    assert match, f"{name} must be declared"
    return match.group(1)


# ------------------------------------------- listener table + bind attestation
def test_network_attestation_module_exists_and_is_declared():
    assert ATTESTATION.is_file(), (
        "PR-008 L1212 lists `network_attestation.rs` as a new file; the Rust side "
        "still has no effective-bind attestation module"
    )
    assert "pub mod network_attestation;" in read_text(LIB_RS), (
        "network_attestation must be declared in lib.rs or it is dead code"
    )


def test_four_listener_fixture_classes_are_representable():
    """L1215 requires 127.0.0.1-only / 0.0.0.0 / `::` / unmappable to classify."""
    src = read_text(ATTESTATION)
    assert "enum BindClass" in src, "the four listener classes need an explicit type"
    for variant in ("LoopbackOnly", "AllInterfacesV4", "AllInterfacesV6", "Unmappable"):
        assert variant in src, f"BindClass must distinguish {variant}"
    assert "fn parse_netstat_tcp" in src or "fn parse_listener_table" in src, (
        "the Windows IPv4/IPv6 listener table must actually be parsed, not assumed"
    )
    assert "fn classify" in src, "classification must be a testable pure function"


def test_attestation_is_redacted():
    """The attestation travels to the WebView, so it must carry no PID/port/address."""
    body = _struct_block(read_text(ATTESTATION), "HubBindAttestation")
    for leak in ("pid", "port", "addr", "endpoint", "token"):
        assert not re.search(rf"\b{leak}\b", body, re.I), (
            f"the bind attestation must not carry `{leak}`; the raw evidence stays on "
            "the Rust diagnostics surface and is correlated by attestation_id only"
        )
    assert "attestation_id" in body, "the attestation must be correlatable by id"


def test_observation_confers_no_kill_authority():
    """L1215: observing a PID/port must not create kill authority."""
    src = read_text(ATTESTATION)
    for verb in ("kill", "terminate", "stop_process", "taskkill"):
        assert verb not in src.lower(), (
            f"network_attestation must never contain `{verb}`: observing a listener "
            "cannot confer process authority"
        )


# ---------------------------------------------------- service identity/readiness
def test_service_registry_exposes_identity_and_readiness():
    src = read_text(REGISTRY)
    assert "enum Readiness" in src or "Readiness" in src, (
        "PR-008 replaces 'PID/port means healthy' with identity/capability/readiness state"
    )
    assert "crash_reason" in src, "L1213 requires a crash reason on the service state"
    assert "instance_token" in src or "restarted" in src, (
        "L1213 requires runtime instance tracking so a PID change is not misjudged"
    )


def test_unknown_ownership_offers_no_stop():
    """L1215: Unknown must not offer stop (and neither may Adopted/External)."""
    src = read_text(REGISTRY)
    match = re.search(r"fn can_stop\([^)]*\)[^{]*\{(.*?)\n    \}", src, re.S)
    assert match, "the registry must expose a capability decision for stop"
    body = match.group(1)
    assert "Spawned" in body, "only a Spawned child may be stopped"
    assert "Adopted" in body and "External" in body and "Unknown" in body, (
        "the stop capability must explicitly exclude Adopted/External/Unknown"
    )
    assert re.search(r"Adopted\s*=>\s*false", body) or "_ => false" in body, (
        "Adopted/External/Unknown must all resolve to can_stop = false"
    )


def test_service_registry_is_actually_wired_to_a_producer():
    """The 09-21 stub had no writer and no reader; PR-008 must fix that."""
    src = read_text(LIB_RS)
    assert re.search(r"service_registry\.(update_status|observe|set_|upsert)", src), (
        "something must write service state, otherwise the registry stays dead code"
    )
    assert re.search(r"get_service_identity|service_identity_status|get_services", src), (
        "something must read service state (a typed command for UI/Core)"
    )


def test_typed_service_status_command_is_registered():
    """L1215: UI/Core must receive typed service/bind state."""
    src = read_text(LIB_RS)
    handler = src[src.index("generate_handler!["):]
    handler = handler[: handler.index("]")]
    assert "get_service_identity_status" in handler, (
        "the typed service/bind state command must be registered in the invoke handler"
    )


# ------------------------------------------------- runtime instance id (V2 / B18)
def test_runtime_instance_id_has_a_single_source():
    """B18: bootstrap generated one id and RuntimeController silently made another."""
    src = read_text(SERVER)
    assert re.search(r"runtime_instance_id\s*=", src), (
        "get_runtime() must pass the bootstrap-generated runtime_instance_id into "
        "RuntimeController; otherwise the id in LVA_READY never matches the one in "
        "RuntimeState and the bridge misreads every first event as an instance change"
    )
