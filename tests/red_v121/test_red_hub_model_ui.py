"""RED: PR-026 Hub model UI (R33).

Plan L1392-1400.  The shipped Conversation Model section could only refresh and
sleep: there was no inventory list, so the user could not see which models the
Hub holds, could not bind one, and had no way to answer a
MODEL_CONFLICT_REQUIRES_CONFIRMATION.  The three defects R33 fixed in the Core
(refresh rejected, `force` dropped, no progress producer) existed precisely
because nothing consumed them.

Acceptance lines asserted here are the plan's own:
* "list/refresh/bind/sleep" (L1398) -- all four must be reachable from the UI;
* "多 loaded model 不误标 current" (L1400) -- a second loaded model must not be
  rendered as the bound one;
* "不展示 ngl/context/mmproj" (L1400) -- Hub launch parameters never render;
* "UI 不直连 Hub" (L1400) / I21 -- the UI talks to Core commands only.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

UI = REPO_ROOT / "apps" / "desktop-ui" / "src"
MODEL_SECTION = UI / "features" / "settings" / "ModelSection.vue"
SETTINGS_STORE = UI / "stores" / "settings.ts"


def _model_section() -> str:
    assert MODEL_SECTION.exists(), "the Conversation Model section must exist"
    return read_text(MODEL_SECTION)


def _settings_store() -> str:
    return read_text(SETTINGS_STORE)


def _ui_blob() -> str:
    parts = []
    for path in list(UI.rglob("*.ts")) + list(UI.rglob("*.vue")):
        if "generated" in path.parts:
            continue
        parts.append(read_text(path))
    return "\n".join(parts)


# ============================================ list / refresh / bind / sleep
def test_the_section_offers_all_four_operations():
    """L1398 Steps: list/refresh/bind/sleep."""
    section = _model_section()
    store = _settings_store()
    blob = section + store
    assert "hub.refresh" in blob, "the UI must be able to refresh the Hub inventory"
    assert "hub.bind_model" in blob, "the UI must be able to bind a model"
    assert "hub.sleep_bound_model" in blob, "the UI must be able to sleep the bound model"
    assert re.search(r"inventory|hubModels|availableModels", section + store), (
        "the section must render the Hub inventory it is supposed to list"
    )


def test_the_refresh_result_is_actually_consumed():
    """A refresh whose payload is dropped is the R24 overstatement again."""
    store = _settings_store()
    block = re.search(r"async function refreshHubModels\((.*?)\n  \}", store, re.S)
    assert block, "refreshHubModels must exist"
    body = block.group(1)
    assert re.search(r"res\.data|result\.data", body), (
        "the refresh result carries the inventory; ignoring it leaves the list empty"
    )
    assert re.search(r"models", body), "the refresh must store the returned model list"


def test_the_refresh_status_accepts_what_the_core_returns():
    """`hub.refresh` answers `accepted`; testing for `applied` reads as failure."""
    store = _settings_store()
    block = re.search(r"async function refreshHubModels\((.*?)\n  \}", store, re.S)
    assert block, "refreshHubModels must exist"
    body = block.group(1)
    # The real Core answers `accepted` for `hub.refresh` (there is no saga step to
    # apply); the dev mock answers `applied`.  A branch that only knows `applied`
    # reports every real refresh as refused, so both must be accepted.
    assert re.search(r"status\s*===\s*'accepted'", body), (
        "hub.refresh returns `accepted` from the real Core; a branch that only "
        "checks `applied` reports a successful refresh as refused"
    )


# ======================================== loaded vs bound must not be conflated
def test_a_second_loaded_model_is_not_shown_as_the_bound_one():
    """L1400 acceptance: 多 loaded model 不误标 current."""
    blob = _ui_blob()
    assert re.search(r"bound|active_model_id", blob), (
        "the UI must distinguish the bound model from the loaded set"
    )
    assert re.search(r"loaded", blob), (
        "the loaded set must be rendered separately from the binding"
    )


def test_the_bound_marker_uses_the_binding_not_mere_loaded_membership():
    """A loaded model is not necessarily the bound model (plan 5.5)."""
    section = _model_section()
    # The "current/bound" marker must be driven by the binding identity, not by
    # a bare membership test against the loaded list.
    assert re.search(r"isBound|boundModel|active_model_id|activeModel", section), (
        "the section must mark the bound model from the binding, not from the "
        "loaded set -- otherwise any second loaded model looks current"
    )


# ============================================ no Hub launch parameters in UI
def test_hub_launch_parameters_never_render():
    """L1400 acceptance: 不展示 ngl/context/mmproj."""
    section = _model_section()
    for token in ("ngl", "mmproj", "extraParams", "llamaBinPathSelect"):
        assert token not in section, (
            f"the Conversation Model UI must not render the Hub launch parameter {token!r}"
        )
    assert re.search(r"\bcontextLength\b", section) is None, (
        "the context length is a Hub profile detail, not a user-facing setting"
    )


# ========================================================== no direct Hub I/O
def test_the_ui_never_talks_to_the_hub_directly():
    """I21 / L1400: management is Core-only."""
    blob = _ui_blob()
    for pattern in ("8080", "8081", "/api/models", "X-LVA-Bound-Model", "Bearer"):
        assert pattern not in blob, (
            f"the UI must not reach the Hub directly; found {pattern!r}"
        )


# ================================================== profile-required guidance
def test_profile_required_offers_guidance_instead_of_guessing():
    """L1398: profile-required 引导 (plan L593: LVA must not invent parameters)."""
    blob = _model_section() + _settings_store()
    assert "PROFILE_REQUIRED" in blob, (
        "the UI must recognise PROFILE_REQUIRED and guide the user to the Hub "
        "instead of silently retrying"
    )
    assert re.search(r"Hub", blob), "the guidance must point at the Hub configuration"


# ===================================================== conflict confirmation
def test_preexisting_stop_requires_explicit_confirmation():
    """L1398: preexisting stop confirm; plan 5.5 requires confirmation to stop."""
    blob = _model_section() + _settings_store()
    assert "MODEL_CONFLICT_REQUIRES_CONFIRMATION" in blob, (
        "the UI must surface the conflict code so the user can answer it"
    )
    assert re.search(r"force", blob), (
        "answering the conflict means sending the explicit confirmation flag"
    )


def test_confirmation_is_not_sent_by_default():
    """Stopping a preexisting model must never be the default path."""
    store = _settings_store()
    block = re.search(r"async function bindHubModel\((.*?)\n  \}", store, re.S)
    assert block, "bindHubModel must exist"
    body = block.group(1)
    assert re.search(r"force\s*=\s*false", body) or re.search(r"force:\s*false", body), (
        "bindHubModel must default to no confirmation, so a plain bind never "
        "stops a model the user did not ask to stop"
    )


# ============================================================ progress / retry
def test_operation_progress_is_rendered():
    """L1398: progress/error/retry; L993 shows operation progress."""
    blob = _model_section() + _settings_store()
    assert re.search(r"hub\.operation_progress|operationProgress|progress", blob), (
        "the UI must show the operation progress the Core now publishes"
    )


def test_errors_are_shown_and_retryable():
    """L1398: progress/error/retry."""
    section = _model_section()
    assert re.search(r"last_error|lastError|error", section), (
        "a failed bind must be visible in the section"
    )
    assert re.search(r"重试|retry", section, re.I), (
        "a failed operation must offer a retry"
    )
