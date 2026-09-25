"""RED: v1.2.1 PR-012 half 2 -- the typed bind-attestation channel (R15).

Frozen basis:

* Plan L1256: ``G 只消费 B 提供的 typed attestation，不实现 Windows process
  inspection`` -- Rust observes, Core consumes.
* Plan L665: only ``VERIFIED_LOOPBACK`` permits load/stop/switch control.
* Plan L579/L580: a confirmed wildcard/non-loopback listener is
  ``HUB_CONTROL_UNSAFE`` and a bind that cannot be proven is ``HUB_BIND_UNVERIFIED``;
  both disable management.
* Design (approved): Rust sends the attestation to Core over the **existing
  authenticated WS** (Rust is the WS client, Core the server), never via the
  WebView.  Method A adds one inbound command carrying the already-defined
  ``HubBindAttestation`` type.
* Reviewer's acceptance addition: **attestation freshness**.  L665's gate is a
  continuing condition, not a one-time ticket -- a cached VERIFIED must not stay
  authoritative forever, and control must fail closed when no fresh attestation
  exists.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
COMMANDS = LVA / "contracts" / "commands.py"
RUNTIME = LVA / "core" / "runtime.py"
SERVER = LVA / "server.py"
TAURI_SRC = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src"


# ------------------------------------------------------------- contract shape
def test_contract_carries_an_inbound_attestation_command():
    src = read_text(COMMANDS)
    assert re.search(r"class\s+HubAttestBindPayload\b", src), (
        "the approved design adds one inbound command carrying the bind "
        "attestation; without it Core has no way to receive a Rust-produced verdict"
    )
    assert 'Literal["hub.attest_bind"]' in src, (
        "the command discriminator must be `hub.attest_bind`"
    )
    union = re.search(r"CommandPayload = Annotated\[(.*?)\n\]", src, re.S)
    assert union and "HubAttestBindPayload" in union.group(1), (
        "the new payload must be a member of the CommandPayload union"
    )


def test_contract_reuses_the_existing_attestation_type():
    """The design's key economy: no new type definition is introduced."""
    src = read_text(COMMANDS)
    # Match up to the next top-level declaration rather than the next blank line:
    # the class carries a docstring, so a blank-line terminator would cut it short.
    block = re.search(
        r"class\s+HubAttestBindPayload\b.*?(?=\nclass\s|\Z)", src, re.S
    )
    assert block, "HubAttestBindPayload must be declared"
    assert "attestation: HubBindAttestation" in block.group(0), (
        "the payload must carry the already-defined HubBindAttestation type, "
        "not a parallel definition"
    )


# ------------------------------------------------------------- Core storage
def test_runtime_stores_the_attestation():
    src = read_text(RUNTIME)
    assert "hub_bind_attestation" in src, (
        "Core must hold the received attestation in RuntimeState; today the "
        "field exists but nothing ever writes it"
    )
    assert re.search(r"def\s+set_hub_bind_attestation", src), (
        "the attestation needs an explicit setter so the update point is auditable"
    )


def test_dispatch_handles_the_attestation_command():
    src = read_text(RUNTIME)
    assert '"hub.attest_bind"' in src, (
        "the dispatcher must handle `hub.attest_bind`; otherwise the command is "
        "in the contract but unimplemented"
    )


# --------------------------------------------------------- the gate (L665)
def test_control_requires_verified_loopback():
    """Only VERIFIED_LOOPBACK permits control (plan L665)."""
    src = read_text(RUNTIME)
    assert re.search(r"def\s+\w*hub_control_allowed\w*", src), (
        "there must be a single predicate answering 'may Hub control run now?', "
        "so the gate is not re-derived inconsistently at each call site"
    )
    body = re.search(r"def\s+\w*hub_control_allowed\w*\(.*?\n(.*?)\n    def ", src, re.S)
    assert body, "the predicate must have a body"
    assert "VERIFIED_LOOPBACK" in body.group(1), (
        "control must be gated on the VERIFIED_LOOPBACK verdict"
    )


def test_control_is_denied_without_any_attestation():
    """fail-closed: no attestation means no control."""
    src = read_text(RUNTIME)
    body = re.search(r"def\s+\w*hub_control_allowed\w*\(.*?\n(.*?)\n    def ", src, re.S)
    assert body and "None" in body.group(1), (
        "the predicate must explicitly treat a missing attestation as denial"
    )


def test_attestation_freshness_is_enforced():
    """Reviewer's acceptance addition: a one-time VERIFIED must not be cached forever."""
    src = read_text(RUNTIME)
    assert re.search(r"revalidate_after|max_age|stale_after|fresh", src, re.I), (
        "L665 is a continuing condition: a stale attestation must stop authorising "
        "control rather than being trusted indefinitely"
    )


def test_hub_control_operations_consult_the_gate():
    """The gate must actually be consulted, not merely defined."""
    src = read_text(RUNTIME)
    assert src.count("hub_control_allowed") >= 3, (
        "the predicate should be defined once and used by the Hub control paths "
        "(bind/stop), otherwise it is dead code"
    )


# -------------------------------------------------- server wiring (PR-014 hook)
def test_server_wires_the_hub_saga():
    """PR-014's assertion also lands here: the saga must be reachable from Core."""
    src = read_text(SERVER)
    assert "hub_saga=" in src, (
        "`server.py` must pass a hub_saga into RuntimeController; the saga exists "
        "in providers/hub_runtime.py but has no runtime origin"
    )


def test_gate_denies_when_the_bind_is_unproven():
    """Behavioural: build a RuntimeState verdict set and assert the gate denies."""
    from uuid import uuid4

    from lva.contracts.state import HubBindAttestation
    from lva.core.runtime import RuntimeController

    rt = RuntimeController(runtime_instance_id=uuid4())

    # No attestation at all -> denied.
    assert not rt.hub_control_allowed()

    now = datetime.now(timezone.utc)
    unverified = HubBindAttestation(
        status="UNVERIFIED_BIND",
        reason_code="PROBE_FAILED",
        checked_at=now,
        attestation_id="att-unverified",
    )
    rt.set_hub_bind_attestation(unverified)
    assert not rt.hub_control_allowed(), "UNVERIFIED_BIND must not authorise control"

    verified = HubBindAttestation(
        status="VERIFIED_LOOPBACK",
        reason_code=None,
        checked_at=now,
        attestation_id="att-verified",
        revalidate_after=now + timedelta(seconds=60),
    )
    rt.set_hub_bind_attestation(verified)
    assert rt.hub_control_allowed(), "a fresh VERIFIED_LOOPBACK must authorise control"

    # Same verdict, but past its revalidation point -> denied again.
    stale = HubBindAttestation(
        status="VERIFIED_LOOPBACK",
        reason_code=None,
        checked_at=now - timedelta(seconds=600),
        attestation_id="att-stale",
        revalidate_after=now - timedelta(seconds=300),
    )
    rt.set_hub_bind_attestation(stale)
    assert not rt.hub_control_allowed(), (
        "a VERIFIED attestation past revalidate_after must stop authorising control"
    )


# ---------------------------------------------- wiring must not self-recurse
def test_server_wiring_does_not_recurse():
    """`get_runtime()` builds the saga, so the saga must not call `get_runtime()`.

    An eager callback capture would recurse infinitely; the callbacks have to be
    resolved lazily.  This is asserted behaviourally because a structural check
    would not catch a different route into the same cycle.
    """
    import os
    import tempfile

    os.environ.setdefault("LVA_ROOT", tempfile.mkdtemp())
    from lva import server as server_mod

    server_mod._runtime = None
    server_mod._hub_saga = None
    server_mod._journal = None
    try:
        rt = server_mod.get_runtime()
        assert rt._hub_saga is not None, "the saga must be wired into Core"
        assert server_mod.get_hub_saga() is rt._hub_saga, "the saga must be a singleton"
    finally:
        if server_mod._journal is not None:
            server_mod._journal.conn.close()
        server_mod._runtime = None
        server_mod._hub_saga = None
        server_mod._journal = None


# ------------------------------------------- the attested port must be the Hub
def test_attested_port_matches_the_hub_control_face():
    """The port the attestation probes must be the Hub control face.

    Plan L527: "默认入口为 8080，child 通常分配 8081+；LVA 不依赖 child 端口".
    The real Hub config (`config/application.json`) sets `webPort: 8080` and
    `httpOnlyPort: 8081`.

    Why this is a regression guard rather than a nicety: if the probed port has no
    listener, `attest_for_port` returns `UnverifiedBind` and `control_allowed()`
    stays False **forever**, even against a perfectly healthy Hub.  The Rust unit
    fixtures use the same wrong number, so they cannot catch it -- that is exactly
    how this shipped.
    """
    lib = read_text(TAURI_SRC / "lib.rs")
    match = re.search(r"HUB_CONTROL_PORT\s*:\s*u16\s*=\s*(\d+)", lib)
    assert match, "the attested port must be a named constant"
    probed = int(match.group(1))

    cfg = read_text(LVA / "config.py")
    hub_port = re.search(r'HUB_PORT\s*=.*?["\'](\d+)["\']', cfg)
    assert hub_port, "config.py must declare the Hub port"
    declared = int(hub_port.group(1))

    assert probed == declared, (
        f"the Rust attestation probes port {probed} but the Hub control face is "
        f"{declared} (plan L527: default entry is 8080). Probing a port with no "
        "listener yields UNVERIFIED_BIND and permanently closes the control gate."
    )


def test_attested_port_is_not_a_child_port():
    """LVA must not attest a child port; children get 8081+ (plan L527)."""
    lib = read_text(TAURI_SRC / "lib.rs")
    match = re.search(r"HUB_CONTROL_PORT\s*:\s*u16\s*=\s*(\d+)", lib)
    assert match, "the attested port must be a named constant"
    probed = int(match.group(1))
    assert probed == 8080, (
        f"the Hub control face is 8080 (plan L527); {probed} would be a child "
        "port, and LVA does not depend on child ports"
    )
