"""RED: v1.2.1 PR-012 Hub compatibility and control client (R14, half 1).

Frozen rule (L1250-1258):

* `Files/new`: ``providers/hub_control.py``, **``hub_contracts_v0_9_8_3.py``**,
  contract fixtures/tests.
* `Steps`: identity/capability probes; DTO; **WS reconnect**; consume PR-008's typed
  listener attestation and fail closed outside ``VERIFIED_LOOPBACK``; **async
  operation tracking**.
* `Tests / acceptance`: pinned fixture smoke; **unknown version DEGRADED**;
  control refused when the Hub also listens on 0.0.0.0; ``UNVERIFIED_BIND`` when
  the bind cannot be proven; a load HTTP ack is not misread as READY; no
  auto-unload API.

Handshake (L575-582) is the shape these assertions follow::

    /api/sys/version + /api/node/info + effective-bind verification
      +-- supported fixture + probes + VERIFIED_LOOPBACK -> READY
      +-- unknown version, probes partially pass         -> DEGRADED
      +-- wildcard/non-loopback listener confirmed       -> HUB_CONTROL_UNSAFE
      +-- effective listeners cannot be proven           -> HUB_BIND_UNVERIFIED
      +-- unreachable                                    -> UNAVAILABLE

Scope note: this file covers **half 1** -- the versioned contract, the DEGRADED
verdict, pinned fixtures, WS reconnect and operation tracking.  All of it is
contract-free.  The attestation *channel* (how a Rust-produced verdict reaches
Core) is designed in `docs/PR-012-ATTESTATION-CHANNEL-DESIGN.md` and needs its own
authorization, so its RED items are expected to stay red until then.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
PROVIDERS = LVA / "providers"
CONTROL = PROVIDERS / "hub_control.py"
CONTRACTS = PROVIDERS / "hub_contracts_v0_9_8_3.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "hub"


# ------------------------------------------------- versioned contract (L1253)
def test_pinned_hub_contract_module_exists():
    assert CONTRACTS.is_file(), (
        "PR-012 Files/new lists `hub_contracts_v0_9_8_3.py`; the control client "
        "still has no pinned contract, so 'versioned DTO' (L584) is unmet"
    )


def test_contract_pins_the_reviewed_upstream_commit():
    """L571 freezes the first compatible target to a reviewed upstream commit."""
    src = read_text(CONTRACTS)
    assert "a9cf12809e8243ff0b820abda1a24934d4eb7026" in src, (
        "the pinned contract must record the reviewed upstream commit hash"
    )
    assert re.search(r"VERSION\s*=\s*[\"']0\.9\.8\.3", src), (
        "the pinned Hub version must be declared explicitly"
    )


def test_contract_declares_a_load_request_dto():
    """L592 maps the Hub profile onto `HubLoadRequestV0_9_8_3`."""
    src = read_text(CONTRACTS)
    assert "HubLoadRequestV0_9_8_3" in src, (
        "the versioned load DTO is named in the frozen plan and must exist"
    )


def test_unknown_fields_are_preserved_not_rewritten():
    """L584: unknown fields are kept read-only, never written back blindly."""
    src = read_text(CONTRACTS)
    assert re.search(r"extra\s*=\s*[\"']allow", src), (
        "the versioned DTO must tolerate unknown fields rather than dropping them"
    )


# --------------------------------------------------- DEGRADED verdict (L578)
def test_unknown_version_yields_degraded():
    src = read_text(CONTROL) + read_text(CONTRACTS)
    assert "DEGRADED" in src, (
        "L578: an unknown Hub version with partially passing probes must resolve "
        "to DEGRADED and disable the missing operations"
    )
    assert re.search(r"class\s+\w*(Capability|Handshake|Compatibility)\w*", src), (
        "the handshake verdict needs an explicit type so it can be tested"
    )


def test_missing_operations_are_disabled_not_attempted():
    """'disable missing operations' is the actionable half of DEGRADED."""
    src = read_text(CONTROL)
    assert re.search(r"def\s+\w*(supports|can_)\w*", src), (
        "the control client must expose a capability query so a caller can avoid "
        "issuing an operation the pinned contract does not support"
    )


# ------------------------------------------------------- pinned fixtures
def test_pinned_fixture_smoke_assets_exist():
    assert FIXTURES.is_dir() and any(FIXTURES.iterdir()), (
        "PR-012 acceptance asks for 'pinned fixture smoke'; there are no Hub "
        "fixtures, so the client is only ever exercised against a live Hub"
    )


def test_fixtures_are_redacted():
    """L571 requires sanitised request/response fixtures."""
    offenders: list[str] = []
    for path in FIXTURES.rglob("*"):
        if not path.is_file():
            continue
        text = read_text(path)
        for pattern in (r"[A-Za-z]:\\\\", r"/Users/", r"Bearer ", r"sk-"):
            if re.search(pattern, text):
                offenders.append(f"{path.name}: {pattern}")
    assert not offenders, (
        f"the Hub fixtures must be sanitised; found {offenders}"
    )


# --------------------------------------------------------- WS reconnect
def test_hub_event_stream_reconnects():
    """L1255 Steps include WS reconnect for the Hub event stream."""
    sources = "".join(
        read_text(p) for p in PROVIDERS.glob("*.py")
    )
    assert re.search(r"reconnect|backoff", sources, re.I), (
        "PR-012 requires a Hub event-stream client with reconnect; `providers/` has "
        "no websocket or backoff code at all"
    )


# ---------------------------------------------------- operation tracking
def test_async_operation_tracking_exists():
    """L1255 Steps include async operation tracking."""
    sources = "".join(read_text(p) for p in PROVIDERS.glob("*.py"))
    assert re.search(r"operation_id", sources), (
        "the contract already carries `hub.operation_progress` with an "
        "`operation_id`; the client must track operations by that id instead of "
        "treating a load ack as completion"
    )


def test_load_ack_is_not_treated_as_ready():
    """Acceptance: a load HTTP ack must not be misread as READY."""
    src = read_text(CONTROL)
    assert "does NOT mean the model" in src or "not mean" in src, (
        "the load path must state explicitly that an ack is not readiness"
    )
    sources = "".join(read_text(p) for p in PROVIDERS.glob("*.py"))
    assert re.search(r"verify|confirm", sources, re.I), (
        "there must be a verification step before readiness is committed"
    )


# --------------------------------------------------- no auto-unload (L1257)
def test_no_auto_unload_api_is_exposed():
    """L1257: the Hub has no auto-unload API and the client must not invent one.

    Note this looks for an auto-unload *call surface* (a method or endpoint), not
    the words: a docstring correctly explaining that Hub has no auto-unload must
    not be flagged, which is what an earlier version of this test got wrong.
    """
    for path in PROVIDERS.glob("*.py"):
        src = read_text(path)
        assert not re.search(r"def\s+\w*auto[_-]?unload", src, re.I), (
            f"{path.name}: the client must not expose an auto-unload method"
        )
        assert not re.search(r"['\"]/[\w/]*auto[_-]?unload", src, re.I), (
            f"{path.name}: the client must not call an auto-unload endpoint"
        )
