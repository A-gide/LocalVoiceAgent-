from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from .enums import ErrorCode, FloorOwner, Mode, PrivacyScope, ProviderState, ServiceState
from .errors import ErrorEnvelope
from .ids import TurnId
from .state import HubBinding, RuntimeState


class BaseEventPayload(BaseModel):
    pass


class RuntimeSnapshotPayload(BaseEventPayload):
    type: Literal["runtime.snapshot"]
    state: RuntimeState


class ModeChangedPayload(BaseEventPayload):
    type: Literal["mode.changed"]
    previous_mode: Mode
    new_mode: Mode
    resume_mode: Mode | None = None


class PrivacyScopeChangedPayload(BaseEventPayload):
    type: Literal["privacy.scope_changed"]
    previous_scope: PrivacyScope
    new_scope: PrivacyScope
    unverified_reasons: list[str] = Field(default_factory=list)


class SessionStartedPayload(BaseEventPayload):
    type: Literal["session.started"]
    session_id: UUID


class SessionEndedPayload(BaseEventPayload):
    type: Literal["session.ended"]
    session_id: UUID


class TurnStartedPayload(BaseEventPayload):
    type: Literal["turn.started"]
    turn_id: TurnId
    provider_epoch: int
    user_text: str | None = None


class TurnCancelRequestedPayload(BaseEventPayload):
    type: Literal["turn.cancel_requested"]
    turn_id: TurnId
    provider_epoch: int
    reason: str


class TurnCancelledPayload(BaseEventPayload):
    type: Literal["turn.cancelled"]
    turn_id: TurnId
    provider_epoch: int
    reason: str


class TurnCompletedPayload(BaseEventPayload):
    type: Literal["turn.completed"]
    turn_id: TurnId
    provider_epoch: int
    reply_text: str


class InterruptDetectedPayload(BaseEventPayload):
    type: Literal["interrupt.detected"]
    turn_id: TurnId | None = None
    provider_epoch: int
    rms: float


class InterruptCommittedPayload(BaseEventPayload):
    type: Literal["interrupt.committed"]
    turn_id: TurnId | None = None
    provider_epoch: int
    new_floor: FloorOwner = FloorOwner.USER


class InterruptSettledPayload(BaseEventPayload):
    type: Literal["interrupt.settled"]
    turn_id: TurnId | None = None
    provider_epoch: int


class AudioVadStartedPayload(BaseEventPayload):
    type: Literal["audio.vad_started"]
    timestamp_ms: float


class AudioVadEndedPayload(BaseEventPayload):
    type: Literal["audio.vad_ended"]
    duration_ms: float


class AudioUtteranceReadyPayload(BaseEventPayload):
    type: Literal["audio.utterance_ready"]
    turn_id: TurnId
    raw_text: str
    corrected_text: str
    domain: str | None = None


class AudioPlaybackStartedPayload(BaseEventPayload):
    type: Literal["audio.playback_started"]
    turn_id: TurnId
    provider_epoch: int


class AudioPlaybackStopRequestedPayload(BaseEventPayload):
    type: Literal["audio.playback_stop_requested"]
    turn_id: TurnId
    provider_epoch: int
    reason: str


class AudioPlaybackSilencedPayload(BaseEventPayload):
    type: Literal["audio.playback_silenced"]
    turn_id: TurnId | None = None
    provider_epoch: int


class ProviderStateChangedPayload(BaseEventPayload):
    type: Literal["provider.state_changed"]
    provider_id: str
    kind: Literal["asr", "llm", "tts"]
    previous_state: ProviderState
    new_state: ProviderState
    epoch: int


class HubBindingChangedPayload(BaseEventPayload):
    type: Literal["hub.binding_changed"]
    binding: HubBinding


class HubOperationProgressPayload(BaseEventPayload):
    type: Literal["hub.operation_progress"]
    operation_id: str
    model_id: str
    progress_percent: float
    message: str


class MemoryCommittedPayload(BaseEventPayload):
    type: Literal["memory.committed"]
    event_id: UUID
    session_id: UUID | None = None
    turn_sequence: int | None = None


class MemoryRevisionAddedPayload(BaseEventPayload):
    type: Literal["memory.revision_added"]
    event_id: UUID
    revision: int
    reason: str


class MemoryRecallCompletedPayload(BaseEventPayload):
    type: Literal["memory.recall_completed"]
    query: str
    matched_count: int
    parse_status: str


class ServiceStateChangedPayload(BaseEventPayload):
    type: Literal["service.state_changed"]
    service_name: str
    previous_state: ServiceState
    new_state: ServiceState


class ErrorRaisedPayload(BaseEventPayload):
    type: Literal["error.raised"]
    error: ErrorEnvelope


EventPayload = Annotated[
    Union[
        RuntimeSnapshotPayload,
        ModeChangedPayload,
        PrivacyScopeChangedPayload,
        SessionStartedPayload,
        SessionEndedPayload,
        TurnStartedPayload,
        TurnCancelRequestedPayload,
        TurnCancelledPayload,
        TurnCompletedPayload,
        InterruptDetectedPayload,
        InterruptCommittedPayload,
        InterruptSettledPayload,
        AudioVadStartedPayload,
        AudioVadEndedPayload,
        AudioUtteranceReadyPayload,
        AudioPlaybackStartedPayload,
        AudioPlaybackStopRequestedPayload,
        AudioPlaybackSilencedPayload,
        ProviderStateChangedPayload,
        HubBindingChangedPayload,
        HubOperationProgressPayload,
        MemoryCommittedPayload,
        MemoryRevisionAddedPayload,
        MemoryRecallCompletedPayload,
        ServiceStateChangedPayload,
        ErrorRaisedPayload,
    ],
    Field(discriminator="type"),
]


class EventEnvelope(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: UUID = Field(default_factory=uuid4)
    sequence: int
    runtime_instance_id: UUID
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str
    session_id: UUID | None = None
    turn_id: TurnId | None = None
    type: str
    payload: EventPayload
