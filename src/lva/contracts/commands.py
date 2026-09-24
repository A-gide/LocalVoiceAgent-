from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from .enums import Mode
from .errors import ErrorEnvelope
from .ids import TurnId
from .state import HubBindAttestation


class BaseCommandPayload(BaseModel):
    pass


class RuntimeGetSnapshotPayload(BaseCommandPayload):
    type: Literal["runtime.get_snapshot"]


class RuntimeSetModePayload(BaseCommandPayload):
    type: Literal["runtime.set_mode"]
    mode: Mode


class RuntimeRestoreModePayload(BaseCommandPayload):
    type: Literal["runtime.restore_mode"]


class TurnSendTextPayload(BaseCommandPayload):
    type: Literal["turn.send_text"]
    text: str
    session_id: UUID | None = None


class TurnCancelPayload(BaseCommandPayload):
    type: Literal["turn.cancel"]
    turn_id: TurnId | None = None
    reason: str = "user_cancel"


class HubRefreshPayload(BaseCommandPayload):
    type: Literal["hub.refresh"]


class HubBindModelPayload(BaseCommandPayload):
    type: Literal["hub.bind_model"]
    model_id: str
    force: bool = False


class HubSleepBoundModelPayload(BaseCommandPayload):
    type: Literal["hub.sleep_bound_model"]


class HubAttestBindPayload(BaseCommandPayload):
    """An effective-bind verdict reported by the process authority (PR-012).

    Direction: this is an **inbound** command.  The Rust side observes the OS
    listener table (plan L1256: the process authority produces the attestation;
    Core does not inspect Windows state), and reports the redacted verdict to Core
    over the existing authenticated WS.  Core then decides whether Hub control may
    run at all (plan L665: only ``VERIFIED_LOOPBACK`` permits it).

    The payload reuses the already-defined ``HubBindAttestation`` -- the same type
    that travels to the WebView -- so there is exactly one verdict shape in the
    contract rather than two that could drift apart.
    """

    type: Literal["hub.attest_bind"]
    attestation: HubBindAttestation


class MemorySearchPayload(BaseCommandPayload):
    type: Literal["memory.search"]
    query: str
    limit: int = 10
    user_timezone: str = "UTC"


class MemoryCorrectPayload(BaseCommandPayload):
    type: Literal["memory.correct"]
    event_id: UUID
    corrected_text: str
    reason: str
    actor: str = "user"


class MemoryHardDeletePayload(BaseCommandPayload):
    type: Literal["memory.hard_delete"]
    event_ids: list[UUID]
    reason_code: str


class ServiceRetryPayload(BaseCommandPayload):
    type: Literal["service.retry"]
    service_name: str


class DiagnosticsExportRedactedPayload(BaseCommandPayload):
    type: Literal["diagnostics.export_redacted"]


class SettingsUpdatePublicPayload(BaseCommandPayload):
    type: Literal["settings.update_public"]
    autostart: bool | None = None
    pet_dormancy_mode: bool | None = None
    idle_vram_release_mins: int | None = None
    local_gguf_path: str | None = None
    llm_mode: Literal["local", "cloud"] | None = None
    active_character: str | None = None
    record_reality_during_live: bool | None = None


class SettingsSetSecretPayload(BaseCommandPayload):
    type: Literal["settings.set_secret"]
    secret_type: Literal["cloud_api_key", "asr_api_key", "tts_api_key"]
    secret_value: str


class SettingsClearSecretPayload(BaseCommandPayload):
    type: Literal["settings.clear_secret"]
    secret_type: Literal["cloud_api_key", "asr_api_key", "tts_api_key"]


class RuntimeControlPrecondition(BaseModel):
    aggregate: Literal["runtime_control"]
    revision: int


class HubBindingPrecondition(BaseModel):
    aggregate: Literal["hub_binding"]
    revision: int


class SettingsPrecondition(BaseModel):
    aggregate: Literal["settings"]
    revision: int


class MemoryEventPrecondition(BaseModel):
    aggregate: Literal["memory_event"]
    resource_id: str
    revision: int


CommandPrecondition = Annotated[
    Union[
        RuntimeControlPrecondition,
        HubBindingPrecondition,
        SettingsPrecondition,
        MemoryEventPrecondition,
        None,
    ],
    Field(discriminator="aggregate"),
]


CommandPayload = Annotated[
    Union[
        RuntimeGetSnapshotPayload,
        RuntimeSetModePayload,
        RuntimeRestoreModePayload,
        TurnSendTextPayload,
        TurnCancelPayload,
        HubRefreshPayload,
        HubBindModelPayload,
        HubSleepBoundModelPayload,
        HubAttestBindPayload,
        SettingsUpdatePublicPayload,
        SettingsSetSecretPayload,
        SettingsClearSecretPayload,
        MemorySearchPayload,
        MemoryCorrectPayload,
        MemoryHardDeletePayload,
        ServiceRetryPayload,
        DiagnosticsExportRedactedPayload,
    ],
    Field(discriminator="type"),
]


class CommandEnvelope(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    command_id: UUID = Field(default_factory=uuid4)
    idempotency_key: str | None = None
    precondition: CommandPrecondition = None
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: str
    payload: CommandPayload


class CommandResult(BaseModel):
    command_id: UUID
    status: Literal["accepted", "applied", "rejected", "duplicate"]
    snapshot_version: int
    revisions: dict[str, int] = Field(default_factory=dict)
    data: Any | None = None
    error: ErrorEnvelope | None = None
