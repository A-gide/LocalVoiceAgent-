"""RED: PR-013 / PR-014 acceptance face (R18).

Frozen basis:

* PR-013 (L1260-1268) `Hub inference provider`.  Files/new: `providers/hub_inference.py`,
  modify `llm.py`.  Steps: model binding header/body; SSE parser; reasoning/content
  separation; cancel close; error mapping.  Acceptance: streaming/cancel/reconnect/
  partial UTF-8; no direct child endpoint dependency.
* PR-014 (L1270-1278) `Hub binding and lifecycle saga`.  Files/new:
  `providers/hub_runtime.py`; Hub command handlers/events.  Steps: Part 5.5 state
  machine; profile required; load origin; confirm preexisting stop; provider_epoch
  commit/rollback.  Acceptance: I14/I15/I18/I21; Hub disappears / load fail / late
  WS / multiple loaded models; binding heartbeat must not make a user command
  stale; Sleep behaviour per 5.6.

Why this file exists: both modules are substantially present (hub_runtime.py is
6,166 B and already wired by `server.py::get_hub_saga`), but neither has RED
coverage for its *acceptance* line -- the six existing test files that mention
them only cover adjacent behaviour.  This file is that acceptance face.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
PROVIDERS = LVA / "providers"
INFERENCE = PROVIDERS / "hub_inference.py"
RUNTIME_SAGA = PROVIDERS / "hub_runtime.py"


# ============================================================ PR-013 inference
def test_inference_separates_reasoning_from_content():
    """PR-013 Steps: reasoning/content separation.

    The Hub streams reasoning models too; a client that folds reasoning into the
    spoken reply would read the model's thinking aloud.
    """
    src = read_text(INFERENCE)
    assert "reasoning" in src, (
        "the inference client must distinguish reasoning deltas from content "
        "deltas; today only `delta.content` is read"
    )


def test_inference_maps_errors_to_stable_codes():
    """PR-013 Steps: error mapping.

    `raise_for_status()` alone gives the caller an httpx exception, not a stable
    ErrorCode, so a Hub failure cannot be classified at the boundary.
    """
    src = read_text(INFERENCE)
    assert "ErrorCode" in src or "ErrorEnvelope" in src, (
        "inference failures must map to the frozen error codes rather than "
        "surfacing a raw httpx error"
    )


def test_inference_sends_the_model_binding():
    """PR-013 Steps: model binding header/body.

    The bound model must be pinned on the request, not left to the Hub default,
    or a switch could silently answer from the previous model.
    """
    src = read_text(INFERENCE)
    assert re.search(r"model_id|bound_model|model_binding", src), (
        "the client must accept the *bound* model identity, not just a free-form "
        "model string"
    )


def test_inference_survives_partial_utf8():
    """PR-013 acceptance: partial UTF-8.

    A multi-byte character can be split across SSE chunks; decoding each chunk
    independently would raise or corrupt the text.
    """
    src = read_text(INFERENCE)
    assert re.search(r"decode\(|errors\s*=|codecs|incremental|buffer", src), (
        "the SSE parser must tolerate a multi-byte character split across "
        "chunks (incremental decoding or an explicit errors policy)"
    )


def test_inference_reconnects_the_stream():
    """PR-013 acceptance: reconnect."""
    src = read_text(INFERENCE)
    assert re.search(r"reconnect|retry|backoff", src, re.I), (
        "PR-013 acceptance lists reconnect; the client has no retry path"
    )


def test_inference_has_no_direct_child_endpoint_dependency():
    """PR-013 acceptance: no direct child endpoint dependency.

    LVA must reach inference through the Hub, never by spawning llama-server
    itself (hard constraint 2).
    """
    src = read_text(INFERENCE)
    for forbidden in ("llama-server", "llama_server", "subprocess", "Popen"):
        assert forbidden not in src, (
            f"the inference client must not reference `{forbidden}`: the Hub is "
            "the model runtime authority"
        )


# ========================================================== PR-014 saga face
def test_saga_state_machine_covers_part_5_5():
    """PR-014 Steps: Part 5.5 state machine."""
    src = read_text(RUNTIME_SAGA)
    for item in ("preparing", "loading", "verifying", "ready", "failed"):
        assert item in src, f"the Part 5.5 state machine must include {item}"


def test_saga_refuses_a_switch_without_a_profile():
    """PR-014 Steps: profile required (plan 5.4 -> PROFILE_REQUIRED).

    A model whose Hub profile is missing must be reported, not loaded with
    invented parameters (plan L593: LVA must not guess -ngl/-c/mmproj).
    """
    src = read_text(RUNTIME_SAGA)
    assert re.search(r"PROFILE_REQUIRED|profile_required|no profile|missing profile", src, re.I), (
        "a missing profile must produce PROFILE_REQUIRED rather than a guess"
    )


def test_saga_requires_confirmation_before_stopping_a_preexisting_model():
    """PR-014 Steps: confirm preexisting stop (plan 5.5 / L1275)."""
    src = read_text(RUNTIME_SAGA)
    assert "force_stop_preexisting" in src or "confirm" in src.lower(), (
        "stopping a model LVA did not load must require explicit confirmation"
    )


def test_saga_commits_and_can_roll_back_the_provider_epoch():
    """PR-014 Steps: provider_epoch commit/rollback (L1275) + plan L636.

    L636 is specific about *how* rollback works: a failure leaves the binding in
    FAILED/DEGRADED, the old turn is not resurrected, and re-binding the old model
    needs an explicit rollback operation -- "restoring old in-memory state and
    pretending success" is forbidden.  So this asserts both the epoch is recorded
    and that a failure keeps the honest status.
    """
    src = read_text(RUNTIME_SAGA)
    assert "provider_epoch" in src, "the saga must record the epoch it committed"
    assert re.search(r"rollback|revert|restore", src, re.I), (
        "PR-014 Steps name rollback: a failed switch must be able to return to "
        "the previously verified binding"
    )
    assert "previous_binding" in src, (
        "L636: a failed switch must record what was serving so an explicit "
        "rollback operation can re-bind it"
    )


def test_a_failed_switch_keeps_an_honest_status():
    """L636: a failure leaves FAILED/DEGRADED, never a pretended ``ready``.

    Behavioural: drive a switch whose profile is missing and assert the binding
    does not claim to be serving.
    """
    import asyncio

    import httpx

    from lva.providers.hub_control import LlamaCppHubControlClient
    from lva.providers.hub_inference import LlamaCppHubInferenceClient
    from lva.providers.hub_runtime import HubRuntimeSaga

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/api/sys/version":
                return httpx.Response(200, json={"version": "0.9.8.3"})
            if path == "/api/models/loaded":
                return httpx.Response(200, json=[])
            if path == "/api/models/config/get":
                return httpx.Response(404, json={"error": "Profile not found"})
            return httpx.Response(404)

    transport = Transport()
    saga = HubRuntimeSaga(
        control_client=LlamaCppHubControlClient("http://127.0.0.1:8080", transport=transport),
        inference_client=LlamaCppHubInferenceClient("http://127.0.0.1:8080", transport=transport),
    )
    with pytest.raises(Exception, match="PROFILE_REQUIRED"):
        asyncio.run(saga.switch_model("unknown-model"))

    assert saga.binding.status in ("failed", "degraded"), (
        "L636: a failed switch must leave FAILED/DEGRADED, not a pretended ready"
    )
    assert saga.binding.status != "ready"


def test_saga_handles_multiple_loaded_models():
    """PR-014 acceptance: multiple loaded models.

    The Hub can hold several loaded models; `current model` is an LVA *binding*,
    not global Hub state, so the saga must not treat every loaded model as its own.
    """
    src = read_text(RUNTIME_SAGA)
    assert re.search(r"list_loaded|loaded", src), "the saga must inspect what is loaded"
    assert re.search(r"target|desired", src), (
        "the saga must track its own target binding rather than assuming a "
        "single global current model"
    )


def test_saga_sleep_does_not_stop_a_preexisting_model():
    """PR-014 acceptance: Sleep behaviour per 5.6; LVA stops only what it loaded."""
    src = read_text(RUNTIME_SAGA)
    block = re.search(r"async def sleep_bound_model(.*?)(?=\n    (?:async )?def |\Z)", src, re.S)
    assert block, "sleep_bound_model must exist"
    assert "loaded_by_lva" in block.group(1), (
        "Sleep must stop only a model LVA itself loaded"
    )


def test_binding_heartbeat_does_not_touch_the_user_command_revision():
    """PR-014 acceptance: binding heartbeat must not make a user command stale.

    This is why `hub_binding` is a separate aggregate from `runtime_control`: a
    heartbeat may bump the former and must not bump the latter, or an unrelated
    user command would be rejected as STALE_REVISION.
    """
    from uuid import uuid4

    from lva.contracts.state import HubBinding
    from lva.core.runtime import RuntimeController

    rt = RuntimeController(runtime_instance_id=uuid4())
    control_before = rt.runtime_control_revision
    binding_before = rt.hub_binding_revision

    rt.set_hub_binding(HubBinding(desired_model_id="m", provider_epoch=1, status="ready"))
    assert rt.hub_binding_revision > binding_before, "a binding change bumps its own aggregate"
    assert rt.runtime_control_revision == control_before, (
        "a binding change must not bump runtime_control_revision, or a "
        "concurrent user command would be wrongly rejected as stale"
    )


def test_hub_management_client_stays_core_only():
    """PR-014 acceptance: I21 -- Hub control originates only from LVA Core."""
    offenders: list[str] = []
    for base in ("apps/desktop-shell/src-tauri/src", "apps/desktop-ui/src"):
        root = REPO_ROOT / base
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".rs", ".ts", ".vue"}:
                continue
            if "target" in path.parts or "node_modules" in path.parts:
                continue
            text = read_text(path)
            for endpoint in ("/api/models/load", "/api/models/stop", "/api/models/config/get"):
                if endpoint in text:
                    offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()} -> {endpoint}")
    assert not offenders, f"I21: Hub management must be Core-only; found {offenders}"
