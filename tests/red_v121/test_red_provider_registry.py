"""RED: v1.2.1 PR-011 provider protocols and registry (R12).

Frozen rule (L1238-1246):

* `Current -> target`: concrete clients and pipeline are tightly coupled ->
  ASR/LLM/TTS protocols plus a capability/state registry.
* `Files/new`: ``providers/{base,registry}.py``, **mock providers**.
* `Steps`: make stream/cancel/errors explicit; wrap the existing ASR/TTS/OpenAI
  clients in thin adapters.
* `Tests / acceptance`: **contract mocks can run a complete turn**; the Passive
  guard takes effect **at the registry boundary**.
* `Rollback / deletion`: concrete implementations are not deleted; the old
  factory is removed after PR-037.

State at the time this file was written: ``base.py`` and ``registry.py`` already
exist and the Passive guard already raises ``PASSIVE_PROVIDER_FORBIDDEN``, but
**nothing in production constructs the registry** -- only tests do -- and there
are no contract mocks and no thin adapters.  So the slice is a *wiring* gap, not
a design gap.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
PROVIDERS = LVA / "providers"
REGISTRY = PROVIDERS / "registry.py"
PIPELINE = LVA / "pipeline.py"
SERVER = LVA / "server.py"


def _iter_production_py():
    for path in LVA.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


# ------------------------------------------------------------- mock providers
def test_contract_mock_providers_exist():
    """PR-011 Files/new requires mock providers alongside base/registry."""
    candidates = [
        p for p in PROVIDERS.glob("*.py")
        if "mock" in p.name.lower()
    ]
    assert candidates, (
        "PR-011: `providers/` has base.py and registry.py but no mock providers. "
        "The frozen acceptance line is 'contract mocks can run a complete turn', "
        "which needs mocks that implement the three protocols."
    )


def test_mock_providers_implement_the_three_protocols():
    src = "".join(
        read_text(p) for p in PROVIDERS.glob("*.py") if "mock" in p.name.lower()
    )
    for protocol in ("ASRProvider", "LLMProvider", "TTSProvider"):
        assert protocol in src, (
            f"PR-011: the contract mocks must cover {protocol} so a complete turn "
            "can run without a real model"
        )


# --------------------------------------------------------------- thin adapters
def test_existing_clients_are_wrapped_by_thin_adapters():
    """PR-011 Steps: wrap the existing ASR/TTS/OpenAI clients in thin adapters.

    An adapter is a class that implements a protocol by delegating to an existing
    concrete client -- not a rewrite of the client.
    """
    adapters = []
    for path in PROVIDERS.glob("*.py"):
        if "mock" in path.name.lower() or path.name in {"base.py", "registry.py"}:
            continue
        src = read_text(path)
        if re.search(r"class\s+\w+Adapter", src) or re.search(
            r"class\s+\w+Provider\b", src
        ):
            adapters.append(path.name)
    assert adapters, (
        "PR-011: no thin adapter found. `openai_compatible.py` exists, but the "
        "frozen step also wraps the existing ASR and TTS clients so the registry "
        "can drive them through the same protocol."
    )


def test_asr_and_tts_adapters_exist_not_only_llm():
    src = "".join(read_text(p) for p in PROVIDERS.glob("*.py"))
    for kind in ("ASR", "TTS"):
        assert re.search(rf"class\s+\w*{kind}\w*(Adapter|Provider)\b", src), (
            f"PR-011: only the LLM path appears to be adapted; an {kind} adapter is "
            "required so all three protocols are reachable through the registry"
        )


# ------------------------------------------------------------------- wiring
def test_registry_is_constructed_by_production_code():
    """The registry must be reachable from production, not only from tests."""
    offenders = []
    for path in _iter_production_py():
        if path.parent == PROVIDERS:
            continue  # the module itself and its own exports
        src = read_text(path)
        if "ProviderRegistry(" in src:
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders, (
        "PR-011: `ProviderRegistry` is never instantiated outside `providers/`. "
        "Only tests construct it today, so the registry is dead code in "
        "production and the slice is not wired."
    )


def test_pipeline_reaches_providers_through_the_registry():
    """PR-011 target: pipeline stops calling concrete clients directly."""
    src = read_text(PIPELINE)
    assert "provider" in src.lower(), (
        "PR-011: `pipeline.py` has no provider/registry reference at all, so the "
        "'concrete clients tightly coupled to pipeline' condition is unchanged"
    )


# --------------------------------------------------------- registry boundary
def test_passive_guard_is_enforced_at_the_registry_boundary():
    """PR-011 acceptance: the Passive guard takes effect at the registry boundary.

    Behavioural proof (a forbidden mode raising PASSIVE_PROVIDER_FORBIDDEN from
    the registry) already exists in `tests/invariants`; this asserts the guard is
    still in the registry rather than having been relocated into a caller, which
    is what makes it a *boundary* guarantee.
    """
    src = read_text(REGISTRY)
    assert src.count("PASSIVE_PROVIDER_FORBIDDEN") >= 2, (
        "PR-011: the Passive guard must be enforced inside the registry for both "
        "LLM and TTS scheduling"
    )


def test_registry_reports_capability_and_state():
    """PR-011 target: 'capability/state registry', not just a name lookup."""
    src = read_text(REGISTRY)
    has_state = "ProviderState" in src or "set_provider_status" in src
    assert has_state, (
        "PR-011: the registry registers providers but exposes no capability/state "
        "surface, so `RuntimeState.providers` cannot be fed from it"
    )
