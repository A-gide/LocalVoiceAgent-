"""RED: v1.2.1 patch #4 - Standby semantics and managed capture (feeds R13).

Frozen rule (v1.2.1 §3.3):
* Standby means "AI idle AND all LVA-managed reality capture is off".
* Passive turns LVA-managed capture ON (entering the mode IS the recording act).
* Live follows ``record_reality_during_live`` (first-install default: Off).
* Privacy Pause: Core mic off AND LVA-managed capture off.
* External/Unknown Screenpipe is out of scope but must be surfaced separately.
* ``privacy_scope`` must stay ack-driven; never claim verified without an ack.

Current state: entering Standby only stops the Core mic; no managed-capture-off
intent exists and ``record_reality_during_live`` is absent everywhere.
"""
from __future__ import annotations

import pytest

from harness import REPO_ROOT, iter_source_files, read_text
from lva.contracts.enums import Mode, PrivacyScope
from lva.core.runtime import RuntimeController

pytestmark = pytest.mark.red_v121


# ------------------------------------------------------- managed-capture intent
def test_capture_coordinator_can_request_managed_capture_off():
    from lva.core.capture import CaptureCoordinator

    c = CaptureCoordinator()
    api = [n for n in dir(c) if "managed" in n.lower() and "request" in n.lower()]
    assert api, (
        "v1.2.1 §3.3/PR-020: CaptureCoordinator needs a managed-capture-off "
        "intent API so Standby can stop LVA-managed recording; "
        f"available members: {[n for n in dir(c) if not n.startswith('_')]}"
    )


def test_standby_marks_lva_managed_capture_off():
    rt = RuntimeController()
    rt.set_mode(Mode.STANDBY)
    agg = rt.get_state().managed_capture
    assert agg.core_mic_stopped is True, "Standby must stop the Core mic"
    assert agg.managed_screenpipe_stopped is True, (
        "v1.2.1 §3.3: entering Standby must turn ALL LVA-managed reality capture "
        f"off, but managed_screenpipe_stopped={agg.managed_screenpipe_stopped!r}"
    )


def test_standby_is_not_reported_as_privacy_guarantee():
    rt = RuntimeController()
    rt.set_mode(Mode.STANDBY)
    scope = rt.get_state().privacy_scope
    assert scope == PrivacyScope.NOT_PAUSED, (
        "Standby is not a privacy pause; scope must stay NOT_PAUSED so the UI "
        f"does not present Standby as a system-wide privacy guarantee (got {scope})"
    )


def test_privacy_pause_does_not_claim_verified_without_ack():
    rt = RuntimeController()
    rt.set_mode(Mode.PRIVACY_PAUSE)
    scope = rt.get_state().privacy_scope
    assert scope != PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF, (
        "without a managed-capture acknowledgement the scope must stay UNVERIFIED "
        "(v1.2.1 §3.4 / I10)"
    )


# ----------------------------------------------------- live recording setting
def test_record_reality_during_live_setting_exists():
    hits = []
    for path in iter_source_files(["src/lva", "apps/desktop-shell/src-tauri/src"], (".py", ".rs")):
        if "record_reality_during_live" in read_text(path):
            hits.append(str(path.relative_to(REPO_ROOT)))
    assert hits, (
        "v1.2.1 §3.3 requires a 'record_reality_during_live' setting (Live mode, "
        "first-install default Off); it is referenced nowhere in the codebase"
    )


def test_live_defaults_to_no_reality_recording():
    """First install must not silently record reality while Live."""
    from lva.contracts import state as state_mod

    field_names = set()
    for model in vars(state_mod).values():
        fields = getattr(model, "model_fields", None)
        if fields:
            field_names |= set(fields)
    assert "record_reality_during_live" in field_names, (
        "Live-mode reality recording must be an explicit, default-off setting in "
        "the runtime state contract (v1.2.1 §3.3)"
    )


# --------------------------------------------------- external capture surfaced
def test_external_capture_is_reported_separately():
    from lva.core.capture import CaptureCoordinator

    c = CaptureCoordinator()
    c.update_managed_capture_status(managed_stopped=None, external_detected=True)
    scope = c.compute_privacy_scope(Mode.PRIVACY_PAUSE)
    assert scope == PrivacyScope.LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT, (
        "an external recorder must be surfaced explicitly rather than folded into "
        f"the managed scope (got {scope})"
    )