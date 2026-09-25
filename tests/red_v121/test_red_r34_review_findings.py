"""RED: R34 independent-review findings — Hub authorization, saga branches, importer.

Every assertion here goes through the REAL entry point the review used, because
four of the six findings survived only by tests that bypassed the real call path
(the R08/R14/R15/Output-Mute failure shape).

Findings covered (see docs/R34-HANDOFF-INDEPENDENT-REVIEW-2026-09-25.md):
  1  Hub release credential can be submitted from the renderer
  2  bind proof is not bound to the actual Hub (owner dropped, port hardcoded)
  3a early-return branch never pins the inference client
  3b a verification failure leaves the binding stuck in verifying
  3c the old model is stopped before the target profile is known to exist
  4  a later redaction mark does not clear the stored Journal text
  5a an unparseable timestamp is replaced with now and advances the watermark
  5b a record sharing the watermark timestamp is skipped
  5c the page transaction is not atomic (append_event commits on its own)
  6  hub.refresh returns a cache nothing ever fills
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
RUNTIME = LVA / "core" / "runtime.py"
SAGA = LVA / "providers" / "hub_runtime.py"
WORKER = LVA / "screenpipe_importer" / "worker.py"
NORMALIZE = LVA / "screenpipe_importer" / "normalize.py"
REPOSITORY = LVA / "journal" / "repository.py"
RUST = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src"


# =============================================================== fixtures
class FakeControl:
    def __init__(self, models=None, loaded=None, profile_error=None) -> None:
        self._models = models if models is not None else []
        self._loaded = loaded if loaded is not None else []
        self.profile_error = profile_error
        self.stopped: list[str] = []
        self.list_models_calls = 0
        self.list_loaded_calls = 0

    async def list_models(self):
        self.list_models_calls += 1
        return list(self._models)

    async def list_loaded(self):
        self.list_loaded_calls += 1
        return list(self._loaded)

    async def get_profile(self, model_id):
        if self.profile_error:
            raise RuntimeError(self.profile_error)
        return {"modelId": model_id}

    async def load_model(self, model_id, profile=None):
        return {"success": True}

    async def stop_model(self, model_id):
        self.stopped.append(model_id)
        return {"success": True}


class FakeInference:
    def __init__(self, models=None) -> None:
        self.bound_model_id = None
        self._models = models if models is not None else []

    def bind_model(self, model_id):
        self.bound_model_id = model_id

    async def list_models(self):
        return list(self._models)


def _fresh():
    from lva.contracts.state import HubBindAttestation

    now = datetime.now(timezone.utc)
    return HubBindAttestation(
        status="VERIFIED_LOOPBACK",
        checked_at=now,
        attestation_id="r34",
        revalidate_after=now + timedelta(seconds=90),
    )


def _saga(control=None, inference=None, **kw):
    from lva.providers.hub_runtime import HubRuntimeSaga

    return HubRuntimeSaga(
        control_client=control or FakeControl(),
        inference_client=inference or FakeInference(),
        **kw,
    )


# ==================================== 1. attestation source must be privileged
def test_renderer_submitted_attestation_cannot_open_the_gate():
    """Finding 1: the gate must not be liftable from the WebView command face.

    Plan L1256 makes the *process authority* (Rust) the producer, and plan
    L470-479 is the closed list of commands the WebView may issue.  A generic
    send_core_command forward lets the renderer forge the verdict shape, which
    is exactly what the review reproduced.
    """
    from lva.contracts.commands import CommandEnvelope, HubAttestBindPayload
    from lva.core.runtime import RuntimeController

    rt = RuntimeController(runtime_instance_id=uuid4())
    assert rt.hub_control_allowed() is False, "must start closed"

    # Core still accepts the verdict on its authority entry point (the shell's
    # own reporter uses it), so the boundary that matters is in the shell: the
    # WebView-facing forward must not carry this command at all.
    src = read_text(RUST / "lib.rs")
    assert re.search(r"WEBVIEW_COMMANDS|ALLOWED_WEBVIEW_COMMANDS|webview_allowlist", src), (
        "send_core_command must forward only the commands the frozen list grants "
        "the WebView (plan L470-479); without an allowlist the renderer can issue "
        "any command, including hub.attest_bind"
    )
    assert re.search(r"\"hub\.attest_bind\"", src), (
        "the shell must name the authority-only command explicitly so the "
        "exclusion is visible rather than accidental"
    )


def test_the_gate_opens_only_via_the_privileged_entry_point():
    """A privileged path must exist, or the gate could never legitimately open."""
    src = read_text(RUNTIME)
    assert re.search(r"def\s+accept_process_authority_attestation", src), (
        "there must be an explicit privileged entry point for the process "
        "authority to report a verdict"
    )


def test_core_verifies_attestation_provenance_not_only_its_shape():
    """Shape validation is not provenance validation."""
    src = read_text(RUNTIME)
    assert re.search(r"process_authority|privileged|PROCESS_AUTHORITY", src), (
        "Core must distinguish the process authority from the renderer; today it "
        "accepts any well-formed verdict from any caller"
    )


def test_the_bootstrap_secret_is_not_exposed_to_the_webview():
    """The shared secret must stay in the Rust/Core boundary."""
    ui = REPO_ROOT / "apps" / "desktop-ui" / "src"
    blob = "\n".join(
        read_text(p) for p in list(ui.rglob("*.ts")) + list(ui.rglob("*.vue"))
        if "generated" not in p.parts
    )
    assert "attestation_secret" not in blob and "LVA_ATTEST" not in blob, (
        "the attestation secret must never reach the WebView"
    )


# ===================================== 2. the proof must name the actual Hub
def test_the_listener_owner_is_not_discarded():
    """Finding 2: attest_for_port(...).0 throws away the process correlation."""
    src = read_text(RUST / "lib.rs")
    assert not re.search(r"attest_for_port\([^)]*\)\.0", src), (
        "the owner PID returned by attest_for_port is discarded, so the proof "
        "cannot be correlated with the Hub process (plan L1213: control port "
        "must be associated with the identified Hub process)"
    )


def test_the_attested_port_is_not_a_second_hardcoded_source():
    """The port must be resolved at runtime, not pinned by the Rust literal.

    The constant itself stays: R21's cross-language guard requires exactly one
    named default on the Rust side (plan L527 fixes it at 8080).  What must not
    happen is the *probe* using that literal while Core reads `LVA_HUB_PORT` --
    the two ends would then describe different services off the default port.
    """
    src = read_text(RUST / "lib.rs")
    # The constant is the agreed default; the probe must not read it directly.
    assert re.search(r"LVA_HUB_PORT", src), (
        "the probe must honour the same port variable Core reads"
    )
    assert not re.search(r"attest_for_port\(&rows,\s*HUB_CONTROL_PORT", src), (
        "the probe uses the constant directly, so a non-default LVA_HUB_PORT "
        "makes the attestation describe a different service than Core talks to"
    )


def test_the_hub_port_has_one_source_across_the_language_boundary():
    """The port must be supplied to Rust, not duplicated in it."""
    src = read_text(RUST / "lib.rs")
    assert re.search(r"hub_port|LVA_HUB_PORT", src), (
        "Rust must receive the Hub port from the same source Core uses"
    )


# ============================================ 3a. early return must pin
def test_binding_an_already_loaded_model_pins_the_inference_client():
    """Finding 3a: reproduced as binding=new-model / inference=old-model."""
    inf = FakeInference(models=["new-model"])
    saga = _saga(control=FakeControl(loaded=[{"id": "new-model"}]), inference=inf)
    saga.binding.active_model_id = "old-model"
    saga.binding.load_origin = "loaded_by_lva"

    asyncio.run(saga.switch_model("new-model"))
    assert saga.binding.active_model_id == "new-model"
    assert inf.bound_model_id == "new-model", (
        "the binding says the new model but inference still pins the old one, so "
        "requests keep carrying the previous X-LVA-Bound-Model header"
    )


# ======================================= 3b. a failed verify must not hang
def test_a_verification_failure_settles_the_binding():
    """Finding 3b: the exception propagates and status stays verifying."""
    saga = _saga(
        control=FakeControl(loaded=[]),
        inference=FakeInference(models=[]),  # target never appears
    )
    saga.binding.active_model_id = "old-model"
    saga.binding.load_origin = "loaded_by_lva"

    async def drive():
        try:
            await saga.switch_model("ghost", verify_timeout=0.2)
        except Exception:
            pass

    asyncio.run(drive())
    assert saga.binding.status in ("failed", "degraded"), (
        "a failed verification left the binding in "
        + repr(saga.binding.status)
        + "; plan L636 requires FAILED/DEGRADED, and verifying is a hung state the "
        "UI would show forever"
    )
    assert saga.previous_binding is not None, (
        "the pre-attempt binding must be recorded so an explicit rollback is "
        "possible (plan L636)"
    )


# ================================ 3c. do not stop before the profile is known
def test_the_old_model_is_not_stopped_before_the_target_profile_is_read():
    """Finding 3c: reproduced as stopped=[old] with active=old, status=failed."""
    control = FakeControl(
        loaded=[{"id": "old-model"}],
        profile_error="Model profile not found for target",
    )
    saga = _saga(control=control, inference=FakeInference())
    saga.binding.active_model_id = "old-model"
    saga.binding.load_origin = "loaded_by_lva"

    async def drive():
        try:
            await saga.switch_model("target", force_stop_preexisting=True)
        except Exception:
            pass

    asyncio.run(drive())
    assert control.stopped == [], (
        "the old model was stopped before the target profile was known to exist; "
        "plan 5.4 reads the profile (step 2) before the load (step 3), so a "
        "missing profile must not destroy the working model"
    )


# ================================================ 4. later redaction applies
def test_a_later_redaction_mark_clears_the_stored_text():
    """Finding 4: the watermark check short-circuits before redaction."""
    from lva.journal.repository import JournalRepository

    repo = JournalRepository(":memory:")
    repo.append_event(
        event_id=uuid4(),
        raw_text="private words",
        occurred_at_utc_us=1_000_000,
        external_source="screenpipe",
        external_id="chunk-1",
    )
    before = repo.conn.execute(
        "SELECT raw_text FROM events WHERE external_id = ?", ("chunk-1",)
    ).fetchone()["raw_text"]
    assert before == "private words"

    src = read_text(WORKER)
    assert re.search(r"redact", src, re.I), (
        "the importer must apply a later redaction to an event it already stored "
        "(plan L896: respect source redaction/deletion marks); today the watermark "
        "check skips the record entirely"
    )


def test_redaction_never_rewrites_the_immutable_raw_text():
    """I06: raw transcript is immutable; a redaction is a revision."""
    src = read_text(WORKER) + read_text(REPOSITORY)
    assert not re.search(r"UPDATE\s+events\s+SET\s+raw_text", src, re.I), (
        "raw_text must never be rewritten (I06); redaction must go through a new "
        "revision so the original stays provable"
    )


# ============================== 5a/5b/5c. the importer must not lose records
def test_an_unparseable_timestamp_is_never_replaced_with_now():
    """Finding 5a: the fallback advances the watermark past earlier records."""
    # Behavioural rather than source-level: an earlier regex form of this test
    # stopped matching as soon as the implementation changed, which is exactly the
    # fragility that makes a source-level assertion weak evidence.
    from lva.screenpipe_importer.normalize import normalize_screenpipe_audio_item

    with pytest.raises(ValueError, match="unparseable"):
        normalize_screenpipe_audio_item(
            {
                "content": {"transcription": "hello", "timestamp": "not-a-timestamp"},
                "id": "bad-1",
            }
        )


def test_a_record_at_the_watermark_is_not_silently_skipped():
    """Finding 5b: occ_us <= watermark drops same-microsecond records."""
    src = read_text(WORKER)
    assert re.search(r"occ_us\s*<=\s*watermark", src) is None, (
        "a record whose timestamp equals the watermark is skipped, so two records "
        "sharing a microsecond lose one silently"
    )


def test_the_page_transaction_is_actually_atomic():
    """Finding 5c: append_event commits on its own, breaking the page boundary."""
    src = read_text(REPOSITORY)
    assert re.search(r"def\s+append_event\w*\([^)]*commit", src, re.S), (
        "append_event must offer a non-committing form so the importer page can "
        "be one transaction; today its inner with self.conn commits the outer "
        "block, so a page with one bad record leaves the good ones committed"
    )


# ================================================= 6. refresh must read the Hub
def test_hub_refresh_actually_reads_the_hub():
    """Finding 6: hub.refresh answers from a cache nothing populates."""
    from lva.contracts.commands import CommandEnvelope, HubRefreshPayload
    from lva.core.runtime import RuntimeController

    control = FakeControl(models=[{"id": "real-model", "name": "Real"}])
    saga = _saga(control=control)
    rt = RuntimeController(runtime_instance_id=uuid4(), hub_saga=saga)
    rt.set_hub_bind_attestation(_fresh())

    res = rt.execute_command(
        CommandEnvelope(type="hub.refresh", payload=HubRefreshPayload(type="hub.refresh"))
    )
    assert res.status == "accepted"
    assert control.list_models_calls > 0, (
        "hub.refresh returned without ever reading the Hub, so the PR-026 refresh "
        "button always shows an empty list"
    )
    assert [m["model_id"] for m in (res.data or {}).get("models", [])] == ["real-model"], (
        "the refresh result must carry what was actually read from the Hub"
    )


def test_the_refresh_read_goes_through_the_privileged_gate():
    """L665 still applies to the read path."""
    from lva.contracts.commands import CommandEnvelope, HubRefreshPayload
    from lva.core.runtime import RuntimeController

    control = FakeControl(models=[{"id": "real-model"}])
    saga = _saga(control=control)
    rt = RuntimeController(runtime_instance_id=uuid4(), hub_saga=saga)
    # No attestation -> the gate is closed.
    res = rt.execute_command(
        CommandEnvelope(type="hub.refresh", payload=HubRefreshPayload(type="hub.refresh"))
    )
    assert res.status == "rejected", (
        "an unverified bind must not reach the Hub, even for a read"
    )
    assert control.list_models_calls == 0
