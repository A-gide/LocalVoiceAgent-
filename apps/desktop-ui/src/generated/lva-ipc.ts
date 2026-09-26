export type RuntimeControlRevision = number;
export type HubBindingRevision = number;
export type Mode = "standby" | "passive" | "live" | "privacy_pause";
export type Mode1 = "standby" | "passive" | "live" | "privacy_pause";
export type FloorOwner = "user" | "agent" | "none";
export type ActivityState = "idle" | "listening" | "thinking" | "speaking";
export type Active = boolean;
export type DeviceName = string | null;
export type FramesCaptured = number;
export type SampleRate = number;
export type CoreMicStopped = boolean;
export type ManagedScreenpipeStopped = boolean | null;
export type ExternalScreenpipeDetected = boolean;
export type CurrentGeneration = number;
export type Name = string;
export type ServiceState = "stopped" | "starting" | "healthy" | "degraded" | "failed";
export type Ownership = "spawned" | "adopted" | "external" | "unknown";
export type Pid = number | null;
export type Port = number | null;
export type Endpoint = string | null;
export type ProviderState = "uninitialized" | "ready" | "busy" | "disconnected" | "error";
export type CurrentModel = string | null;
export type DesiredModelId = string | null;
export type ActiveModelId = string | null;
export type LoadOrigin = "loaded_by_lva" | "preexisting" | "unknown";
export type LastError = string | null;
/**
 * Why the Hub control endpoint could not be proven loopback-only (§5.8).
 *
 * The values carry no address, port or PID: this type travels to the WebView.
 */
export type HubBindReason =
  | "RESOLVED_NON_LOOPBACK"
  | "LISTENER_NON_LOOPBACK"
  | "PROCESS_UNMAPPED"
  | "HUB_INFO_UNAVAILABLE"
  | "REVALIDATION_REQUIRED"
  | "PROBE_FAILED";
export type CheckedAt = string;
export type AttestationId = string;
export type RevalidateAfter = string | null;
export type PrivacyScope =
  | "VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF"
  | "LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT"
  | "LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN"
  | "NOT_PAUSED";
export type EventId = string;
export type Sequence = number;
export type RuntimeInstanceId = string;
export type OccurredAt = string;
export type Source = string;
export type SessionId = string | null;
export type PrivacyScope1 =
  | "VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF"
  | "LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT"
  | "LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN"
  | "NOT_PAUSED";
export type UnverifiedReasons = string[];
export type UserText = string | null;
export type ReplyText = string;
export type Rms = number;
export type FloorOwner1 = "user" | "agent" | "none";
export type TimestampMs = number;
export type DurationMs = number;
export type RawText = string;
export type CorrectedText = string;
export type Domain = string | null;
export type Reason = string;
export type Type = "audio.playback_silenced";
export type ProviderEpoch = number;
export type ProviderId = string;
export type ProviderState1 = "uninitialized" | "ready" | "busy" | "disconnected" | "error";
export type Epoch = number;
export type ProgressPercent = number;
export type TurnSequence = number | null;
export type Query = string;
export type MatchedCount = number;
export type ParseStatus = string;
export type ServiceState1 = "stopped" | "starting" | "healthy" | "degraded" | "failed";
export type ErrorCode =
  | "AUTH_REQUIRED"
  | "AUTH_FAILED"
  | "ORIGIN_REJECTED"
  | "PROTOCOL_MISMATCH"
  | "STALE_REVISION"
  | "DUPLICATE_COMMAND"
  | "INVALID_TRANSITION"
  | "PASSIVE_PROVIDER_FORBIDDEN"
  | "PRIVACY_UNVERIFIED"
  | "HUB_UNAVAILABLE"
  | "HUB_VERSION_UNSUPPORTED"
  | "HUB_CONTROL_UNSAFE"
  | "HUB_BIND_UNVERIFIED"
  | "PROFILE_REQUIRED"
  | "MODEL_CONFLICT_REQUIRES_CONFIRMATION"
  | "MODEL_LOAD_FAILED"
  | "PROVIDER_DISCONNECTED"
  | "TURN_CANCELLED"
  | "STALE_EFFECT_DROPPED"
  | "JOURNAL_BUSY"
  | "IMPORT_SCHEMA_UNSUPPORTED"
  | "MIGRATION_FAILED";
export type Message = string;
export type Retryable = boolean;
export type Severity = "info" | "warning" | "error" | "fatal";
export type Component = string;
export type CorrelationId = string;
export type RedactedDetails = {
  [k: string]: unknown;
} | null;
export type Kind = "stop" | "resume";
export type SchemaVersion = "1.0";
export type CommandId = string;
export type IdempotencyKey = string | null;
export type Precondition =
  (RuntimeControlPrecondition | HubBindingPrecondition | SettingsPrecondition | MemoryEventPrecondition) | null;
export type Aggregate = "hub_binding";
export type Revision = number;
export type ResourceId = string;
export type IssuedAt = string;
export type Payload =
  | RuntimeGetSnapshotPayload
  | RuntimeSetModePayload
  | RuntimeRestoreModePayload
  | TurnSendTextPayload
  | TurnCancelPayload
  | HubRefreshPayload
  | HubBindModelPayload
  | HubSleepBoundModelPayload
  | HubAttestBindPayload
  | CaptureAckPayload
  | PlaybackSetMutedPayload
  | SettingsUpdatePublicPayload
  | SettingsSetSecretPayload
  | SettingsClearSecretPayload
  | MemorySearchPayload
  | MemoryCorrectPayload
  | MemoryHardDeletePayload
  | ServiceRetryPayload
  | DiagnosticsExportRedactedPayload;
export type Text = string;
export type ModelId = string;
export type Force = boolean;
export type OperationId = string;
export type ManagedStopped = boolean | null;
export type ExternalDetected = boolean | null;
export type Muted = boolean;
export type Autostart = boolean | null;
export type PetDormancyMode = boolean | null;
export type IdleVramReleaseMins = number | null;
export type LocalGgufPath = string | null;
export type LlmMode = ("local" | "cloud") | null;
export type ActiveCharacter = string | null;
export type RecordRealityDuringLive = boolean | null;
export type SecretValue = string;
export type SecretType = "cloud_api_key" | "asr_api_key" | "tts_api_key";
export type Limit = number;
export type UserTimezone = string;
export type Actor = string;
export type EventIds = string[];
export type ReasonCode = string;
export type ServiceName = string;
export type Status = "accepted" | "applied" | "rejected" | "duplicate";
export type SnapshotVersion = number;

export interface LvaIpcSchemaRoot {
  runtime_state: RuntimeState;
  event_envelope: EventEnvelope;
  command_envelope: CommandEnvelope;
  command_result: CommandResult;
  error_envelope: ErrorEnvelope;
}
export interface RuntimeState {
  schema_version?: "1.0";
  runtime_instance_id: string;
  snapshot_version?: number;
  runtime_control_revision?: RuntimeControlRevision;
  hub_binding_revision?: HubBindingRevision;
  mode?: Mode;
  resume_mode?: Mode1 | null;
  session_id?: string | null;
  current_turn?: TurnId | null;
  floor?: FloorOwner;
  activity?: ActivityState;
  mic_capture?: CaptureState;
  managed_capture?: CaptureAggregate;
  playback?: PlaybackState;
  services?: Services;
  providers?: Providers;
  hub_binding?: HubBinding | null;
  hub_bind_attestation?: HubBindAttestation | null;
  privacy_scope?: PrivacyScope;
}
export interface TurnId {
  session_id: string;
  /**
   * Per-session monotonic sequence number, starting at 1
   */
  sequence: number;
}
export interface CaptureState {
  active?: Active;
  device_name?: DeviceName;
  frames_captured?: FramesCaptured;
  sample_rate?: SampleRate;
}
export interface CaptureAggregate {
  core_mic_stopped?: CoreMicStopped;
  managed_screenpipe_stopped?: ManagedScreenpipeStopped;
  external_screenpipe_detected?: ExternalScreenpipeDetected;
}
export interface PlaybackState {
  active?: boolean;
  device_name?: string | null;
  current_generation?: CurrentGeneration;
  muted?: boolean;
}
export interface Services {
  [k: string]: ServiceStatus;
}
export interface ServiceStatus {
  name: Name;
  state?: ServiceState;
  ownership?: Ownership;
  pid?: Pid;
  port?: Port;
  endpoint?: Endpoint;
  last_error?: string | null;
}
export interface Providers {
  [k: string]: ProviderStatus;
}
export interface ProviderStatus {
  provider_id: string;
  kind: "asr" | "llm" | "tts";
  state?: ProviderState;
  current_model?: CurrentModel;
  epoch?: number;
  last_error?: string | null;
}
export interface HubBinding {
  desired_model_id?: DesiredModelId;
  active_model_id?: ActiveModelId;
  provider_epoch?: number;
  load_origin?: LoadOrigin;
  status?: "unbound" | "preparing" | "stopping" | "loading" | "verifying" | "ready" | "degraded" | "failed";
  last_error?: LastError;
}
/**
 * Redacted summary of the Hub effective-bind attestation (v1.2.1 §5.8).
 *
 * This travels with ``RuntimeState`` into the WebView, so it carries only the
 * verdict and coarse provenance -- never a PID, port, listener address,
 * endpoint or credential.  The raw evidence stays on the Rust diagnostics
 * surface and is correlated by ``attestation_id`` only.
 */
export interface HubBindAttestation {
  status: "VERIFIED_LOOPBACK" | "VERIFIED_NON_LOOPBACK" | "UNVERIFIED_BIND";
  reason_code?: HubBindReason | null;
  checked_at: CheckedAt;
  attestation_id: AttestationId;
  revalidate_after?: RevalidateAfter;
}
export interface EventEnvelope {
  schema_version?: "1.0";
  event_id?: EventId;
  sequence: Sequence;
  runtime_instance_id: RuntimeInstanceId;
  occurred_at?: OccurredAt;
  source: Source;
  session_id?: SessionId;
  turn_id?: TurnId | null;
  type: string;
  payload:
    | RuntimeSnapshotPayload
    | ModeChangedPayload
    | PrivacyScopeChangedPayload
    | SessionStartedPayload
    | SessionEndedPayload
    | TurnStartedPayload
    | TurnCancelRequestedPayload
    | TurnCancelledPayload
    | TurnCompletedPayload
    | InterruptDetectedPayload
    | InterruptCommittedPayload
    | InterruptSettledPayload
    | AudioVadStartedPayload
    | AudioVadEndedPayload
    | AudioUtteranceReadyPayload
    | AudioPlaybackStartedPayload
    | AudioPlaybackStopRequestedPayload
    | AudioPlaybackSilencedPayload
    | ProviderStateChangedPayload
    | HubBindingChangedPayload
    | HubOperationProgressPayload
    | MemoryCommittedPayload
    | MemoryRevisionAddedPayload
    | MemoryRecallCompletedPayload
    | ServiceStateChangedPayload
    | ErrorRaisedPayload
    | CaptureOperationRequestedPayload;
}
export interface RuntimeSnapshotPayload {
  type: "runtime.snapshot";
  state: RuntimeState;
}
export interface ModeChangedPayload {
  type: "mode.changed";
  previous_mode: Mode1;
  new_mode: Mode1;
  resume_mode?: Mode1 | null;
}
export interface PrivacyScopeChangedPayload {
  type: "privacy.scope_changed";
  previous_scope: PrivacyScope1;
  new_scope: PrivacyScope1;
  unverified_reasons?: UnverifiedReasons;
}
export interface SessionStartedPayload {
  type: "session.started";
  session_id: string;
}
export interface SessionEndedPayload {
  type: "session.ended";
  session_id: string;
}
export interface TurnStartedPayload {
  type: "turn.started";
  turn_id: TurnId;
  provider_epoch: number;
  user_text?: UserText;
}
export interface TurnCancelRequestedPayload {
  type: "turn.cancel_requested";
  turn_id: TurnId;
  provider_epoch: number;
  reason: string;
}
export interface TurnCancelledPayload {
  type: "turn.cancelled";
  turn_id: TurnId;
  provider_epoch: number;
  reason: string;
}
export interface TurnCompletedPayload {
  type: "turn.completed";
  turn_id: TurnId;
  provider_epoch: number;
  reply_text: ReplyText;
}
export interface InterruptDetectedPayload {
  type: "interrupt.detected";
  turn_id?: TurnId | null;
  provider_epoch: number;
  rms: Rms;
}
export interface InterruptCommittedPayload {
  type: "interrupt.committed";
  turn_id?: TurnId | null;
  provider_epoch: number;
  new_floor?: FloorOwner1;
}
export interface InterruptSettledPayload {
  type: "interrupt.settled";
  turn_id?: TurnId | null;
  provider_epoch: number;
}
export interface AudioVadStartedPayload {
  type: "audio.vad_started";
  timestamp_ms: TimestampMs;
}
export interface AudioVadEndedPayload {
  type: "audio.vad_ended";
  duration_ms: DurationMs;
}
export interface AudioUtteranceReadyPayload {
  type: "audio.utterance_ready";
  turn_id: TurnId;
  raw_text: RawText;
  corrected_text: CorrectedText;
  domain?: Domain;
}
export interface AudioPlaybackStartedPayload {
  type: "audio.playback_started";
  turn_id: TurnId;
  provider_epoch: number;
}
export interface AudioPlaybackStopRequestedPayload {
  type: "audio.playback_stop_requested";
  turn_id: TurnId;
  provider_epoch: number;
  reason: Reason;
}
export interface AudioPlaybackSilencedPayload {
  type: Type;
  turn_id?: TurnId | null;
  provider_epoch: ProviderEpoch;
}
export interface ProviderStateChangedPayload {
  type: "provider.state_changed";
  provider_id: ProviderId;
  kind: "asr" | "llm" | "tts";
  previous_state: ProviderState1;
  new_state: ProviderState1;
  epoch: Epoch;
}
export interface HubBindingChangedPayload {
  type: "hub.binding_changed";
  binding: HubBinding;
}
export interface HubOperationProgressPayload {
  type: "hub.operation_progress";
  operation_id: string;
  model_id: string;
  progress_percent: ProgressPercent;
  message: string;
}
export interface MemoryCommittedPayload {
  type: "memory.committed";
  event_id: string;
  session_id?: string | null;
  turn_sequence?: TurnSequence;
}
export interface MemoryRevisionAddedPayload {
  type: "memory.revision_added";
  event_id: string;
  revision: number;
  reason: string;
}
export interface MemoryRecallCompletedPayload {
  type: "memory.recall_completed";
  query: Query;
  matched_count: MatchedCount;
  parse_status: ParseStatus;
}
export interface ServiceStateChangedPayload {
  type: "service.state_changed";
  service_name: string;
  previous_state: ServiceState1;
  new_state: ServiceState1;
}
export interface ErrorRaisedPayload {
  type: "error.raised";
  error: ErrorEnvelope;
}
export interface ErrorEnvelope {
  code: ErrorCode;
  message: Message;
  retryable?: Retryable;
  severity?: Severity;
  component: Component;
  correlation_id: CorrelationId;
  redacted_details?: RedactedDetails;
}
/**
 * Core asks the capture executor to run one managed-capture operation (FIX-006).
 *
 * Direction: Core -> Desktop executor.  Before this the Core recorded capture
 * operations in its own list and nothing ever carried them to the process that
 * owns the recorder, so Privacy Pause could never be acknowledged.  The
 * operation is correlated by ``operation_id``; the executor answers with
 * ``capture.ack``.
 */
export interface CaptureOperationRequestedPayload {
  type: "capture.operation_requested";
  operation_id: string;
  kind: Kind;
}
export interface CommandEnvelope {
  schema_version?: SchemaVersion;
  command_id?: CommandId;
  idempotency_key?: IdempotencyKey;
  precondition?: Precondition;
  issued_at?: IssuedAt;
  type: string;
  payload: Payload;
}
export interface RuntimeControlPrecondition {
  aggregate: "runtime_control";
  revision: number;
}
export interface HubBindingPrecondition {
  aggregate: Aggregate;
  revision: Revision;
}
export interface SettingsPrecondition {
  aggregate: "settings";
  revision: number;
}
export interface MemoryEventPrecondition {
  aggregate: "memory_event";
  resource_id: ResourceId;
  revision: number;
}
export interface RuntimeGetSnapshotPayload {
  type: "runtime.get_snapshot";
}
export interface RuntimeSetModePayload {
  type: "runtime.set_mode";
  mode: Mode1;
}
export interface RuntimeRestoreModePayload {
  type: "runtime.restore_mode";
}
export interface TurnSendTextPayload {
  type: "turn.send_text";
  text: Text;
  session_id?: string | null;
}
export interface TurnCancelPayload {
  type: "turn.cancel";
  turn_id?: TurnId | null;
  reason?: string;
}
export interface HubRefreshPayload {
  type: "hub.refresh";
}
export interface HubBindModelPayload {
  type: "hub.bind_model";
  model_id: ModelId;
  force?: Force;
}
export interface HubSleepBoundModelPayload {
  type: "hub.sleep_bound_model";
}
/**
 * An effective-bind verdict reported by the process authority (PR-012).
 *
 * Direction: this is an **inbound** command.  The Rust side observes the OS
 * listener table (plan L1256: the process authority produces the attestation;
 * Core does not inspect Windows state), and reports the redacted verdict to Core
 * over the existing authenticated WS.  Core then decides whether Hub control may
 * run at all (plan L665: only ``VERIFIED_LOOPBACK`` permits it).
 *
 * The payload reuses the already-defined ``HubBindAttestation`` -- the same type
 * that travels to the WebView -- so there is exactly one verdict shape in the
 * contract rather than two that could drift apart.
 */
export interface HubAttestBindPayload {
  type: "hub.attest_bind";
  attestation: HubBindAttestation;
}
/**
 * The capture executor's answer to one ``capture.operation_requested`` (FIX-006).
 *
 * Direction: this is an **inbound** command.  The Desktop executor owns the
 * recorder, so it reports what actually happened; Core settles the matching
 * operation and re-derives the privacy scope.  ``managed_stopped`` is the
 * observed state (not the requested one), so an executor that failed to stop
 * reports ``False`` rather than letting Core claim a verified pause.
 */
export interface CaptureAckPayload {
  type: "capture.ack";
  operation_id: OperationId;
  managed_stopped?: ManagedStopped;
  external_detected?: ExternalDetected;
}
/**
 * Output Mute / 静音播放 (PR-024, plan L989 / L321 / L1377).
 *
 * Stops and suppresses **speaker playback only**.  It deliberately does not
 * touch capture: the Core mic, VAD/ASR, Journal and reality capture keep their
 * current state, and stopping capture remains Privacy Pause's job.
 *
 * The intent travels as a command because a local UI flag cannot stop audio
 * that the Core owns -- the shipped version changed the icon and left the
 * speakers playing.
 */
export interface PlaybackSetMutedPayload {
  type: "playback.set_muted";
  muted: Muted;
}
export interface SettingsUpdatePublicPayload {
  type: "settings.update_public";
  autostart?: Autostart;
  pet_dormancy_mode?: PetDormancyMode;
  idle_vram_release_mins?: IdleVramReleaseMins;
  local_gguf_path?: LocalGgufPath;
  llm_mode?: LlmMode;
  active_character?: ActiveCharacter;
  record_reality_during_live?: RecordRealityDuringLive;
}
export interface SettingsSetSecretPayload {
  type: "settings.set_secret";
  secret_type: "cloud_api_key" | "asr_api_key" | "tts_api_key";
  secret_value: SecretValue;
}
export interface SettingsClearSecretPayload {
  type: "settings.clear_secret";
  secret_type: SecretType;
}
export interface MemorySearchPayload {
  type: "memory.search";
  query: string;
  limit?: Limit;
  user_timezone?: UserTimezone;
}
export interface MemoryCorrectPayload {
  type: "memory.correct";
  event_id: string;
  corrected_text: string;
  reason: string;
  actor?: Actor;
}
export interface MemoryHardDeletePayload {
  type: "memory.hard_delete";
  event_ids: EventIds;
  reason_code: ReasonCode;
}
export interface ServiceRetryPayload {
  type: "service.retry";
  service_name: ServiceName;
}
export interface DiagnosticsExportRedactedPayload {
  type: "diagnostics.export_redacted";
}
export interface CommandResult {
  command_id: string;
  status: Status;
  snapshot_version: SnapshotVersion;
  revisions?: Revisions;
  data?: unknown;
  error?: ErrorEnvelope | null;
}
export interface Revisions {
  [k: string]: number;
}
