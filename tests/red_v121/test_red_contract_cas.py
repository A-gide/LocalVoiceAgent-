"""RED: v1.2.1 patch #2 - aggregate/object revision CAS (R03a, hardened).

Frozen rule (v1.2.1 搂4.2 / 搂4.4 / 搂4.5).

History
-------
* v1 only checked *field names*.
* R03a-v1 strengthened the checks but had three structural defects found by an
  independent adversarial review: ``_payload_union_members()`` returned ``[]``
  (so two tests could never go green and two others were vacuous), several
  checks were raw substring probes, and two "rejection" assertions were
  satisfied by an unrelated ``INVALID_TRANSITION``.
* R03a-v2 (this file) fixes those: the union is unwrapped correctly, generated
  artifacts are parsed structurally rather than substring-matched, rejections
  must cite the CAS error code and the required aggregate, and positive
  assertions are guarded by ``_require_cas_mechanism()`` so they cannot pass
  merely because the contract ignores the precondition.

Every test here must fail while the repository implements v1.2, and every
failure must name the missing v1.2.1 behaviour.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest

from lva.contracts.commands import CommandEnvelope, CommandPayload, CommandResult
from lva.contracts.enums import ErrorCode
from lva.contracts.state import RuntimeState

pytestmark = pytest.mark.red_v121

REPO_ROOT = Path(__file__).resolve().parents[2]
TS_CONTRACT = REPO_ROOT / "apps" / "desktop-ui" / "src" / "generated" / "lva-ipc.ts"
RS_CONTRACT = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src" / "generated" / "lva_ipc.rs"
JSON_SCHEMA = REPO_ROOT / "schemas" / "lva-ipc-v1.json"

# ---- v1.2.1 搂4.4 frozen command table --------------------------------------
CAS_REQUIRED: dict[str, str] = {
    "runtime.set_mode": "runtime_control",
    "runtime.restore_mode": "runtime_control",
    "hub.bind_model": "hub_binding",
    "hub.sleep_bound_model": "hub_binding",
    "memory.correct": "memory_event",
    "memory.hard_delete": "memory_event",
}

# Settings commands carry a `settings` aggregate precondition (frozen §4.4 line
# 463), but the frozen authority matrix (line 293) gives Secrets to the **Rust
# settings/OS protection layer**, and §4.2 line 397 places `settings_revision`
# in the Rust public settings DTO rather than the global RuntimeState CAS.
# They are therefore NOT enforced by the Python dispatcher and are deliberately
# excluded from the CAS_REQUIRED matrix below; see
# test_settings_commands_are_boundary_owned_not_core_enforced.
SETTINGS_AGGREGATE_COMMANDS: tuple[str, ...] = (
    "settings.update_public",
    "settings.set_secret",
    "settings.clear_secret",
)
CAS_FREE: tuple[str, ...] = (
    "runtime.get_snapshot",
    "turn.send_text",
    "turn.cancel",
    "memory.search",
    "service.retry",
    "diagnostics.export_redacted",
    # PR-012: an inbound attestation report is not a control action, so it carries
    # no CAS precondition -- it is the very thing that can *lift* the control gate.
    "hub.attest_bind",
)

# Hub control commands are gated by the bind attestation (plan L665), not by the
# CAS matrix: a stale hub_binding revision is a different failure from an unproven
# loopback bind.  They are listed separately so the CAS matrix stays about CAS.
HUB_CONTROL_COMMANDS: tuple[str, ...] = (
    "hub.refresh",
    "hub.bind_model",
    "hub.sleep_bound_model",
)
ALL_COMMANDS: tuple[str, ...] = (
    tuple(CAS_REQUIRED)
    + SETTINGS_AGGREGATE_COMMANDS
    + HUB_CONTROL_COMMANDS
    + CAS_FREE
)

# command -> the payload class that must carry it (exact, not "some class")
PAYLOAD_CLASS: dict[str, str] = {
    "runtime.get_snapshot": "RuntimeGetSnapshotPayload",
    "runtime.set_mode": "RuntimeSetModePayload",
    "runtime.restore_mode": "RuntimeRestoreModePayload",
    "turn.send_text": "TurnSendTextPayload",
    "turn.cancel": "TurnCancelPayload",
    "hub.refresh": "HubRefreshPayload",
    "hub.bind_model": "HubBindModelPayload",
    "hub.sleep_bound_model": "HubSleepBoundModelPayload",
    "hub.attest_bind": "HubAttestBindPayload",
    "settings.update_public": "SettingsUpdatePublicPayload",
    "settings.set_secret": "SettingsSetSecretPayload",
    "settings.clear_secret": "SettingsClearSecretPayload",
    "memory.search": "MemorySearchPayload",
    "memory.correct": "MemoryCorrectPayload",
    "memory.hard_delete": "MemoryHardDeletePayload",
    "service.retry": "ServiceRetryPayload",
    "diagnostics.export_redacted": "DiagnosticsExportRedactedPayload",
}
CLASS_TO_COMMAND: dict[str, str] = {v: k for k, v in PAYLOAD_CLASS.items()}

# Frozen §4.5 defines exactly ONE code for a precondition mismatch. The gate must
# accept only that code: accepting an unfrozen alternative would let a future
# implementation introduce an error code the plan does not define.
CAS_ERROR_CODES = ("STALE_REVISION",)
NON_CAS_REJECTION_ALLOWLIST = (
    "PASSIVE_PROVIDER_FORBIDDEN",
    "INVALID_TRANSITION",
    "JOURNAL_BUSY",
    "HUB_UNAVAILABLE",
    "PROVIDER_DISCONNECTED",
)

MINIMAL_PAYLOAD: dict[str, dict[str, Any]] = {
    "runtime.get_snapshot": {},
    "runtime.set_mode": {"mode": "standby"},
    "runtime.restore_mode": {},
    "turn.send_text": {"text": "hi"},
    "turn.cancel": {},
    "hub.refresh": {},
    "hub.bind_model": {"model_id": "m1"},
    "hub.sleep_bound_model": {},
    "settings.update_public": {},
    "settings.set_secret": {"secret_type": "cloud_api_key", "secret_value": "x"},
    "settings.clear_secret": {"secret_type": "cloud_api_key"},
    "memory.search": {"query": "q"},
    "memory.correct": {"event_id": "11111111-1111-1111-1111-111111111111", "corrected_text": "x", "reason": "r"},
    "memory.hard_delete": {"event_ids": ["11111111-1111-1111-1111-111111111111"], "reason_code": "user_request"},
    "service.retry": {"service_name": "screenpipe"},
    "diagnostics.export_redacted": {},
}

SEED_EVENT_ID = "11111111-1111-1111-1111-111111111111"


# ------------------------------------------------------------------ helpers
def _payload_for(command: str) -> dict[str, Any]:
    """Build a discriminated payload for a command.

    The ``type`` discriminator must be present or pydantic rejects the payload
    and every execution test would fail for the wrong reason.
    """
    if command == "hub.attest_bind":
        # PR-012: the attestation report carries a verdict, so its minimal payload
        # is a fresh loopback attestation rather than an empty body.
        from datetime import datetime, timedelta, timezone

        from lva.contracts.state import HubBindAttestation

        now = datetime.now(timezone.utc)
        return {
            "type": command,
            "attestation": HubBindAttestation(
                status="VERIFIED_LOOPBACK",
                reason_code=None,
                checked_at=now,
                attestation_id="payload-fresh-loopback",
                revalidate_after=now + timedelta(minutes=5),
            ).model_dump(mode="json"),
        }
    return {"type": command, **MINIMAL_PAYLOAD.get(command, {})}


def _fail(msg: str) -> None:
    pytest.fail(msg, pytrace=False)


class _Omitted:
    """Sentinel: distinguishes 'key absent' from 'key present and null'."""

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "<omitted>"


_OMITTED = _Omitted()


def _make_cmd(**kwargs: Any) -> CommandEnvelope:
    try:
        return CommandEnvelope.model_validate(kwargs)
    except Exception as exc:  # noqa: BLE001
        _fail(f"v1.2.1 command envelope rejected by the contract: {type(exc).__name__}: {exc}")


def _payload_union_members() -> list[type]:
    """Unwrap ``Annotated[Union[...], FieldInfo]`` correctly.

    ``get_args(CommandPayload)`` yields ``(Union[...], FieldInfo)``; the union
    members are one level deeper. The naive one-level filter returns ``[]``.
    """
    outer = get_args(CommandPayload)
    if not outer:
        _fail("CommandPayload is not an Annotated union")
    inner = get_args(outer[0])
    members = [m for m in inner if hasattr(m, "model_fields")]
    if not members:
        _fail("CommandPayload union has no payload members")
    return members


def _python_command_types() -> set[str]:
    out: set[str] = set()
    for m in _payload_union_members():
        lit = m.model_fields.get("type")
        if lit is not None:
            out |= set(get_args(lit.annotation))
    return out


def _dispatcher():
    from lva.core.runtime import RuntimeController
    from lva.journal.repository import JournalRepository

    return RuntimeController(journal=JournalRepository(":memory:"))


def _grant_verified_loopback(rt: Any) -> None:
    """Open the Hub control gate with a fresh VERIFIED_LOOPBACK attestation.

    PR-012: Hub control requires a *fresh* loopback verdict (plan L665), which is
    independent of the CAS matrix.  Tests that exercise CAS semantics on Hub
    commands call this so a gate denial cannot be mistaken for a CAS rejection.
    """
    from datetime import datetime, timedelta, timezone

    from lva.contracts.state import HubBindAttestation

    now = datetime.now(timezone.utc)
    rt.set_hub_bind_attestation(
        HubBindAttestation(
            status="VERIFIED_LOOPBACK",
            reason_code=None,
            checked_at=now,
            attestation_id="test-fresh-loopback",
            revalidate_after=now + timedelta(minutes=5),
        )
    )


def _rev(rt: Any, aggregate: str) -> int:
    """Read an aggregate revision; fail loudly rather than returning None."""
    name = f"{aggregate}_revision"
    if not hasattr(rt, name):
        _fail(f"RuntimeController has no {name} (v1.2.1 搂4.2 aggregate CAS)")
    value = getattr(rt, name)
    if not isinstance(value, int):
        _fail(f"RuntimeController.{name} must be an int, got {type(value).__name__}")
    return value


def _require_cas_mechanism() -> None:
    if "precondition" not in CommandEnvelope.model_fields:
        _fail("CAS mechanism absent: CommandEnvelope has no 'precondition' field")
    _rev(_dispatcher(), "runtime_control")


def _seed_event(rt: Any) -> str:
    from uuid import UUID

    journal = rt._journal
    if journal is None:
        _fail("dispatcher must expose a journal for object-CAS tests")
    try:
        journal.append_event(
            event_id=UUID(SEED_EVENT_ID),
            raw_text="seed",
            session_id=None,
            turn_sequence=None,
            speaker="user",
            source="test",
            domain=None,
        )
    except Exception as exc:  # noqa: BLE001
        _fail(f"could not seed a Journal event: {type(exc).__name__}: {exc}")
    return SEED_EVENT_ID


def _rejection_is_cas(res: Any) -> tuple[bool, str]:
    if res.status != "rejected":
        return False, f"status={res.status}"
    if res.error is None:
        return False, "rejected with no error envelope"
    if res.error.code not in CAS_ERROR_CODES:
        return False, f"code={res.error.code}"
    return True, "ok"


# ------------------------------------------------- generated-artifact parsers
def _read(path: Path) -> str:
    if not path.exists():
        _fail(f"generated artifact missing: {path.relative_to(REPO_ROOT)}")
    return path.read_text(encoding="utf-8", errors="replace")


def _ts_interface_fields(name: str) -> set[str]:
    text = _read(TS_CONTRACT)
    m = re.search(rf"export interface {re.escape(name)}\s*\{{(.*?)\n\s*\}}", text, re.S)
    if not m:
        _fail(f"generated TS has no interface {name}")
    return set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\??:", m.group(1), re.M))


def _rs_struct_fields(name: str) -> set[str]:
    """Rust *wire* field names for a struct, as they appear on the wire.

    Approved amendment (owner decision), revision 2. Two earlier forms were
    rejected:

    * v1 matched ``^\\s*pub\\s+([a-z_][a-z0-9_]*)\\s*:``, which cannot match a
      raw identifier, so a field named ``type`` (necessarily ``pub r#type``)
      was silently dropped and the field set could never equal Python's.
    * v2 added ``(?:r#)?``, which fixed that but still compared the Rust
      *identifier* to the Python *field name*. The frozen plan (line 363) pins
      ``typify`` as the Rust generator, and a pinned generator may legitimately
      emit ``pub command_type`` + ``#[serde(rename = "type")]`` instead. What
      the contract actually requires is that the **serialized** name matches.

    This version reads the wire name: ``#[serde(rename = "X")]`` wins, otherwise
    the identifier with any ``r#`` prefix stripped. It is generator-agnostic.
    """
    text = _read(RS_CONTRACT)
    m = re.search(rf"pub struct {re.escape(name)}\s*\{{(.*?)\n\s*\}}", text, re.S)
    if not m:
        _fail(f"generated Rust has no struct {name}")

    wire: set[str] = set()
    pending_rename: str | None = None
    for line in m.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("#[serde("):
            found = re.search(r'rename\s*=\s*"([^"]+)"', stripped)
            pending_rename = found.group(1) if found else pending_rename
            continue
        if stripped.startswith("#["):
            continue
        found = re.match(r"pub\s+(?:r#)?([A-Za-z_][A-Za-z0-9_]*)\s*:", stripped)
        if found:
            wire.add(pending_rename or found.group(1))
            pending_rename = None
    if not wire:
        _fail(f"could not extract any wire field from generated Rust struct {name}")
    return wire


def _json_def(name: str) -> dict:
    schema = json.loads(_read(JSON_SCHEMA))
    defs = schema.get("$defs", {})
    if name not in defs:
        _fail(f"JSON schema has no $defs.{name}")
    return defs[name]


def _json_props(name: str) -> set[str]:
    return set(_json_def(name).get("properties", {}))


def _json_enum(name: str) -> set[str]:
    return set(_json_def(name).get("enum", []))


def _ts_error_codes() -> set[str]:
    text = _read(TS_CONTRACT)
    m = re.search(r"export type ErrorCode\s*=\s*(.*?);", text, re.S)
    if not m:
        _fail("generated TS has no ErrorCode union")
    # Accept either quote style: the pinned json-schema-to-typescript emits
    # double quotes, the previous hand-written template used single quotes.
    return set(re.findall(r"['\"]([A-Z_]+)['\"]", m.group(1)))


def _ts_command_types() -> set[str]:
    """Only the literals of interfaces that are members of CommandPayload."""
    text = _read(TS_CONTRACT)
    # The pinned generator names the union after the property (`Payload`), not
    # `CommandPayload`, so locate it by membership of the known payload classes.
    block = None
    for cand in re.finditer(r"export type (\w+)\s*=\s*(.*?);", text, re.S):
        members = set(re.findall(r"\|\s*([A-Za-z_][A-Za-z0-9_]*)", cand.group(2)))
        if members & set(PAYLOAD_CLASS.values()):
            block = cand
            break
    if not block:
        _fail("generated TS has no union containing the command payload interfaces")
    member_names = set(re.findall(r"\|\s*([A-Za-z_][A-Za-z0-9_]*)", block.group(2)))
    if not member_names:
        _fail("generated TS CommandPayload union lists no members")
    out: set[str] = set()
    for name in member_names:
        m = re.search(rf"export interface {re.escape(name)}\s*\{{(.*?)\n\s*\}}", text, re.S)
        if not m:
            continue
        out |= set(re.findall(r"type:\s*['\"]([a-z_]+\.[a-z_]+)['\"]", m.group(1)))
    return out


def _rs_error_codes() -> set[str]:
    text = _read(RS_CONTRACT)
    m = re.search(r"pub enum ErrorCode\s*\{(.*?)\n\s*\}", text, re.S)
    if not m:
        _fail("generated Rust has no ErrorCode enum")
    body = m.group(1)
    return set(re.findall(r"^\s*([A-Z][A-Z0-9_]+)\s*,", body, re.M)) | set(
        re.findall(r'#\[serde\(rename = "([A-Z_]+)"\)\]', body)
    )


# ============================================================ rule 1: state
def test_runtime_state_has_three_revisions():
    missing = [
        f
        for f in ("snapshot_version", "runtime_control_revision", "hub_binding_revision")
        if f not in RuntimeState.model_fields
    ]
    if missing:
        _fail(f"v1.2.1 搂4.2 requires RuntimeState.{missing}; present: {sorted(RuntimeState.model_fields)}")


def test_runtime_state_drops_global_state_version():
    if "state_version" in RuntimeState.model_fields:
        _fail("v1.2.1 搂4.2 replaces the global CAS field 'state_version' with aggregate revisions")


def test_hub_bind_attestation_is_a_model_not_a_scalar():
    if "hub_bind_attestation" not in RuntimeState.model_fields:
        _fail("v1.2.1 搂4.1 requires RuntimeState.hub_bind_attestation (HubBindAttestation)")
    ann = RuntimeState.model_fields["hub_bind_attestation"].annotation
    if not any(hasattr(a, "model_fields") for a in get_args(ann)):
        _fail(f"hub_bind_attestation must be a HubBindAttestation model (or None), got {ann!r}")


def test_generated_runtime_state_matches_python_fields():
    py = set(RuntimeState.model_fields)
    ts = _ts_interface_fields("RuntimeState")
    rs = _rs_struct_fields("RuntimeState")
    js = _json_props("RuntimeState")
    problems = []
    if ts != py:
        problems.append(f"TS missing={sorted(py - ts)} extra={sorted(ts - py)}")
    if rs != py:
        problems.append(f"Rust missing={sorted(py - rs)} extra={sorted(rs - py)}")
    if js != py:
        problems.append(f"JSON missing={sorted(py - js)} extra={sorted(js - py)}")
    if problems:
        _fail("RuntimeState drifted between Python and the generated artifacts: " + "; ".join(problems))


# ===================================================== rule 2: precondition
def test_precondition_is_optional_with_none_default():
    field = CommandEnvelope.model_fields.get("precondition")
    if field is None:
        _fail("CommandEnvelope has no 'precondition' field")
    if field.is_required():
        _fail("precondition must be optional; it is currently a required field")
    if field.default is not None:
        _fail(f"precondition must default to None, got {field.default!r}")


def test_precondition_is_discriminated_on_the_aggregate_field():
    """Gate the *published contract* and its *behaviour*, not a Pydantic internal.

    Approved amendment (owner decision), revision 2. Two earlier forms were
    rejected:

    * v1 read ``field.annotation.__metadata__``, which pydantic 2.13.5 never
      produces for a field (it unwraps ``Annotated`` onto the ``FieldInfo``),
      so the test failed even against a correct implementation.
    * v2 asserted ``FieldInfo.discriminator``, which works but pins an internal
      shape: it silently requires ``None`` to be a *union member* rather than a
      ``| None`` on the field. That is a Pydantic artefact, not a frozen
      requirement.

    Frozen §4.4 requires only: optional, typed, discriminated on ``aggregate``,
    with the four documented tag forms. This version gates exactly that -- the
    discriminator is checked where it is *published* (the generated JSON Schema)
    plus four behavioural cases, and no Python declaration form is pinned.
    """
    from pydantic import ValidationError

    field = CommandEnvelope.model_fields.get("precondition")
    if field is None:
        _fail("CommandEnvelope has no 'precondition' field")

    # 1. optional, defaulting to None (frozen §4.4: precondition is optional)
    if field.is_required() or field.default is not None:
        _fail(
            "precondition must be optional with default None "
            f"(required={field.is_required()}, default={field.default!r})"
        )

    # 2. the published contract declares the discriminator.
    #    Checked on the generated JSON Schema rather than on the Python object,
    #    so any implementation that produces a correctly discriminated contract
    #    passes, whatever its declaration spelling.
    pre_schema = _json_def("CommandEnvelope").get("properties", {}).get("precondition")
    if pre_schema is None:
        _fail("JSON Schema CommandEnvelope has no 'precondition' property")
    discriminators = [
        branch["discriminator"]
        for branch in (pre_schema.get("anyOf") or [])
        if isinstance(branch, dict) and "discriminator" in branch
    ]
    if not discriminators:
        _fail(f"JSON Schema must declare a discriminator for precondition; got {pre_schema!r}")
    if not any(d.get("propertyName") == "aggregate" for d in discriminators):
        _fail(
            "JSON Schema discriminator.propertyName must be 'aggregate', got "
            f"{[d.get('propertyName') for d in discriminators]!r}"
        )
    mapping = {}
    for d in discriminators:
        mapping.update(d.get("mapping") or {})
    expected_tags = {"runtime_control", "hub_binding", "settings", "memory_event"}
    if set(mapping) != expected_tags:
        _fail(f"discriminator.mapping must cover the four frozen tags; got {sorted(mapping)}")

    # 3. behaviour -- the four cases frozen §4.4 implies.
    def _validate(precondition_value: Any) -> Any:
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "type": "runtime.set_mode",
            "payload": _payload_for("runtime.set_mode"),
        }
        if precondition_value is not _OMITTED:
            payload["precondition"] = precondition_value
        return CommandEnvelope.model_validate(payload)

    # (a) omitted -> allowed, resolves to None
    if getattr(_validate(_OMITTED), "precondition", "missing") is not None:
        _fail("an omitted precondition must be allowed and resolve to None")

    # (b) explicit None -> allowed
    if getattr(_validate(None), "precondition", "missing") is not None:
        _fail("an explicit null precondition must be allowed")

    # (c) unknown tag -> rejected
    try:
        _validate({"aggregate": "not_an_aggregate", "revision": 1})
    except ValidationError:
        pass
    else:
        _fail("an unknown precondition aggregate was accepted; the union is not discriminated")

    # (d) known tag -> resolves to the matching variant, revision preserved
    pre = getattr(_validate({"aggregate": "runtime_control", "revision": 7}), "precondition", None)
    if pre is None:
        _fail("a known precondition aggregate was dropped instead of resolving")
    if pre.aggregate != "runtime_control" or pre.revision != 7:
        _fail(f"a known precondition aggregate must resolve with its revision, got {pre!r}")


def test_precondition_accepts_each_frozen_aggregate_on_its_own_command():
    if "precondition" not in CommandEnvelope.model_fields:
        _fail("CommandEnvelope has no 'precondition' field")
    probes = {
        "runtime_control": "runtime.set_mode",
        "hub_binding": "hub.bind_model",
        "settings": "settings.update_public",
    }
    for aggregate, command in probes.items():
        cmd = _make_cmd(
            schema_version="1.0",
            type=command,
            payload=_payload_for(command),
            precondition={"aggregate": aggregate, "revision": 7},
        )
        pre = getattr(cmd, "precondition", None)
        if pre is None:
            _fail(f"precondition was dropped for aggregate {aggregate}")
        if pre.aggregate != aggregate:
            _fail(f"precondition.aggregate round-trip failed for {aggregate}")
        if pre.revision != 7:
            _fail(f"precondition.revision round-trip failed for {aggregate} (got {pre.revision!r})")


def test_precondition_accepts_memory_event_object_form():
    if "precondition" not in CommandEnvelope.model_fields:
        _fail("CommandEnvelope has no 'precondition' field")
    cmd = _make_cmd(
        schema_version="1.0",
        type="memory.correct",
        payload=_payload_for("memory.correct"),
        precondition={"aggregate": "memory_event", "resource_id": SEED_EVENT_ID, "revision": 3},
    )
    pre = getattr(cmd, "precondition", None)
    if pre is None or pre.aggregate != "memory_event":
        _fail("memory_event precondition must round-trip")
    if getattr(pre, "resource_id", None) != SEED_EVENT_ID:
        _fail("memory_event precondition must carry the target event id as resource_id")


def test_precondition_rejects_unknown_aggregate():
    from pydantic import ValidationError

    if "precondition" not in CommandEnvelope.model_fields:
        _fail("CommandEnvelope has no 'precondition' field, so an unknown aggregate cannot be rejected")
    try:
        CommandEnvelope.model_validate(
            {
                "schema_version": "1.0",
                "type": "runtime.set_mode",
                "payload": {"type": "runtime.set_mode", "mode": "live"},
                "precondition": {"aggregate": "not_an_aggregate", "revision": 1},
            }
        )
    except ValidationError:
        return
    _fail("an unknown precondition aggregate was accepted; the union must be discriminated")


def test_command_envelope_drops_expected_state_version():
    if "expected_state_version" in CommandEnvelope.model_fields:
        _fail("v1.2.1 搂4.4 removes the global 'expected_state_version' CAS field")


def test_generated_command_envelope_carries_precondition_not_expected_state_version():
    py = set(CommandEnvelope.model_fields)
    problems = []
    for label, fields in (
        ("TS", _ts_interface_fields("CommandEnvelope")),
        ("Rust", _rs_struct_fields("CommandEnvelope")),
        ("JSON", _json_props("CommandEnvelope")),
    ):
        if "precondition" not in fields:
            problems.append(f"{label}: no precondition")
        if "expected_state_version" in fields:
            problems.append(f"{label}: still has expected_state_version")
        if fields != py:
            problems.append(f"{label}: fields differ from Python ({sorted(fields ^ py)})")
    if problems:
        _fail("CommandEnvelope drifted across languages: " + "; ".join(problems))


# ================================================== rule 3: error codes
def test_stale_revision_error_code_exists():
    if not hasattr(ErrorCode, "STALE_REVISION"):
        _fail("v1.2.1 搂4.5 replaces STALE_STATE with STALE_REVISION")


def test_stale_state_error_code_removed():
    if hasattr(ErrorCode, "STALE_STATE"):
        _fail("v1.2.1 搂4.5 removes STALE_STATE in favour of STALE_REVISION")


def test_hub_bind_unverified_error_code_exists():
    if not hasattr(ErrorCode, "HUB_BIND_UNVERIFIED"):
        _fail("v1.2.1 搂5.3/搂5.8 requires HUB_BIND_UNVERIFIED")


def test_json_schema_error_code_enum_contains_v121_codes():
    codes = _json_enum("ErrorCode")
    missing = [c for c in ("STALE_REVISION", "HUB_BIND_UNVERIFIED") if c not in codes]
    if missing:
        _fail(f"JSON schema $defs.ErrorCode.enum is missing {missing} (enum has {len(codes)} codes)")


def test_error_code_set_is_identical_across_python_ts_rust_json():
    py = {c.value for c in ErrorCode}
    ts = _ts_error_codes()
    rs = _rs_error_codes()
    js = _json_enum("ErrorCode")
    problems = []
    for label, other in (("TS", ts), ("Rust", rs), ("JSON", js)):
        if not other:
            problems.append(f"{label}: empty set (parser or artifact broken)")
        elif other != py:
            problems.append(f"{label} missing={sorted(py - other)} extra={sorted(other - py)}")
    if problems:
        _fail("ErrorCode drifted across languages: " + "; ".join(problems))


# ============================== rule 4: payload union and command matrix
def test_payload_union_has_exactly_the_frozen_commands():
    members = _payload_union_members()
    names = {m.__name__ for m in members}
    expected = set(PAYLOAD_CLASS.values())
    if names != expected:
        _fail(f"CommandPayload union mismatch: missing={sorted(expected - names)} extra={sorted(names - expected)}")


def test_each_payload_declares_its_own_command_literal():
    """A payload whose literal names a *different* valid command is still wrong."""
    problems = []
    for m in _payload_union_members():
        expected_command = CLASS_TO_COMMAND.get(m.__name__)
        if expected_command is None:
            continue
        lit = m.model_fields.get("type")
        if lit is None:
            problems.append(f"{m.__name__}: no type literal")
            continue
        values = get_args(lit.annotation)
        if values != (expected_command,):
            problems.append(f"{m.__name__}: declares {values!r}, expected {expected_command!r}")
    if problems:
        _fail("payload/command literal mismatch: " + "; ".join(problems))


def test_python_command_types_match_the_frozen_list():
    py = _python_command_types()
    if py != set(ALL_COMMANDS):
        _fail(f"Python command types mismatch: missing={sorted(set(ALL_COMMANDS) - py)} extra={sorted(py - set(ALL_COMMANDS))}")


def test_ts_command_types_match_python():
    py = _python_command_types()
    ts = _ts_command_types()
    if not ts:
        _fail("generated TS CommandPayload union yielded no command literals")
    if ts != py:
        _fail(f"command types drifted: TS missing={sorted(py - ts)} extra={sorted(ts - py)}")


def _run_cas_matrix(build_precondition) -> None:
    """Shared driver: report BOTH missing payloads and CAS-behaviour gaps.

    A command whose payload class does not exist yet cannot exercise the CAS
    matrix at all. That is a distinct gap and must be reported as such, rather
    than aborting the whole test inside envelope construction.
    """
    rt = _dispatcher()
    unconstructible: list[str] = []
    problems: list[str] = []
    exercised = 0
    for command, aggregate in CAS_REQUIRED.items():
        kwargs: dict[str, Any] = {
            "schema_version": "1.0",
            "type": command,
            "payload": _payload_for(command),
        }
        precondition = build_precondition(command, aggregate)
        if precondition is not None:
            kwargs["precondition"] = precondition
        try:
            cmd = CommandEnvelope.model_validate(kwargs)
        except Exception as exc:  # noqa: BLE001
            unconstructible.append(f"{command} ({type(exc).__name__})")
            continue
        exercised += 1
        res = rt.execute_command(cmd)
        ok, why = _rejection_is_cas(res)
        if not ok:
            problems.append(f"{command} needs {aggregate}: {why}")

    msgs = []
    if unconstructible:
        msgs.append(f"CAS-required commands have no usable payload yet, matrix not exercised: {unconstructible}")
    if problems:
        msgs.append(f"CAS not enforced ({exercised} exercised): " + "; ".join(problems))
    if not msgs and exercised < len(CAS_REQUIRED):
        msgs.append(f"only {exercised}/{len(CAS_REQUIRED)} CAS commands were exercised")
    if msgs:
        _fail(" | ".join(msgs))


def test_cas_required_commands_reject_a_missing_precondition():
    _run_cas_matrix(lambda command, aggregate: None)


def test_cas_required_commands_reject_a_wrong_aggregate():
    _run_cas_matrix(
        lambda command, aggregate: {
            "aggregate": "settings" if aggregate != "settings" else "runtime_control",
            "revision": 1,
        }
    )


def test_cas_rejection_names_the_required_aggregate():
    rt = _dispatcher()
    cmd = _make_cmd(
        schema_version="1.0",
        type="runtime.set_mode",
        payload=_payload_for("runtime.set_mode"),
    )
    res = rt.execute_command(cmd)
    ok, why = _rejection_is_cas(res)
    if not ok:
        _fail(f"a missing precondition must produce a CAS rejection, got {why}")
    details = res.error.redacted_details or {}
    if details.get("aggregate") != "runtime_control":
        _fail(f"the CAS rejection must name the required aggregate; details={details}")


def test_cas_free_commands_are_not_cas_rejected():
    _require_cas_mechanism()
    rt = _dispatcher()
    # PR-012: Hub control commands are gated by the bind attestation (plan L665),
    # not by CAS.  This test is about CAS, so the gate is opened explicitly to
    # keep the two failure modes from being conflated.
    _grant_verified_loopback(rt)
    problems = []
    for command in CAS_FREE:
        cmd = _make_cmd(schema_version="1.0", type=command, payload=_payload_for(command))
        res = rt.execute_command(cmd)
        if res.status in ("applied", "accepted"):
            continue
        if res.error is not None and res.error.code in NON_CAS_REJECTION_ALLOWLIST:
            continue
        problems.append(f"{command}: status={res.status} code={res.error.code if res.error else None}")
    if problems:
        _fail("CAS-free commands were rejected for a CAS reason: " + "; ".join(problems))


# ================================ rule 5: valid / stale execution semantics
def _apply_one_valid_mode_change(rt: Any) -> int:
    """Advance runtime_control_revision so a genuinely stale value exists."""
    current = _rev(rt, "runtime_control")
    cmd = _make_cmd(
        schema_version="1.0",
        type="runtime.set_mode",
        payload={"type": "runtime.set_mode", "mode": "live"},
        precondition={"aggregate": "runtime_control", "revision": current},
    )
    res = rt.execute_command(cmd)
    if res.status != "applied":
        _fail(f"could not establish a baseline: valid mode change was {res.status} ({res.error})")
    return current


def test_valid_revision_applies_and_bumps_only_its_aggregate():
    rt = _dispatcher()
    control_before = _rev(rt, "runtime_control")
    hub_before = _rev(rt, "hub_binding")
    cmd = _make_cmd(
        schema_version="1.0",
        type="runtime.set_mode",
        payload={"type": "runtime.set_mode", "mode": "live"},
        precondition={"aggregate": "runtime_control", "revision": control_before},
    )
    res = rt.execute_command(cmd)
    if res.status != "applied":
        _fail(f"a valid revision must apply, got {res.status} ({res.error})")
    if _rev(rt, "runtime_control") <= control_before:
        _fail("a committable mode change must bump runtime_control_revision")
    if _rev(rt, "hub_binding") != hub_before:
        _fail("a mode change must not touch hub_binding_revision")


def test_valid_hub_binding_revision_applies_and_bumps_hub_binding():
    rt = _dispatcher()
    # PR-012: a valid CAS revision is necessary but not sufficient -- Hub control
    # also needs a fresh VERIFIED_LOOPBACK attestation (plan L665).  Grant one so
    # this test measures the CAS rule it is named for.
    _grant_verified_loopback(rt)
    before = _rev(rt, "hub_binding")
    control_before = _rev(rt, "runtime_control")
    cmd = _make_cmd(
        schema_version="1.0",
        type="hub.bind_model",
        payload=_payload_for("hub.bind_model"),
        precondition={"aggregate": "hub_binding", "revision": before},
    )
    res = rt.execute_command(cmd)
    if res.status != "applied":
        _fail(f"a valid hub_binding revision must apply, got {res.status} ({res.error})")
    if _rev(rt, "hub_binding") <= before:
        _fail("a committed model binding must bump hub_binding_revision")
    if _rev(rt, "runtime_control") != control_before:
        _fail("a hub binding change must not bump runtime_control_revision")


def test_settings_commands_are_boundary_owned_not_core_enforced():
    """Settings CAS is enforced at the Rust settings boundary, not in Core.

    Approved amendment (owner decision). The original test asserted
    ``rt.settings_revision`` on the Python ``RuntimeController``. That conflicts
    with the frozen plan on two counts:

    * authority matrix (line 293): Secrets are owned by the **Rust settings/OS
      protection layer** (write-only update + public status DTO); the anti-goal
      is returning plaintext to the WebView. Enforcing settings CAS in Core
      would put ``secret_value`` handling in the Python dispatcher.
    * §4.2 line 397: ``settings_revision`` is carried by the **Rust public
      settings DTO** and is explicitly *not* part of the global RuntimeState CAS.

    So the contract-level requirements are asserted here, and the revision is
    required to be absent from the global snapshot.
    """
    # 1. the settings commands exist and carry the `settings` aggregate tag.
    py_types = _python_command_types()
    missing = [c for c in SETTINGS_AGGREGATE_COMMANDS if c not in py_types]
    if missing:
        _fail(f"frozen §4.4 lists settings commands that the contract lacks: {missing}")

    # 2. `settings_revision` must NOT enter the global RuntimeState CAS.
    if "settings_revision" in RuntimeState.model_fields:
        _fail("§4.2 line 397: settings_revision must not be part of the global RuntimeState CAS")
    for label, fields in (
        ("TS", _ts_interface_fields("RuntimeState")),
        ("Rust", _rs_struct_fields("RuntimeState")),
        ("JSON", _json_props("RuntimeState")),
    ):
        if "settings_revision" in fields:
            _fail(f"§4.2 line 397: {label} RuntimeState must not carry settings_revision")

    # 3. Core must not expose a settings CAS counter at all.
    rt = _dispatcher()
    if hasattr(rt, "settings_revision"):
        _fail(
            "RuntimeController must not own settings_revision; the frozen authority "
            "matrix (line 293) gives Secrets to the Rust settings/OS protection layer"
        )


def test_stale_revision_is_rejected_and_leaves_state_and_revision_unchanged():
    rt = _dispatcher()
    stale = _apply_one_valid_mode_change(rt)      # stale is now genuinely behind
    mode_before = rt.mode
    control_before = _rev(rt, "runtime_control")

    cmd = _make_cmd(
        schema_version="1.0",
        type="runtime.set_mode",
        payload={"type": "runtime.set_mode", "mode": "privacy_pause"},
        precondition={"aggregate": "runtime_control", "revision": stale},
    )
    res = rt.execute_command(cmd)
    ok, why = _rejection_is_cas(res)
    if not ok:
        _fail(f"a stale revision must be rejected with a CAS error, got {why}")
    if rt.mode != mode_before:
        _fail("a rejected stale command must not mutate state")
    if _rev(rt, "runtime_control") != control_before:
        _fail("a rejected stale command must not bump the aggregate revision")


def test_stale_error_returns_current_aggregate_revision():
    rt = _dispatcher()
    stale = _apply_one_valid_mode_change(rt)
    current = _rev(rt, "runtime_control")
    cmd = _make_cmd(
        schema_version="1.0",
        type="runtime.set_mode",
        payload={"type": "runtime.set_mode", "mode": "live"},
        precondition={"aggregate": "runtime_control", "revision": stale},
    )
    res = rt.execute_command(cmd)
    ok, why = _rejection_is_cas(res)
    if not ok:
        _fail(f"expected a CAS rejection, got {why}")
    details = res.error.redacted_details or {}
    if details.get("aggregate") != "runtime_control":
        _fail(f"stale error must name the aggregate; details={details}")
    if details.get("current_revision") != current:
        _fail(f"stale error must return the current revision ({current}); details={details}")


# ============================== rule 4 (memory): object revision semantics
def test_memory_correct_requires_the_event_revision():
    rt = _dispatcher()
    _seed_event(rt)
    cmd = _make_cmd(
        schema_version="1.0",
        type="memory.correct",
        payload=_payload_for("memory.correct"),
    )
    res = rt.execute_command(cmd)
    ok, why = _rejection_is_cas(res)
    if not ok:
        _fail(
            "memory.correct on an EXISTING event must still require the target event's "
            f"current_revision (object CAS); got {why}"
        )


def test_memory_correct_with_matching_event_revision_is_applied():
    _require_cas_mechanism()
    rt = _dispatcher()
    event_id = _seed_event(rt)
    cmd = _make_cmd(
        schema_version="1.0",
        type="memory.correct",
        payload=_payload_for("memory.correct"),
        precondition={"aggregate": "memory_event", "resource_id": event_id, "revision": 0},
    )
    res = rt.execute_command(cmd)
    if res.status != "applied":
        _fail(f"a matching event revision must apply, got {res.status} ({res.error})")


def test_memory_correct_with_stale_event_revision_is_rejected():
    rt = _dispatcher()
    event_id = _seed_event(rt)
    cmd = _make_cmd(
        schema_version="1.0",
        type="memory.correct",
        payload=_payload_for("memory.correct"),
        precondition={"aggregate": "memory_event", "resource_id": event_id, "revision": 99},
    )
    res = rt.execute_command(cmd)
    ok, why = _rejection_is_cas(res)
    if not ok:
        _fail(f"a stale event revision must be rejected with a CAS error; got {why}")


def test_memory_stale_error_reports_the_object_current_revision():
    rt = _dispatcher()
    event_id = _seed_event(rt)
    cmd = _make_cmd(
        schema_version="1.0",
        type="memory.correct",
        payload=_payload_for("memory.correct"),
        precondition={"aggregate": "memory_event", "resource_id": event_id, "revision": 99},
    )
    res = rt.execute_command(cmd)
    ok, why = _rejection_is_cas(res)
    if not ok:
        _fail(f"expected a CAS rejection for the stale event revision, got {why}")
    details = res.error.redacted_details or {}
    if details.get("aggregate") != "memory_event":
        _fail(f"object-CAS error must name the memory_event aggregate; details={details}")
    if details.get("current_revision") != 0:
        _fail(f"object-CAS error must return the event's current revision (0); details={details}")


def test_memory_hard_delete_requires_object_revision():
    rt = _dispatcher()
    _seed_event(rt)
    cmd = _make_cmd(
        schema_version="1.0",
        type="memory.hard_delete",
        payload=_payload_for("memory.hard_delete"),
    )
    res = rt.execute_command(cmd)
    ok, why = _rejection_is_cas(res)
    if not ok:
        _fail(f"memory.hard_delete must require an object revision before deleting; got {why}")


# ============================================= rule 6: heartbeat non-conflict
def test_heartbeat_does_not_bump_runtime_control_revision():
    rt = _dispatcher()
    before = _rev(rt, "runtime_control")
    rt.set_activity("thinking")
    if _rev(rt, "runtime_control") != before:
        _fail("activity/heartbeat must not increment runtime_control_revision")


def test_heartbeat_does_bump_snapshot_version():
    rt = _dispatcher()
    if not hasattr(rt, "snapshot_version"):
        _fail("RuntimeController has no snapshot_version (v1.2.1 搂4.2)")
    before = getattr(rt, "snapshot_version")
    rt.set_activity("thinking")
    if getattr(rt, "snapshot_version") == before:
        _fail("a published-state change must bump snapshot_version even when no CAS aggregate changes")


def test_heartbeat_does_not_invalidate_a_pending_mode_command():
    rt = _dispatcher()
    control = _rev(rt, "runtime_control")
    rt.set_activity("speaking")
    rt.set_activity("listening")
    cmd = _make_cmd(
        schema_version="1.0",
        type="runtime.set_mode",
        payload={"type": "runtime.set_mode", "mode": "live"},
        precondition={"aggregate": "runtime_control", "revision": control},
    )
    res = rt.execute_command(cmd)
    if res.status != "applied":
        _fail(f"heartbeat traffic made a valid mode command stale: {res.status} ({res.error})")


def test_provider_progress_does_not_bump_hub_binding_revision():
    from lva.contracts.state import ProviderStatus

    rt = _dispatcher()
    before = _rev(rt, "hub_binding")
    rt.set_provider_status("hub", ProviderStatus(provider_id="hub", kind="llm"))
    if _rev(rt, "hub_binding") != before:
        _fail("provider progress must not bump hub_binding_revision")


# ================================================= rule 7: CommandResult shape
def test_command_result_carries_snapshot_version_and_revisions():
    fields = set(CommandResult.model_fields)
    missing = [f for f in ("snapshot_version", "revisions") if f not in fields]
    if missing:
        _fail(f"v1.2.1 搂4.4: CommandResult must carry {missing}; fields={sorted(fields)}")


def test_command_result_drops_global_state_version():
    if "state_version" in CommandResult.model_fields:
        _fail("v1.2.1 搂4.4 replaces CommandResult.state_version with snapshot_version + revisions")


def test_command_result_reports_the_changed_aggregate_revision():
    rt = _dispatcher()
    control = _rev(rt, "runtime_control")
    cmd = _make_cmd(
        schema_version="1.0",
        type="runtime.set_mode",
        payload={"type": "runtime.set_mode", "mode": "live"},
        precondition={"aggregate": "runtime_control", "revision": control},
    )
    res = rt.execute_command(cmd)
    if res.status != "applied":
        _fail(f"baseline mode change must apply, got {res.status} ({res.error})")
    revisions = getattr(res, "revisions", None)
    if not revisions:
        _fail("CommandResult.revisions must report the changed aggregate revisions")
    if "runtime_control" not in revisions:
        _fail(f"CommandResult.revisions must include the changed aggregate; got {revisions}")


def test_generated_command_result_matches_python_fields():
    py = set(CommandResult.model_fields)
    problems = []
    for label, fields in (
        ("TS", _ts_interface_fields("CommandResult")),
        ("Rust", _rs_struct_fields("CommandResult")),
        ("JSON", _json_props("CommandResult")),
    ):
        if fields != py:
            problems.append(f"{label} differs from Python ({sorted(fields ^ py)})")
    if problems:
        _fail("CommandResult drifted across languages: " + "; ".join(problems))


def test_generated_artifacts_drop_state_version_from_state_and_result():
    problems = []
    for label, fields in (
        ("TS:RuntimeState", _ts_interface_fields("RuntimeState")),
        ("Rust:RuntimeState", _rs_struct_fields("RuntimeState")),
        ("JSON:RuntimeState", _json_props("RuntimeState")),
        ("TS:CommandResult", _ts_interface_fields("CommandResult")),
        ("Rust:CommandResult", _rs_struct_fields("CommandResult")),
        ("JSON:CommandResult", _json_props("CommandResult")),
    ):
        if "state_version" in fields:
            problems.append(label)
    if problems:
        _fail("generated artifacts still expose the removed global CAS field in: " + ", ".join(problems))


def test_generated_artifacts_carry_the_new_revision_fields():
    """Structural, not substring: the fields must be in the right interfaces."""
    expected = {"snapshot_version", "runtime_control_revision", "hub_binding_revision"}
    problems = []
    for label, fields in (
        ("TS:RuntimeState", _ts_interface_fields("RuntimeState")),
        ("Rust:RuntimeState", _rs_struct_fields("RuntimeState")),
        ("JSON:RuntimeState", _json_props("RuntimeState")),
    ):
        missing = expected - fields
        if missing:
            problems.append(f"{label} missing {sorted(missing)}")
    if problems:
        _fail("generated RuntimeState is missing v1.2.1 revision fields: " + "; ".join(problems))


# ==================================== rule 8: regenerate-and-diff (not self-ref)
def test_committed_json_schema_matches_a_fresh_generation():
    from lva.contracts.schema import generate_json_schema

    fresh = generate_json_schema()
    on_disk = json.loads(_read(JSON_SCHEMA))
    if fresh != on_disk:
        _fail("schemas/lva-ipc-v1.json is stale: a fresh generation differs from the committed file")


def test_committed_generated_ts_and_rust_match_a_fresh_generation():
    from lva.contracts.codegen import generate_rust_contracts, generate_typescript_contracts

    problems = []
    if generate_typescript_contracts() != _read(TS_CONTRACT):
        problems.append("lva-ipc.ts")
    if generate_rust_contracts() != _read(RS_CONTRACT):
        problems.append("lva_ipc.rs")
    if problems:
        _fail(f"generated artifacts are stale or hand-edited: {problems}")


def test_generated_command_payload_union_covers_the_frozen_commands():
    """The TS CommandPayload union must list exactly the frozen payload classes."""
    text = _read(TS_CONTRACT)
    # The pinned generator names the union after the property (`Payload`), so
    # locate it by membership of the frozen payload classes rather than by name.
    block = None
    for cand in re.finditer(r"export type (\w+)\s*=\s*(.*?);", text, re.S):
        if set(re.findall(r"\|\s*([A-Za-z_][A-Za-z0-9_]*)", cand.group(2))) & set(
            PAYLOAD_CLASS.values()
        ):
            block = cand
            break
    if not block:
        _fail("generated TS has no union containing the command payload interfaces")
    members = set(re.findall(r"\|\s*([A-Za-z_][A-Za-z0-9_]*)", block.group(2)))
    expected = set(PAYLOAD_CLASS.values())
    if members != expected:
        _fail(f"TS CommandPayload union mismatch: missing={sorted(expected - members)} extra={sorted(members - expected)}")
