///`ActivityState`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum ActivityState {
    #[serde(rename = "idle")]
    Idle,
    #[serde(rename = "listening")]
    Listening,
    #[serde(rename = "thinking")]
    Thinking,
    #[serde(rename = "speaking")]
    Speaking,
}
impl ::std::fmt::Display for ActivityState {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Idle => f.write_str("idle"),
            Self::Listening => f.write_str("listening"),
            Self::Thinking => f.write_str("thinking"),
            Self::Speaking => f.write_str("speaking"),
        }
    }
}
impl ::std::str::FromStr for ActivityState {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "idle" => Ok(Self::Idle),
            "listening" => Ok(Self::Listening),
            "thinking" => Ok(Self::Thinking),
            "speaking" => Ok(Self::Speaking),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for ActivityState {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for ActivityState {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`AudioPlaybackSilencedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct AudioPlaybackSilencedPayload {
    pub provider_epoch: i64,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub turn_id: ::std::option::Option<TurnId>,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`AudioPlaybackStartedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct AudioPlaybackStartedPayload {
    pub provider_epoch: i64,
    pub turn_id: TurnId,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`AudioPlaybackStopRequestedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct AudioPlaybackStopRequestedPayload {
    pub provider_epoch: i64,
    pub reason: ::std::string::String,
    pub turn_id: TurnId,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`AudioUtteranceReadyPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct AudioUtteranceReadyPayload {
    pub corrected_text: ::std::string::String,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub domain: ::std::option::Option<::std::string::String>,
    pub raw_text: ::std::string::String,
    pub turn_id: TurnId,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`AudioVadEndedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct AudioVadEndedPayload {
    pub duration_ms: f64,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`AudioVadStartedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct AudioVadStartedPayload {
    pub timestamp_ms: f64,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`CaptureAggregate`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct CaptureAggregate {
    #[serde(default = "defaults::default_bool::<true>")]
    pub core_mic_stopped: bool,
    #[serde(default)]
    pub external_screenpipe_detected: bool,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub managed_screenpipe_stopped: ::std::option::Option<bool>,
}
impl ::std::default::Default for CaptureAggregate {
    fn default() -> Self {
        Self {
            core_mic_stopped: defaults::default_bool::<true>(),
            external_screenpipe_detected: Default::default(),
            managed_screenpipe_stopped: Default::default(),
        }
    }
}
///`CaptureState`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct CaptureState {
    #[serde(default)]
    pub active: bool,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub device_name: ::std::option::Option<::std::string::String>,
    #[serde(default)]
    pub frames_captured: i64,
    #[serde(default = "defaults::default_u64::<i64, 16000>")]
    pub sample_rate: i64,
}
impl ::std::default::Default for CaptureState {
    fn default() -> Self {
        Self {
            active: Default::default(),
            device_name: Default::default(),
            frames_captured: Default::default(),
            sample_rate: defaults::default_u64::<i64, 16000>(),
        }
    }
}
///`CommandEnvelope`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct CommandEnvelope {
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub command_id: ::std::option::Option<::uuid::Uuid>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub idempotency_key: ::std::option::Option<::std::string::String>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub issued_at: ::std::option::Option<::chrono::DateTime<::chrono::offset::Utc>>,
    pub payload: Payload,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub precondition: ::std::option::Option<CommandEnvelopePrecondition>,
    #[serde(default = "defaults::command_envelope_schema_version")]
    pub schema_version: ::std::string::String,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`CommandEnvelopePrecondition`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
#[serde(tag = "aggregate")]
pub enum CommandEnvelopePrecondition {
    ///RuntimeControlPrecondition
    #[serde(rename = "runtime_control")]
    RuntimeControl { revision: i64 },
    ///HubBindingPrecondition
    #[serde(rename = "hub_binding")]
    HubBinding { revision: i64 },
    ///SettingsPrecondition
    #[serde(rename = "settings")]
    Settings { revision: i64 },
    ///MemoryEventPrecondition
    #[serde(rename = "memory_event")]
    MemoryEvent { resource_id: ::std::string::String, revision: i64 },
}
///`CommandResult`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct CommandResult {
    pub command_id: ::uuid::Uuid,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub data: ::std::option::Option<::serde_json::Value>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub error: ::std::option::Option<ErrorEnvelope>,
    #[serde(default, skip_serializing_if = ":: std :: collections :: HashMap::is_empty")]
    pub revisions: ::std::collections::HashMap<::std::string::String, i64>,
    pub snapshot_version: i64,
    pub status: Status,
}
///`DiagnosticsExportRedactedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct DiagnosticsExportRedactedPayload {
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`ErrorCode`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum ErrorCode {
    #[serde(rename = "AUTH_REQUIRED")]
    AuthRequired,
    #[serde(rename = "AUTH_FAILED")]
    AuthFailed,
    #[serde(rename = "ORIGIN_REJECTED")]
    OriginRejected,
    #[serde(rename = "PROTOCOL_MISMATCH")]
    ProtocolMismatch,
    #[serde(rename = "STALE_REVISION")]
    StaleRevision,
    #[serde(rename = "DUPLICATE_COMMAND")]
    DuplicateCommand,
    #[serde(rename = "INVALID_TRANSITION")]
    InvalidTransition,
    #[serde(rename = "PASSIVE_PROVIDER_FORBIDDEN")]
    PassiveProviderForbidden,
    #[serde(rename = "PRIVACY_UNVERIFIED")]
    PrivacyUnverified,
    #[serde(rename = "HUB_UNAVAILABLE")]
    HubUnavailable,
    #[serde(rename = "HUB_VERSION_UNSUPPORTED")]
    HubVersionUnsupported,
    #[serde(rename = "HUB_CONTROL_UNSAFE")]
    HubControlUnsafe,
    #[serde(rename = "HUB_BIND_UNVERIFIED")]
    HubBindUnverified,
    #[serde(rename = "PROFILE_REQUIRED")]
    ProfileRequired,
    #[serde(rename = "MODEL_CONFLICT_REQUIRES_CONFIRMATION")]
    ModelConflictRequiresConfirmation,
    #[serde(rename = "MODEL_LOAD_FAILED")]
    ModelLoadFailed,
    #[serde(rename = "PROVIDER_DISCONNECTED")]
    ProviderDisconnected,
    #[serde(rename = "TURN_CANCELLED")]
    TurnCancelled,
    #[serde(rename = "STALE_EFFECT_DROPPED")]
    StaleEffectDropped,
    #[serde(rename = "JOURNAL_BUSY")]
    JournalBusy,
    #[serde(rename = "IMPORT_SCHEMA_UNSUPPORTED")]
    ImportSchemaUnsupported,
    #[serde(rename = "MIGRATION_FAILED")]
    MigrationFailed,
}
impl ::std::fmt::Display for ErrorCode {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::AuthRequired => f.write_str("AUTH_REQUIRED"),
            Self::AuthFailed => f.write_str("AUTH_FAILED"),
            Self::OriginRejected => f.write_str("ORIGIN_REJECTED"),
            Self::ProtocolMismatch => f.write_str("PROTOCOL_MISMATCH"),
            Self::StaleRevision => f.write_str("STALE_REVISION"),
            Self::DuplicateCommand => f.write_str("DUPLICATE_COMMAND"),
            Self::InvalidTransition => f.write_str("INVALID_TRANSITION"),
            Self::PassiveProviderForbidden => f.write_str("PASSIVE_PROVIDER_FORBIDDEN"),
            Self::PrivacyUnverified => f.write_str("PRIVACY_UNVERIFIED"),
            Self::HubUnavailable => f.write_str("HUB_UNAVAILABLE"),
            Self::HubVersionUnsupported => f.write_str("HUB_VERSION_UNSUPPORTED"),
            Self::HubControlUnsafe => f.write_str("HUB_CONTROL_UNSAFE"),
            Self::HubBindUnverified => f.write_str("HUB_BIND_UNVERIFIED"),
            Self::ProfileRequired => f.write_str("PROFILE_REQUIRED"),
            Self::ModelConflictRequiresConfirmation => {
                f.write_str("MODEL_CONFLICT_REQUIRES_CONFIRMATION")
            }
            Self::ModelLoadFailed => f.write_str("MODEL_LOAD_FAILED"),
            Self::ProviderDisconnected => f.write_str("PROVIDER_DISCONNECTED"),
            Self::TurnCancelled => f.write_str("TURN_CANCELLED"),
            Self::StaleEffectDropped => f.write_str("STALE_EFFECT_DROPPED"),
            Self::JournalBusy => f.write_str("JOURNAL_BUSY"),
            Self::ImportSchemaUnsupported => f.write_str("IMPORT_SCHEMA_UNSUPPORTED"),
            Self::MigrationFailed => f.write_str("MIGRATION_FAILED"),
        }
    }
}
impl ::std::str::FromStr for ErrorCode {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "AUTH_REQUIRED" => Ok(Self::AuthRequired),
            "AUTH_FAILED" => Ok(Self::AuthFailed),
            "ORIGIN_REJECTED" => Ok(Self::OriginRejected),
            "PROTOCOL_MISMATCH" => Ok(Self::ProtocolMismatch),
            "STALE_REVISION" => Ok(Self::StaleRevision),
            "DUPLICATE_COMMAND" => Ok(Self::DuplicateCommand),
            "INVALID_TRANSITION" => Ok(Self::InvalidTransition),
            "PASSIVE_PROVIDER_FORBIDDEN" => Ok(Self::PassiveProviderForbidden),
            "PRIVACY_UNVERIFIED" => Ok(Self::PrivacyUnverified),
            "HUB_UNAVAILABLE" => Ok(Self::HubUnavailable),
            "HUB_VERSION_UNSUPPORTED" => Ok(Self::HubVersionUnsupported),
            "HUB_CONTROL_UNSAFE" => Ok(Self::HubControlUnsafe),
            "HUB_BIND_UNVERIFIED" => Ok(Self::HubBindUnverified),
            "PROFILE_REQUIRED" => Ok(Self::ProfileRequired),
            "MODEL_CONFLICT_REQUIRES_CONFIRMATION" => {
                Ok(Self::ModelConflictRequiresConfirmation)
            }
            "MODEL_LOAD_FAILED" => Ok(Self::ModelLoadFailed),
            "PROVIDER_DISCONNECTED" => Ok(Self::ProviderDisconnected),
            "TURN_CANCELLED" => Ok(Self::TurnCancelled),
            "STALE_EFFECT_DROPPED" => Ok(Self::StaleEffectDropped),
            "JOURNAL_BUSY" => Ok(Self::JournalBusy),
            "IMPORT_SCHEMA_UNSUPPORTED" => Ok(Self::ImportSchemaUnsupported),
            "MIGRATION_FAILED" => Ok(Self::MigrationFailed),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for ErrorCode {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for ErrorCode {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`ErrorEnvelope`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct ErrorEnvelope {
    pub code: ErrorCode,
    pub component: ::std::string::String,
    pub correlation_id: ::uuid::Uuid,
    pub message: ::std::string::String,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub redacted_details: ::std::option::Option<
        ::serde_json::Map<::std::string::String, ::serde_json::Value>,
    >,
    #[serde(default)]
    pub retryable: bool,
    #[serde(default = "defaults::error_envelope_severity")]
    pub severity: Severity,
}
///`ErrorRaisedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct ErrorRaisedPayload {
    pub error: ErrorEnvelope,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`EventEnvelope`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct EventEnvelope {
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub event_id: ::std::option::Option<::uuid::Uuid>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub occurred_at: ::std::option::Option<::chrono::DateTime<::chrono::offset::Utc>>,
    pub payload: EventEnvelopePayload,
    pub runtime_instance_id: ::uuid::Uuid,
    #[serde(default = "defaults::event_envelope_schema_version")]
    pub schema_version: ::std::string::String,
    pub sequence: i64,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub session_id: ::std::option::Option<::uuid::Uuid>,
    pub source: ::std::string::String,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub turn_id: ::std::option::Option<TurnId>,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`EventEnvelopePayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
#[serde(tag = "type")]
pub enum EventEnvelopePayload {
    ///RuntimeSnapshotPayload
    #[serde(rename = "runtime.snapshot")]
    RuntimeSnapshot { state: RuntimeState },
    ///ModeChangedPayload
    #[serde(rename = "mode.changed")]
    ModeChanged {
        new_mode: Mode,
        previous_mode: Mode,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        resume_mode: ::std::option::Option<Mode>,
    },
    ///PrivacyScopeChangedPayload
    #[serde(rename = "privacy.scope_changed")]
    PrivacyScopeChanged {
        new_scope: PrivacyScope,
        previous_scope: PrivacyScope,
        #[serde(default, skip_serializing_if = "::std::vec::Vec::is_empty")]
        unverified_reasons: ::std::vec::Vec<::std::string::String>,
    },
    ///SessionStartedPayload
    #[serde(rename = "session.started")]
    SessionStarted { session_id: ::uuid::Uuid },
    ///SessionEndedPayload
    #[serde(rename = "session.ended")]
    SessionEnded { session_id: ::uuid::Uuid },
    ///TurnStartedPayload
    #[serde(rename = "turn.started")]
    TurnStarted {
        provider_epoch: i64,
        turn_id: TurnId,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        user_text: ::std::option::Option<::std::string::String>,
    },
    ///TurnCancelRequestedPayload
    #[serde(rename = "turn.cancel_requested")]
    TurnCancelRequested {
        provider_epoch: i64,
        reason: ::std::string::String,
        turn_id: TurnId,
    },
    ///TurnCancelledPayload
    #[serde(rename = "turn.cancelled")]
    TurnCancelled {
        provider_epoch: i64,
        reason: ::std::string::String,
        turn_id: TurnId,
    },
    ///TurnCompletedPayload
    #[serde(rename = "turn.completed")]
    TurnCompleted {
        provider_epoch: i64,
        reply_text: ::std::string::String,
        turn_id: TurnId,
    },
    ///InterruptDetectedPayload
    #[serde(rename = "interrupt.detected")]
    InterruptDetected {
        provider_epoch: i64,
        rms: f64,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        turn_id: ::std::option::Option<TurnId>,
    },
    ///InterruptCommittedPayload
    #[serde(rename = "interrupt.committed")]
    InterruptCommitted {
        #[serde(
            default = "defaults::event_envelope_payload_interrupt_committed_new_floor"
        )]
        new_floor: FloorOwner,
        provider_epoch: i64,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        turn_id: ::std::option::Option<TurnId>,
    },
    ///InterruptSettledPayload
    #[serde(rename = "interrupt.settled")]
    InterruptSettled {
        provider_epoch: i64,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        turn_id: ::std::option::Option<TurnId>,
    },
    ///AudioVadStartedPayload
    #[serde(rename = "audio.vad_started")]
    AudioVadStarted { timestamp_ms: f64 },
    ///AudioVadEndedPayload
    #[serde(rename = "audio.vad_ended")]
    AudioVadEnded { duration_ms: f64 },
    ///AudioUtteranceReadyPayload
    #[serde(rename = "audio.utterance_ready")]
    AudioUtteranceReady {
        corrected_text: ::std::string::String,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        domain: ::std::option::Option<::std::string::String>,
        raw_text: ::std::string::String,
        turn_id: TurnId,
    },
    ///AudioPlaybackStartedPayload
    #[serde(rename = "audio.playback_started")]
    AudioPlaybackStarted { provider_epoch: i64, turn_id: TurnId },
    ///AudioPlaybackStopRequestedPayload
    #[serde(rename = "audio.playback_stop_requested")]
    AudioPlaybackStopRequested {
        provider_epoch: i64,
        reason: ::std::string::String,
        turn_id: TurnId,
    },
    ///AudioPlaybackSilencedPayload
    #[serde(rename = "audio.playback_silenced")]
    AudioPlaybackSilenced {
        provider_epoch: i64,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        turn_id: ::std::option::Option<TurnId>,
    },
    ///ProviderStateChangedPayload
    #[serde(rename = "provider.state_changed")]
    ProviderStateChanged {
        epoch: i64,
        kind: Kind,
        new_state: ProviderState,
        previous_state: ProviderState,
        provider_id: ::std::string::String,
    },
    ///HubBindingChangedPayload
    #[serde(rename = "hub.binding_changed")]
    HubBindingChanged { binding: HubBinding },
    ///HubOperationProgressPayload
    #[serde(rename = "hub.operation_progress")]
    HubOperationProgress {
        message: ::std::string::String,
        model_id: ::std::string::String,
        operation_id: ::std::string::String,
        progress_percent: f64,
    },
    ///MemoryCommittedPayload
    #[serde(rename = "memory.committed")]
    MemoryCommitted {
        event_id: ::uuid::Uuid,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        session_id: ::std::option::Option<::uuid::Uuid>,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        turn_sequence: ::std::option::Option<i64>,
    },
    ///MemoryRevisionAddedPayload
    #[serde(rename = "memory.revision_added")]
    MemoryRevisionAdded {
        event_id: ::uuid::Uuid,
        reason: ::std::string::String,
        revision: i64,
    },
    ///MemoryRecallCompletedPayload
    #[serde(rename = "memory.recall_completed")]
    MemoryRecallCompleted {
        matched_count: i64,
        parse_status: ::std::string::String,
        query: ::std::string::String,
    },
    ///ServiceStateChangedPayload
    #[serde(rename = "service.state_changed")]
    ServiceStateChanged {
        new_state: ServiceState,
        previous_state: ServiceState,
        service_name: ::std::string::String,
    },
    ///ErrorRaisedPayload
    #[serde(rename = "error.raised")]
    ErrorRaised { error: ErrorEnvelope },
}
///`FloorOwner`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum FloorOwner {
    #[serde(rename = "user")]
    User,
    #[serde(rename = "agent")]
    Agent,
    #[serde(rename = "none")]
    None,
}
impl ::std::fmt::Display for FloorOwner {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::User => f.write_str("user"),
            Self::Agent => f.write_str("agent"),
            Self::None => f.write_str("none"),
        }
    }
}
impl ::std::str::FromStr for FloorOwner {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "user" => Ok(Self::User),
            "agent" => Ok(Self::Agent),
            "none" => Ok(Self::None),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for FloorOwner {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for FloorOwner {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
/**An effective-bind verdict reported by the process authority (PR-012).

Direction: this is an **inbound** command.  The Rust side observes the OS
listener table (plan L1256: the process authority produces the attestation;
Core does not inspect Windows state), and reports the redacted verdict to Core
over the existing authenticated WS.  Core then decides whether Hub control may
run at all (plan L665: only ``VERIFIED_LOOPBACK`` permits it).

The payload reuses the already-defined ``HubBindAttestation`` -- the same type
that travels to the WebView -- so there is exactly one verdict shape in the
contract rather than two that could drift apart.*/
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct HubAttestBindPayload {
    pub attestation: HubBindAttestation,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
/**Redacted summary of the Hub effective-bind attestation (v1.2.1 §5.8).

This travels with ``RuntimeState`` into the WebView, so it carries only the
verdict and coarse provenance -- never a PID, port, listener address,
endpoint or credential.  The raw evidence stays on the Rust diagnostics
surface and is correlated by ``attestation_id`` only.*/
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct HubBindAttestation {
    pub attestation_id: ::std::string::String,
    pub checked_at: ::chrono::DateTime<::chrono::offset::Utc>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub reason_code: ::std::option::Option<HubBindReason>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub revalidate_after: ::std::option::Option<
        ::chrono::DateTime<::chrono::offset::Utc>,
    >,
    pub status: HubBindAttestationStatus,
}
///`HubBindAttestationStatus`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum HubBindAttestationStatus {
    #[serde(rename = "VERIFIED_LOOPBACK")]
    VerifiedLoopback,
    #[serde(rename = "VERIFIED_NON_LOOPBACK")]
    VerifiedNonLoopback,
    #[serde(rename = "UNVERIFIED_BIND")]
    UnverifiedBind,
}
impl ::std::fmt::Display for HubBindAttestationStatus {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::VerifiedLoopback => f.write_str("VERIFIED_LOOPBACK"),
            Self::VerifiedNonLoopback => f.write_str("VERIFIED_NON_LOOPBACK"),
            Self::UnverifiedBind => f.write_str("UNVERIFIED_BIND"),
        }
    }
}
impl ::std::str::FromStr for HubBindAttestationStatus {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "VERIFIED_LOOPBACK" => Ok(Self::VerifiedLoopback),
            "VERIFIED_NON_LOOPBACK" => Ok(Self::VerifiedNonLoopback),
            "UNVERIFIED_BIND" => Ok(Self::UnverifiedBind),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for HubBindAttestationStatus {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for HubBindAttestationStatus {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`HubBindModelPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct HubBindModelPayload {
    #[serde(default)]
    pub force: bool,
    pub model_id: ::std::string::String,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
/**Why the Hub control endpoint could not be proven loopback-only (§5.8).

The values carry no address, port or PID: this type travels to the WebView.*/
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum HubBindReason {
    #[serde(rename = "RESOLVED_NON_LOOPBACK")]
    ResolvedNonLoopback,
    #[serde(rename = "LISTENER_NON_LOOPBACK")]
    ListenerNonLoopback,
    #[serde(rename = "PROCESS_UNMAPPED")]
    ProcessUnmapped,
    #[serde(rename = "HUB_INFO_UNAVAILABLE")]
    HubInfoUnavailable,
    #[serde(rename = "REVALIDATION_REQUIRED")]
    RevalidationRequired,
    #[serde(rename = "PROBE_FAILED")]
    ProbeFailed,
}
impl ::std::fmt::Display for HubBindReason {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::ResolvedNonLoopback => f.write_str("RESOLVED_NON_LOOPBACK"),
            Self::ListenerNonLoopback => f.write_str("LISTENER_NON_LOOPBACK"),
            Self::ProcessUnmapped => f.write_str("PROCESS_UNMAPPED"),
            Self::HubInfoUnavailable => f.write_str("HUB_INFO_UNAVAILABLE"),
            Self::RevalidationRequired => f.write_str("REVALIDATION_REQUIRED"),
            Self::ProbeFailed => f.write_str("PROBE_FAILED"),
        }
    }
}
impl ::std::str::FromStr for HubBindReason {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "RESOLVED_NON_LOOPBACK" => Ok(Self::ResolvedNonLoopback),
            "LISTENER_NON_LOOPBACK" => Ok(Self::ListenerNonLoopback),
            "PROCESS_UNMAPPED" => Ok(Self::ProcessUnmapped),
            "HUB_INFO_UNAVAILABLE" => Ok(Self::HubInfoUnavailable),
            "REVALIDATION_REQUIRED" => Ok(Self::RevalidationRequired),
            "PROBE_FAILED" => Ok(Self::ProbeFailed),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for HubBindReason {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for HubBindReason {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`HubBinding`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct HubBinding {
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub active_model_id: ::std::option::Option<::std::string::String>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub desired_model_id: ::std::option::Option<::std::string::String>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub last_error: ::std::option::Option<::std::string::String>,
    #[serde(default = "defaults::hub_binding_load_origin")]
    pub load_origin: LoadOrigin,
    #[serde(default)]
    pub provider_epoch: i64,
    #[serde(default = "defaults::hub_binding_status")]
    pub status: HubBindingStatus,
}
impl ::std::default::Default for HubBinding {
    fn default() -> Self {
        Self {
            active_model_id: Default::default(),
            desired_model_id: Default::default(),
            last_error: Default::default(),
            load_origin: defaults::hub_binding_load_origin(),
            provider_epoch: Default::default(),
            status: defaults::hub_binding_status(),
        }
    }
}
///`HubBindingChangedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct HubBindingChangedPayload {
    pub binding: HubBinding,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`HubBindingPrecondition`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct HubBindingPrecondition {
    pub aggregate: ::std::string::String,
    pub revision: i64,
}
///`HubBindingStatus`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum HubBindingStatus {
    #[serde(rename = "unbound")]
    Unbound,
    #[serde(rename = "preparing")]
    Preparing,
    #[serde(rename = "stopping")]
    Stopping,
    #[serde(rename = "loading")]
    Loading,
    #[serde(rename = "verifying")]
    Verifying,
    #[serde(rename = "ready")]
    Ready,
    #[serde(rename = "degraded")]
    Degraded,
    #[serde(rename = "failed")]
    Failed,
}
impl ::std::fmt::Display for HubBindingStatus {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Unbound => f.write_str("unbound"),
            Self::Preparing => f.write_str("preparing"),
            Self::Stopping => f.write_str("stopping"),
            Self::Loading => f.write_str("loading"),
            Self::Verifying => f.write_str("verifying"),
            Self::Ready => f.write_str("ready"),
            Self::Degraded => f.write_str("degraded"),
            Self::Failed => f.write_str("failed"),
        }
    }
}
impl ::std::str::FromStr for HubBindingStatus {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "unbound" => Ok(Self::Unbound),
            "preparing" => Ok(Self::Preparing),
            "stopping" => Ok(Self::Stopping),
            "loading" => Ok(Self::Loading),
            "verifying" => Ok(Self::Verifying),
            "ready" => Ok(Self::Ready),
            "degraded" => Ok(Self::Degraded),
            "failed" => Ok(Self::Failed),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for HubBindingStatus {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for HubBindingStatus {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::default::Default for HubBindingStatus {
    fn default() -> Self {
        HubBindingStatus::Unbound
    }
}
///`HubOperationProgressPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct HubOperationProgressPayload {
    pub message: ::std::string::String,
    pub model_id: ::std::string::String,
    pub operation_id: ::std::string::String,
    pub progress_percent: f64,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`HubRefreshPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct HubRefreshPayload {
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`HubSleepBoundModelPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct HubSleepBoundModelPayload {
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`InterruptCommittedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct InterruptCommittedPayload {
    #[serde(default = "defaults::interrupt_committed_payload_new_floor")]
    pub new_floor: FloorOwner,
    pub provider_epoch: i64,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub turn_id: ::std::option::Option<TurnId>,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`InterruptDetectedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct InterruptDetectedPayload {
    pub provider_epoch: i64,
    pub rms: f64,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub turn_id: ::std::option::Option<TurnId>,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`InterruptSettledPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct InterruptSettledPayload {
    pub provider_epoch: i64,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub turn_id: ::std::option::Option<TurnId>,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`Kind`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum Kind {
    #[serde(rename = "asr")]
    Asr,
    #[serde(rename = "llm")]
    Llm,
    #[serde(rename = "tts")]
    Tts,
}
impl ::std::fmt::Display for Kind {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Asr => f.write_str("asr"),
            Self::Llm => f.write_str("llm"),
            Self::Tts => f.write_str("tts"),
        }
    }
}
impl ::std::str::FromStr for Kind {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "asr" => Ok(Self::Asr),
            "llm" => Ok(Self::Llm),
            "tts" => Ok(Self::Tts),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for Kind {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for Kind {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`LoadOrigin`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum LoadOrigin {
    #[serde(rename = "loaded_by_lva")]
    LoadedByLva,
    #[serde(rename = "preexisting")]
    Preexisting,
    #[serde(rename = "unknown")]
    Unknown,
}
impl ::std::fmt::Display for LoadOrigin {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::LoadedByLva => f.write_str("loaded_by_lva"),
            Self::Preexisting => f.write_str("preexisting"),
            Self::Unknown => f.write_str("unknown"),
        }
    }
}
impl ::std::str::FromStr for LoadOrigin {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "loaded_by_lva" => Ok(Self::LoadedByLva),
            "preexisting" => Ok(Self::Preexisting),
            "unknown" => Ok(Self::Unknown),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for LoadOrigin {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for LoadOrigin {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::default::Default for LoadOrigin {
    fn default() -> Self {
        LoadOrigin::Unknown
    }
}
///`LvaIpcSchemaRoot`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct LvaIpcSchemaRoot {
    pub command_envelope: CommandEnvelope,
    pub command_result: CommandResult,
    pub error_envelope: ErrorEnvelope,
    pub event_envelope: EventEnvelope,
    pub runtime_state: RuntimeState,
}
///`MemoryCommittedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct MemoryCommittedPayload {
    pub event_id: ::uuid::Uuid,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub session_id: ::std::option::Option<::uuid::Uuid>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub turn_sequence: ::std::option::Option<i64>,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`MemoryCorrectPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct MemoryCorrectPayload {
    #[serde(default = "defaults::memory_correct_payload_actor")]
    pub actor: ::std::string::String,
    pub corrected_text: ::std::string::String,
    pub event_id: ::uuid::Uuid,
    pub reason: ::std::string::String,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`MemoryEventPrecondition`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct MemoryEventPrecondition {
    pub aggregate: ::std::string::String,
    pub resource_id: ::std::string::String,
    pub revision: i64,
}
///`MemoryHardDeletePayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct MemoryHardDeletePayload {
    pub event_ids: ::std::vec::Vec<::uuid::Uuid>,
    pub reason_code: ::std::string::String,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`MemoryRecallCompletedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct MemoryRecallCompletedPayload {
    pub matched_count: i64,
    pub parse_status: ::std::string::String,
    pub query: ::std::string::String,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`MemoryRevisionAddedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct MemoryRevisionAddedPayload {
    pub event_id: ::uuid::Uuid,
    pub reason: ::std::string::String,
    pub revision: i64,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`MemorySearchPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct MemorySearchPayload {
    #[serde(default = "defaults::default_u64::<i64, 10>")]
    pub limit: i64,
    pub query: ::std::string::String,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
    #[serde(default = "defaults::memory_search_payload_user_timezone")]
    pub user_timezone: ::std::string::String,
}
///`Mode`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum Mode {
    #[serde(rename = "standby")]
    Standby,
    #[serde(rename = "passive")]
    Passive,
    #[serde(rename = "live")]
    Live,
    #[serde(rename = "privacy_pause")]
    PrivacyPause,
}
impl ::std::fmt::Display for Mode {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Standby => f.write_str("standby"),
            Self::Passive => f.write_str("passive"),
            Self::Live => f.write_str("live"),
            Self::PrivacyPause => f.write_str("privacy_pause"),
        }
    }
}
impl ::std::str::FromStr for Mode {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "standby" => Ok(Self::Standby),
            "passive" => Ok(Self::Passive),
            "live" => Ok(Self::Live),
            "privacy_pause" => Ok(Self::PrivacyPause),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for Mode {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for Mode {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`ModeChangedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct ModeChangedPayload {
    pub new_mode: Mode,
    pub previous_mode: Mode,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub resume_mode: ::std::option::Option<Mode>,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`Ownership`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum Ownership {
    #[serde(rename = "spawned")]
    Spawned,
    #[serde(rename = "adopted")]
    Adopted,
    #[serde(rename = "external")]
    External,
    #[serde(rename = "unknown")]
    Unknown,
}
impl ::std::fmt::Display for Ownership {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Spawned => f.write_str("spawned"),
            Self::Adopted => f.write_str("adopted"),
            Self::External => f.write_str("external"),
            Self::Unknown => f.write_str("unknown"),
        }
    }
}
impl ::std::str::FromStr for Ownership {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "spawned" => Ok(Self::Spawned),
            "adopted" => Ok(Self::Adopted),
            "external" => Ok(Self::External),
            "unknown" => Ok(Self::Unknown),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for Ownership {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for Ownership {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`Payload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
#[serde(tag = "type")]
pub enum Payload {
    #[serde(rename = "runtime.get_snapshot")]
    RuntimeGetSnapshot,
    ///RuntimeSetModePayload
    #[serde(rename = "runtime.set_mode")]
    RuntimeSetMode { mode: Mode },
    #[serde(rename = "runtime.restore_mode")]
    RuntimeRestoreMode,
    ///TurnSendTextPayload
    #[serde(rename = "turn.send_text")]
    TurnSendText {
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        session_id: ::std::option::Option<::uuid::Uuid>,
        text: ::std::string::String,
    },
    ///TurnCancelPayload
    #[serde(rename = "turn.cancel")]
    TurnCancel {
        #[serde(default = "defaults::payload_turn_cancel_reason")]
        reason: ::std::string::String,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        turn_id: ::std::option::Option<TurnId>,
    },
    #[serde(rename = "hub.refresh")]
    HubRefresh,
    ///HubBindModelPayload
    #[serde(rename = "hub.bind_model")]
    HubBindModel { #[serde(default)] force: bool, model_id: ::std::string::String },
    #[serde(rename = "hub.sleep_bound_model")]
    HubSleepBoundModel,
    /**HubAttestBindPayload

An effective-bind verdict reported by the process authority (PR-012).

Direction: this is an **inbound** command.  The Rust side observes the OS
listener table (plan L1256: the process authority produces the attestation;
Core does not inspect Windows state), and reports the redacted verdict to Core
over the existing authenticated WS.  Core then decides whether Hub control may
run at all (plan L665: only ``VERIFIED_LOOPBACK`` permits it).

The payload reuses the already-defined ``HubBindAttestation`` -- the same type
that travels to the WebView -- so there is exactly one verdict shape in the
contract rather than two that could drift apart.*/
    #[serde(rename = "hub.attest_bind")]
    HubAttestBind { attestation: HubBindAttestation },
    ///SettingsUpdatePublicPayload
    #[serde(rename = "settings.update_public")]
    SettingsUpdatePublic {
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        active_character: ::std::option::Option<::std::string::String>,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        autostart: ::std::option::Option<bool>,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        idle_vram_release_mins: ::std::option::Option<i64>,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        llm_mode: ::std::option::Option<SettingsUpdatePublicPayloadLlmMode>,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        local_gguf_path: ::std::option::Option<::std::string::String>,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        pet_dormancy_mode: ::std::option::Option<bool>,
        #[serde(skip_serializing_if = "::std::option::Option::is_none")]
        record_reality_during_live: ::std::option::Option<bool>,
    },
    ///SettingsSetSecretPayload
    #[serde(rename = "settings.set_secret")]
    SettingsSetSecret {
        secret_type: SettingsSetSecretPayloadSecretType,
        secret_value: ::std::string::String,
    },
    ///SettingsClearSecretPayload
    #[serde(rename = "settings.clear_secret")]
    SettingsClearSecret { secret_type: SecretType },
    ///MemorySearchPayload
    #[serde(rename = "memory.search")]
    MemorySearch {
        #[serde(default = "defaults::default_u64::<i64, 10>")]
        limit: i64,
        query: ::std::string::String,
        #[serde(default = "defaults::payload_memory_search_user_timezone")]
        user_timezone: ::std::string::String,
    },
    ///MemoryCorrectPayload
    #[serde(rename = "memory.correct")]
    MemoryCorrect {
        #[serde(default = "defaults::payload_memory_correct_actor")]
        actor: ::std::string::String,
        corrected_text: ::std::string::String,
        event_id: ::uuid::Uuid,
        reason: ::std::string::String,
    },
    ///MemoryHardDeletePayload
    #[serde(rename = "memory.hard_delete")]
    MemoryHardDelete {
        event_ids: ::std::vec::Vec<::uuid::Uuid>,
        reason_code: ::std::string::String,
    },
    ///ServiceRetryPayload
    #[serde(rename = "service.retry")]
    ServiceRetry { service_name: ::std::string::String },
    #[serde(rename = "diagnostics.export_redacted")]
    DiagnosticsExportRedacted,
}
///`PlaybackState`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug, Default)]
pub struct PlaybackState {
    #[serde(default)]
    pub active: bool,
    #[serde(default)]
    pub current_generation: i64,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub device_name: ::std::option::Option<::std::string::String>,
    #[serde(default)]
    pub muted: bool,
}
///`PrivacyScope`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum PrivacyScope {
    #[serde(rename = "VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF")]
    VerifiedAllLvaManagedCaptureOff,
    #[serde(rename = "LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT")]
    LvaCoreOffExternalCapturePresent,
    #[serde(rename = "LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN")]
    LvaCoreOffExternalCaptureUnknown,
    #[serde(rename = "NOT_PAUSED")]
    NotPaused,
}
impl ::std::fmt::Display for PrivacyScope {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::VerifiedAllLvaManagedCaptureOff => {
                f.write_str("VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF")
            }
            Self::LvaCoreOffExternalCapturePresent => {
                f.write_str("LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT")
            }
            Self::LvaCoreOffExternalCaptureUnknown => {
                f.write_str("LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN")
            }
            Self::NotPaused => f.write_str("NOT_PAUSED"),
        }
    }
}
impl ::std::str::FromStr for PrivacyScope {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF" => {
                Ok(Self::VerifiedAllLvaManagedCaptureOff)
            }
            "LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT" => {
                Ok(Self::LvaCoreOffExternalCapturePresent)
            }
            "LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN" => {
                Ok(Self::LvaCoreOffExternalCaptureUnknown)
            }
            "NOT_PAUSED" => Ok(Self::NotPaused),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for PrivacyScope {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for PrivacyScope {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`PrivacyScopeChangedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct PrivacyScopeChangedPayload {
    pub new_scope: PrivacyScope,
    pub previous_scope: PrivacyScope,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
    #[serde(default, skip_serializing_if = "::std::vec::Vec::is_empty")]
    pub unverified_reasons: ::std::vec::Vec<::std::string::String>,
}
///`ProviderState`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum ProviderState {
    #[serde(rename = "uninitialized")]
    Uninitialized,
    #[serde(rename = "ready")]
    Ready,
    #[serde(rename = "busy")]
    Busy,
    #[serde(rename = "disconnected")]
    Disconnected,
    #[serde(rename = "error")]
    Error,
}
impl ::std::fmt::Display for ProviderState {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Uninitialized => f.write_str("uninitialized"),
            Self::Ready => f.write_str("ready"),
            Self::Busy => f.write_str("busy"),
            Self::Disconnected => f.write_str("disconnected"),
            Self::Error => f.write_str("error"),
        }
    }
}
impl ::std::str::FromStr for ProviderState {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "uninitialized" => Ok(Self::Uninitialized),
            "ready" => Ok(Self::Ready),
            "busy" => Ok(Self::Busy),
            "disconnected" => Ok(Self::Disconnected),
            "error" => Ok(Self::Error),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for ProviderState {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for ProviderState {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`ProviderStateChangedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct ProviderStateChangedPayload {
    pub epoch: i64,
    pub kind: Kind,
    pub new_state: ProviderState,
    pub previous_state: ProviderState,
    pub provider_id: ::std::string::String,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`ProviderStatus`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct ProviderStatus {
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub current_model: ::std::option::Option<::std::string::String>,
    #[serde(default)]
    pub epoch: i64,
    pub kind: ProviderStatusKind,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub last_error: ::std::option::Option<::std::string::String>,
    pub provider_id: ::std::string::String,
    #[serde(default = "defaults::provider_status_state")]
    pub state: ProviderState,
}
///`ProviderStatusKind`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum ProviderStatusKind {
    #[serde(rename = "asr")]
    Asr,
    #[serde(rename = "llm")]
    Llm,
    #[serde(rename = "tts")]
    Tts,
}
impl ::std::fmt::Display for ProviderStatusKind {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Asr => f.write_str("asr"),
            Self::Llm => f.write_str("llm"),
            Self::Tts => f.write_str("tts"),
        }
    }
}
impl ::std::str::FromStr for ProviderStatusKind {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "asr" => Ok(Self::Asr),
            "llm" => Ok(Self::Llm),
            "tts" => Ok(Self::Tts),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for ProviderStatusKind {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for ProviderStatusKind {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`RuntimeControlPrecondition`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct RuntimeControlPrecondition {
    pub aggregate: ::std::string::String,
    pub revision: i64,
}
///`RuntimeGetSnapshotPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct RuntimeGetSnapshotPayload {
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`RuntimeRestoreModePayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct RuntimeRestoreModePayload {
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`RuntimeSetModePayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct RuntimeSetModePayload {
    pub mode: Mode,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`RuntimeSnapshotPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct RuntimeSnapshotPayload {
    pub state: RuntimeState,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`RuntimeState`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct RuntimeState {
    #[serde(default = "defaults::runtime_state_activity")]
    pub activity: ActivityState,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub current_turn: ::std::option::Option<TurnId>,
    #[serde(default = "defaults::runtime_state_floor")]
    pub floor: FloorOwner,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub hub_bind_attestation: ::std::option::Option<HubBindAttestation>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub hub_binding: ::std::option::Option<HubBinding>,
    #[serde(default)]
    pub hub_binding_revision: i64,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub managed_capture: ::std::option::Option<CaptureAggregate>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub mic_capture: ::std::option::Option<CaptureState>,
    #[serde(default = "defaults::runtime_state_mode")]
    pub mode: Mode,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub playback: ::std::option::Option<PlaybackState>,
    #[serde(default = "defaults::runtime_state_privacy_scope")]
    pub privacy_scope: PrivacyScope,
    #[serde(default, skip_serializing_if = ":: std :: collections :: HashMap::is_empty")]
    pub providers: ::std::collections::HashMap<::std::string::String, ProviderStatus>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub resume_mode: ::std::option::Option<Mode>,
    #[serde(default)]
    pub runtime_control_revision: i64,
    pub runtime_instance_id: ::uuid::Uuid,
    #[serde(default = "defaults::runtime_state_schema_version")]
    pub schema_version: ::std::string::String,
    #[serde(default, skip_serializing_if = ":: std :: collections :: HashMap::is_empty")]
    pub services: ::std::collections::HashMap<::std::string::String, ServiceStatus>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub session_id: ::std::option::Option<::uuid::Uuid>,
    #[serde(default)]
    pub snapshot_version: i64,
}
///`SecretType`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum SecretType {
    #[serde(rename = "cloud_api_key")]
    CloudApiKey,
    #[serde(rename = "asr_api_key")]
    AsrApiKey,
    #[serde(rename = "tts_api_key")]
    TtsApiKey,
}
impl ::std::fmt::Display for SecretType {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::CloudApiKey => f.write_str("cloud_api_key"),
            Self::AsrApiKey => f.write_str("asr_api_key"),
            Self::TtsApiKey => f.write_str("tts_api_key"),
        }
    }
}
impl ::std::str::FromStr for SecretType {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "cloud_api_key" => Ok(Self::CloudApiKey),
            "asr_api_key" => Ok(Self::AsrApiKey),
            "tts_api_key" => Ok(Self::TtsApiKey),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for SecretType {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for SecretType {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`ServiceRetryPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct ServiceRetryPayload {
    pub service_name: ::std::string::String,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`ServiceState`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum ServiceState {
    #[serde(rename = "stopped")]
    Stopped,
    #[serde(rename = "starting")]
    Starting,
    #[serde(rename = "healthy")]
    Healthy,
    #[serde(rename = "degraded")]
    Degraded,
    #[serde(rename = "failed")]
    Failed,
}
impl ::std::fmt::Display for ServiceState {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Stopped => f.write_str("stopped"),
            Self::Starting => f.write_str("starting"),
            Self::Healthy => f.write_str("healthy"),
            Self::Degraded => f.write_str("degraded"),
            Self::Failed => f.write_str("failed"),
        }
    }
}
impl ::std::str::FromStr for ServiceState {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "stopped" => Ok(Self::Stopped),
            "starting" => Ok(Self::Starting),
            "healthy" => Ok(Self::Healthy),
            "degraded" => Ok(Self::Degraded),
            "failed" => Ok(Self::Failed),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for ServiceState {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for ServiceState {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`ServiceStateChangedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct ServiceStateChangedPayload {
    pub new_state: ServiceState,
    pub previous_state: ServiceState,
    pub service_name: ::std::string::String,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`ServiceStatus`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct ServiceStatus {
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub endpoint: ::std::option::Option<::std::string::String>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub last_error: ::std::option::Option<::std::string::String>,
    pub name: ::std::string::String,
    #[serde(default = "defaults::service_status_ownership")]
    pub ownership: Ownership,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub pid: ::std::option::Option<i64>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub port: ::std::option::Option<i64>,
    #[serde(default = "defaults::service_status_state")]
    pub state: ServiceState,
}
///`SessionEndedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct SessionEndedPayload {
    pub session_id: ::uuid::Uuid,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`SessionStartedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct SessionStartedPayload {
    pub session_id: ::uuid::Uuid,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`SettingsClearSecretPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct SettingsClearSecretPayload {
    pub secret_type: SecretType,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`SettingsPrecondition`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct SettingsPrecondition {
    pub aggregate: ::std::string::String,
    pub revision: i64,
}
///`SettingsSetSecretPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct SettingsSetSecretPayload {
    pub secret_type: SettingsSetSecretPayloadSecretType,
    pub secret_value: ::std::string::String,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`SettingsSetSecretPayloadSecretType`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum SettingsSetSecretPayloadSecretType {
    #[serde(rename = "cloud_api_key")]
    CloudApiKey,
    #[serde(rename = "asr_api_key")]
    AsrApiKey,
    #[serde(rename = "tts_api_key")]
    TtsApiKey,
}
impl ::std::fmt::Display for SettingsSetSecretPayloadSecretType {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::CloudApiKey => f.write_str("cloud_api_key"),
            Self::AsrApiKey => f.write_str("asr_api_key"),
            Self::TtsApiKey => f.write_str("tts_api_key"),
        }
    }
}
impl ::std::str::FromStr for SettingsSetSecretPayloadSecretType {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "cloud_api_key" => Ok(Self::CloudApiKey),
            "asr_api_key" => Ok(Self::AsrApiKey),
            "tts_api_key" => Ok(Self::TtsApiKey),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for SettingsSetSecretPayloadSecretType {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String>
for SettingsSetSecretPayloadSecretType {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`SettingsUpdatePublicPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct SettingsUpdatePublicPayload {
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub active_character: ::std::option::Option<::std::string::String>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub autostart: ::std::option::Option<bool>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub idle_vram_release_mins: ::std::option::Option<i64>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub llm_mode: ::std::option::Option<SettingsUpdatePublicPayloadLlmMode>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub local_gguf_path: ::std::option::Option<::std::string::String>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub pet_dormancy_mode: ::std::option::Option<bool>,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub record_reality_during_live: ::std::option::Option<bool>,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`SettingsUpdatePublicPayloadLlmMode`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum SettingsUpdatePublicPayloadLlmMode {
    #[serde(rename = "local")]
    Local,
    #[serde(rename = "cloud")]
    Cloud,
}
impl ::std::fmt::Display for SettingsUpdatePublicPayloadLlmMode {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Local => f.write_str("local"),
            Self::Cloud => f.write_str("cloud"),
        }
    }
}
impl ::std::str::FromStr for SettingsUpdatePublicPayloadLlmMode {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "local" => Ok(Self::Local),
            "cloud" => Ok(Self::Cloud),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for SettingsUpdatePublicPayloadLlmMode {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String>
for SettingsUpdatePublicPayloadLlmMode {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`Severity`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum Severity {
    #[serde(rename = "info")]
    Info,
    #[serde(rename = "warning")]
    Warning,
    #[serde(rename = "error")]
    Error,
    #[serde(rename = "fatal")]
    Fatal,
}
impl ::std::fmt::Display for Severity {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Info => f.write_str("info"),
            Self::Warning => f.write_str("warning"),
            Self::Error => f.write_str("error"),
            Self::Fatal => f.write_str("fatal"),
        }
    }
}
impl ::std::str::FromStr for Severity {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "info" => Ok(Self::Info),
            "warning" => Ok(Self::Warning),
            "error" => Ok(Self::Error),
            "fatal" => Ok(Self::Fatal),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for Severity {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for Severity {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::default::Default for Severity {
    fn default() -> Self {
        Severity::Error
    }
}
///`Status`
#[derive(
    ::serde::Deserialize,
    ::serde::Serialize,
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd
)]
pub enum Status {
    #[serde(rename = "accepted")]
    Accepted,
    #[serde(rename = "applied")]
    Applied,
    #[serde(rename = "rejected")]
    Rejected,
    #[serde(rename = "duplicate")]
    Duplicate,
}
impl ::std::fmt::Display for Status {
    fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
        match *self {
            Self::Accepted => f.write_str("accepted"),
            Self::Applied => f.write_str("applied"),
            Self::Rejected => f.write_str("rejected"),
            Self::Duplicate => f.write_str("duplicate"),
        }
    }
}
impl ::std::str::FromStr for Status {
    type Err = self::error::ConversionError;
    fn from_str(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        match value {
            "accepted" => Ok(Self::Accepted),
            "applied" => Ok(Self::Applied),
            "rejected" => Ok(Self::Rejected),
            "duplicate" => Ok(Self::Duplicate),
            _ => Err("invalid value".into()),
        }
    }
}
impl ::std::convert::TryFrom<&str> for Status {
    type Error = self::error::ConversionError;
    fn try_from(
        value: &str,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
impl ::std::convert::TryFrom<::std::string::String> for Status {
    type Error = self::error::ConversionError;
    fn try_from(
        value: ::std::string::String,
    ) -> ::std::result::Result<Self, self::error::ConversionError> {
        value.parse()
    }
}
///`TurnCancelPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct TurnCancelPayload {
    #[serde(default = "defaults::turn_cancel_payload_reason")]
    pub reason: ::std::string::String,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub turn_id: ::std::option::Option<TurnId>,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`TurnCancelRequestedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct TurnCancelRequestedPayload {
    pub provider_epoch: i64,
    pub reason: ::std::string::String,
    pub turn_id: TurnId,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`TurnCancelledPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct TurnCancelledPayload {
    pub provider_epoch: i64,
    pub reason: ::std::string::String,
    pub turn_id: TurnId,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`TurnCompletedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct TurnCompletedPayload {
    pub provider_epoch: i64,
    pub reply_text: ::std::string::String,
    pub turn_id: TurnId,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`TurnId`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct TurnId {
    ///Per-session monotonic sequence number, starting at 1
    pub sequence: ::std::num::NonZeroU64,
    pub session_id: ::uuid::Uuid,
}
///`TurnSendTextPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct TurnSendTextPayload {
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub session_id: ::std::option::Option<::uuid::Uuid>,
    pub text: ::std::string::String,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
}
///`TurnStartedPayload`
#[derive(::serde::Deserialize, ::serde::Serialize, Clone, Debug)]
pub struct TurnStartedPayload {
    pub provider_epoch: i64,
    pub turn_id: TurnId,
    #[serde(rename = "type")]
    pub type_: ::std::string::String,
    #[serde(skip_serializing_if = "::std::option::Option::is_none")]
    pub user_text: ::std::option::Option<::std::string::String>,
}
/// Generation of default values for serde.
pub mod defaults {
    pub(super) fn default_bool<const V: bool>() -> bool {
        V
    }
    pub(super) fn default_u64<T, const V: u64>() -> T
    where
        T: ::std::convert::TryFrom<u64>,
        <T as ::std::convert::TryFrom<u64>>::Error: ::std::fmt::Debug,
    {
        T::try_from(V).unwrap()
    }
    pub(super) fn command_envelope_schema_version() -> ::std::string::String {
        "1.0".to_string()
    }
    pub(super) fn error_envelope_severity() -> super::Severity {
        super::Severity::Error
    }
    pub(super) fn event_envelope_schema_version() -> ::std::string::String {
        "1.0".to_string()
    }
    pub(super) fn event_envelope_payload_interrupt_committed_new_floor() -> super::FloorOwner {
        super::FloorOwner::User
    }
    pub(super) fn hub_binding_load_origin() -> super::LoadOrigin {
        super::LoadOrigin::Unknown
    }
    pub(super) fn hub_binding_status() -> super::HubBindingStatus {
        super::HubBindingStatus::Unbound
    }
    pub(super) fn interrupt_committed_payload_new_floor() -> super::FloorOwner {
        super::FloorOwner::User
    }
    pub(super) fn memory_correct_payload_actor() -> ::std::string::String {
        "user".to_string()
    }
    pub(super) fn memory_search_payload_user_timezone() -> ::std::string::String {
        "UTC".to_string()
    }
    pub(super) fn payload_memory_correct_actor() -> ::std::string::String {
        "user".to_string()
    }
    pub(super) fn payload_memory_search_user_timezone() -> ::std::string::String {
        "UTC".to_string()
    }
    pub(super) fn payload_turn_cancel_reason() -> ::std::string::String {
        "user_cancel".to_string()
    }
    pub(super) fn provider_status_state() -> super::ProviderState {
        super::ProviderState::Uninitialized
    }
    pub(super) fn runtime_state_activity() -> super::ActivityState {
        super::ActivityState::Idle
    }
    pub(super) fn runtime_state_floor() -> super::FloorOwner {
        super::FloorOwner::None
    }
    pub(super) fn runtime_state_mode() -> super::Mode {
        super::Mode::Standby
    }
    pub(super) fn runtime_state_privacy_scope() -> super::PrivacyScope {
        super::PrivacyScope::NotPaused
    }
    pub(super) fn runtime_state_schema_version() -> ::std::string::String {
        "1.0".to_string()
    }
    pub(super) fn service_status_ownership() -> super::Ownership {
        super::Ownership::Unknown
    }
    pub(super) fn service_status_state() -> super::ServiceState {
        super::ServiceState::Stopped
    }
    pub(super) fn turn_cancel_payload_reason() -> ::std::string::String {
        "user_cancel".to_string()
    }
}
/// Error types.
pub mod error {
    /// Error from a `TryFrom` or `FromStr` implementation.
    pub struct ConversionError(::std::borrow::Cow<'static, str>);
    impl ::std::error::Error for ConversionError {}
    impl ::std::fmt::Display for ConversionError {
        fn fmt(
            &self,
            f: &mut ::std::fmt::Formatter<'_>,
        ) -> Result<(), ::std::fmt::Error> {
            ::std::fmt::Display::fmt(&self.0, f)
        }
    }
    impl ::std::fmt::Debug for ConversionError {
        fn fmt(
            &self,
            f: &mut ::std::fmt::Formatter<'_>,
        ) -> Result<(), ::std::fmt::Error> {
            ::std::fmt::Debug::fmt(&self.0, f)
        }
    }
    impl From<&'static str> for ConversionError {
        fn from(value: &'static str) -> Self {
            Self(value.into())
        }
    }
    impl From<String> for ConversionError {
        fn from(value: String) -> Self {
            Self(value.into())
        }
    }
}

