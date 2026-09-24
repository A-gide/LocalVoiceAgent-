from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, model_validator

from .enums import (
    ActivityState,
    FloorOwner,
    Mode,
    Ownership,
    PrivacyScope,
    ProviderState,
    ServiceState,
)
from .ids import TurnId


class CaptureState(BaseModel):
    active: bool = False
    device_name: str | None = None
    frames_captured: int = 0
    sample_rate: int = 16000


class PlaybackState(BaseModel):
    active: bool = False
    device_name: str | None = None
    current_generation: int = 0
    muted: bool = False


class ServiceStatus(BaseModel):
    name: str
    state: ServiceState = ServiceState.STOPPED
    ownership: Ownership = Ownership.UNKNOWN
    pid: int | None = None
    port: int | None = None
    endpoint: str | None = None
    last_error: str | None = None


class ProviderStatus(BaseModel):
    provider_id: str
    kind: Literal["asr", "llm", "tts"]
    state: ProviderState = ProviderState.UNINITIALIZED
    current_model: str | None = None
    epoch: int = 0
    last_error: str | None = None


class HubBinding(BaseModel):
    desired_model_id: str | None = None
    active_model_id: str | None = None
    provider_epoch: int = 0
    load_origin: Literal["loaded_by_lva", "preexisting", "unknown"] = "unknown"
    status: Literal[
        "unbound",
        "preparing",
        "stopping",
        "loading",
        "verifying",
        "ready",
        "degraded",
        "failed",
    ] = "unbound"
    last_error: str | None = None


class CaptureAggregate(BaseModel):
    core_mic_stopped: bool = True
    managed_screenpipe_stopped: bool | None = None
    external_screenpipe_detected: bool = False


class HubBindReason(str, Enum):
    """Why the Hub control endpoint could not be proven loopback-only (§5.8).

    The values carry no address, port or PID: this type travels to the WebView.
    """

    RESOLVED_NON_LOOPBACK = "RESOLVED_NON_LOOPBACK"
    LISTENER_NON_LOOPBACK = "LISTENER_NON_LOOPBACK"
    PROCESS_UNMAPPED = "PROCESS_UNMAPPED"
    HUB_INFO_UNAVAILABLE = "HUB_INFO_UNAVAILABLE"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    PROBE_FAILED = "PROBE_FAILED"


class HubBindAttestation(BaseModel):
    """Redacted summary of the Hub effective-bind attestation (v1.2.1 §5.8).

    This travels with ``RuntimeState`` into the WebView, so it carries only the
    verdict and coarse provenance -- never a PID, port, listener address,
    endpoint or credential.  The raw evidence stays on the Rust diagnostics
    surface and is correlated by ``attestation_id`` only.
    """

    status: Literal["VERIFIED_LOOPBACK", "VERIFIED_NON_LOOPBACK", "UNVERIFIED_BIND"]
    reason_code: HubBindReason | None = None
    checked_at: datetime
    attestation_id: str
    revalidate_after: datetime | None = None

    @model_validator(mode="after")
    def _fail_closed(self) -> "HubBindAttestation":
        if self.status == "VERIFIED_LOOPBACK" and self.reason_code is not None:
            raise ValueError("a verified attestation must not carry a reason_code")
        return self


class RuntimeState(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    runtime_instance_id: UUID
    snapshot_version: int = 0
    runtime_control_revision: int = 0
    hub_binding_revision: int = 0
    mode: Mode = Mode.STANDBY
    resume_mode: Mode | None = None
    session_id: UUID | None = None
    current_turn: TurnId | None = None
    floor: FloorOwner = FloorOwner.NONE
    activity: ActivityState = ActivityState.IDLE
    mic_capture: CaptureState = Field(default_factory=CaptureState)
    managed_capture: CaptureAggregate = Field(default_factory=CaptureAggregate)
    playback: PlaybackState = Field(default_factory=PlaybackState)
    services: dict[str, ServiceStatus] = Field(default_factory=dict)
    providers: dict[str, ProviderStatus] = Field(default_factory=dict)
    hub_binding: HubBinding | None = None
    hub_bind_attestation: HubBindAttestation | None = None
    privacy_scope: PrivacyScope = PrivacyScope.NOT_PAUSED


class RealityRecordingSettings(BaseModel):
    record_reality_during_live: bool = False
