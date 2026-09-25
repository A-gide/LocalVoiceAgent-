"""RED: the Hub inventory/refresh/force surface PR-026 needs (R33).

Source audit before writing this file found three defects that make the Hub
model UI impossible to build honestly:

1. hub.refresh is **rejected** whenever a saga exists.  The dispatcher hands
   every Hub control command to _schedule_hub_saga, which correctly answers
   "there is no saga step for refresh" -- and the dispatcher then reads that
   False as "could not be scheduled" and returns rejected / HUB_UNAVAILABLE.
   Against the real server (which always has a saga) the UI can never refresh,
   so it can never list anything.
2. HubBindModelPayload.force is dropped.  The UI sends it, the payload declares
   it, and _schedule_hub_saga calls switch_model(payload.model_id) without it,
   so force_stop_preexisting is always False and the documented "preexisting
   stop confirm" path is unreachable from the UI.
3. hub.operation_progress has no producer anywhere, so the "operation progress"
   the plan requires the Conversation Model UI to show (L993) can never arrive.

The inventory is returned through the existing hub.refresh command result data,
so no new command type is introduced and the frozen command list (plan
L470-479) is unchanged.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
RUNTIME = LVA / "core" / "runtime.py"
SAGA = LVA / "providers" / "hub_runtime.py"
SERVER = LVA / "server.py"


class FakeControl:
    """Minimal stand-in for the Hub control client (no network)."""

    def __init__(self, models=None, loaded=None, fail=False) -> None:
        self._models = models if models is not None else []
        self._loaded = loaded if loaded is not None else []
        self.fail = fail
        self.stopped: list[str] = []

    async def list_models(self):
        if self.fail:
            raise RuntimeError("hub unreachable")
        return list(self._models)

    async def list_loaded(self):
        if self.fail:
            raise RuntimeError("hub unreachable")
        return list(self._loaded)

    async def get_profile(self, model_id):
        return {"modelId": model_id, "cmd": "--ctx-size 8192"}

    async def load_model(self, model_id, profile=None):
        return {"success": True}

    async def stop_model(self, model_id):
        self.stopped.append(model_id)
        return {"success": True}


class FakeInference:
    def __init__(self, models=None) -> None:
        self.bound_model_id = None
        self._models = models if models is not None else ["Spark-X2.5-4B-GGUF"]

    def bind_model(self, model_id):
        self.bound_model_id = model_id

    async def list_models(self):
        return list(self._models)


def _fresh_attestation():
    from lva.contracts.state import HubBindAttestation

    now = datetime.now(timezone.utc)
    return HubBindAttestation(
        status="VERIFIED_LOOPBACK",
        checked_at=now,
        attestation_id="r33",
        revalidate_after=now + timedelta(seconds=90),
    )


def _runtime_with_saga(saga, *, attested=True):
    from lva.core.runtime import RuntimeController

    rt = RuntimeController(runtime_instance_id=uuid4(), hub_saga=saga)
    if attested:
        rt.set_hub_bind_attestation(_fresh_attestation())
    return rt


def _bind_command(rt, *, force=False):
    from lva.contracts.commands import CommandEnvelope, HubBindModelPayload

    return CommandEnvelope(
        type="hub.bind_model",
        payload=HubBindModelPayload(type="hub.bind_model", model_id="m1", force=force),
        # `hub.bind_model` is CAS-guarded on the hub_binding aggregate, so a
        # command without the current revision is rejected before dispatch.
        precondition={"aggregate": "hub_binding", "revision": rt.hub_binding_revision},
    )


def _refresh_command():
    from lva.contracts.commands import CommandEnvelope, HubRefreshPayload

    return CommandEnvelope(type="hub.refresh", payload=HubRefreshPayload(type="hub.refresh"))


def _saga(control=None, inference=None, **kwargs):
    from lva.providers.hub_runtime import HubRuntimeSaga

    return HubRuntimeSaga(
        control_client=control or FakeControl(),
        inference_client=inference or FakeInference(),
        **kwargs,
    )


# ============================================ 1. refresh must not be rejected
def test_refresh_is_accepted_when_a_saga_exists():
    """A live saga must not turn hub.refresh into a rejection."""
    rt = _runtime_with_saga(_saga())
    res = rt.execute_command(_refresh_command())
    assert res.status == "accepted", (
        f"hub.refresh was {res.status!r}; against the real server every refresh "
        "would be refused"
    )
    assert res.error is None


def test_refresh_data_carries_the_inventory():
    """The command result is the only contract-legal channel for the list."""
    rt = _runtime_with_saga(
        _saga(
            control=FakeControl(
                models=[{"id": "Occamy-1.0", "name": "Occamy-1.0", "size": 21166757696}],
                loaded=[{"id": "Spark-X2.5-4B-GGUF", "name": "Hf_Format", "port": 8082}],
            )
        )
    )
    asyncio.run(rt.refresh_hub_inventory())
    res = rt.execute_command(_refresh_command())
    assert res.status == "accepted"
    data = res.data or {}
    assert "models" in data, "the refresh result must carry the model list"
    assert [m["model_id"] for m in data["models"]] == ["Occamy-1.0"]
    assert data["loaded"] == ["Spark-X2.5-4B-GGUF"], (
        "the loaded set is what lets the UI avoid mislabelling a second loaded model"
    )


def test_inventory_entries_never_expose_hub_profile_details():
    """Plan L993 / PR-026 acceptance: no ngl/context/mmproj on the wire."""
    control = FakeControl(
        models=[
            {
                "id": "Spark-X2.5-4B-GGUF",
                "name": "Hf_Format",
                "size": 4375021152,
                "mg": -1.0,
                "extraParams": "--spec-type none",
                "ngl": 99,
                "contextLength": 8192,
                "mmproj": "mmproj.gguf",
            }
        ]
    )
    saga = _saga(control=control)
    data = asyncio.run(saga.refresh_inventory())
    entry = data["models"][0]
    forbidden = {"ngl", "context", "contextLength", "mmproj", "mg", "extraParams", "cmd", "envVars"}
    leaked = forbidden & set(entry)
    assert not leaked, f"inventory entry leaks Hub profile details: {sorted(leaked)}"
    assert entry["model_id"] == "Spark-X2.5-4B-GGUF"


def test_refresh_requires_the_attestation_gate():
    """Plan L665: control is denied without a fresh VERIFIED_LOOPBACK."""
    rt = _runtime_with_saga(_saga(), attested=False)
    assert asyncio.run(rt.refresh_hub_inventory()) is None, (
        "an unverified bind must not reach the Hub"
    )
    res = rt.execute_command(_refresh_command())
    assert res.status == "rejected" and res.error.code.value == "HUB_BIND_UNVERIFIED"


# =================================================== 2. force must be forwarded
def test_force_is_forwarded_to_the_switch_saga():
    """Preexisting stop confirm is unreachable while force is dropped."""
    seen: dict = {}

    class RecordingSaga:
        async def switch_model(self, model_id, force_stop_preexisting=False):
            seen["model_id"] = model_id
            seen["force"] = force_stop_preexisting

        async def sleep_bound_model(self, *a, **k):  # pragma: no cover
            return None

    rt = _runtime_with_saga(RecordingSaga())

    async def drive():
        res = rt.execute_command(_bind_command(rt, force=True))
        assert res.status == "accepted"
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(drive())
    assert seen.get("force") is True, (
        "force never reaches the saga, so the UI cannot confirm stopping a "
        "preexisting model"
    )
    assert seen.get("model_id") == "m1"


def test_force_defaults_to_false_so_the_conflict_path_stays_the_default():
    seen: dict = {}

    class RecordingSaga:
        async def switch_model(self, model_id, force_stop_preexisting=False):
            seen["force"] = force_stop_preexisting

        async def sleep_bound_model(self, *a, **k):  # pragma: no cover
            return None

    rt = _runtime_with_saga(RecordingSaga())

    async def drive():
        res = rt.execute_command(_bind_command(rt, force=False))
        assert res.status == "accepted"
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(drive())
    assert seen.get("force") is False


# ============================================= 3. progress needs a producer
def test_the_saga_reports_operation_progress():
    """hub.operation_progress must have a producer (plan L993)."""
    events: list[tuple] = []
    control = FakeControl(loaded=[])
    saga = _saga(
        control=control,
        inference=FakeInference(models=["m1"]),
        on_operation_progress=lambda model_id, percent, message: events.append(
            (model_id, percent, message)
        ),
    )
    asyncio.run(saga.switch_model("m1"))
    assert events, "the saga never reported operation progress"
    percents = [p for _, p, _ in events]
    assert percents[0] <= percents[-1], "progress must be monotonic"
    assert events[-1][0] == "m1"


def test_server_wires_the_progress_callback():
    """A callback nobody injects is a producer nobody hears."""
    src = read_text(SERVER)
    assert "on_operation_progress" in src, (
        "server.py must inject the progress callback, exactly like on_binding_changed"
    )


def test_core_publishes_the_frozen_progress_event():
    """No contract change: the existing event type is used."""
    runtime_src = read_text(RUNTIME)
    assert "hub.operation_progress" in runtime_src, (
        "the Core must publish the frozen hub.operation_progress event"
    )
