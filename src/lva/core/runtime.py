from __future__ import annotations

import collections
import logging
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from ..contracts.commands import CommandEnvelope, CommandResult
from ..contracts.enums import (
    ActivityState,
    ErrorCode,
    FloorOwner,
    Mode,
    PrivacyScope,
    ProviderState,
    ServiceState,
)
from ..contracts.errors import ErrorEnvelope
from ..contracts.events import EventEnvelope, EventPayload
from ..contracts.ids import TurnId
from ..contracts.state import (
    HubBinding,
    PlaybackState,
    ProviderStatus,
    RuntimeState,
    ServiceStatus,
)
from .capture import CaptureCoordinator
from .effects import StaleEffectGate
from .floor import FloorController
from .interrupt import InterruptController
from .session import SessionController
from .turn import TurnController

log = logging.getLogger("lva.core.runtime")


class RuntimeController:
    def __init__(
        self,
        runtime_instance_id: UUID | None = None,
        event_broadcaster: Callable[[EventEnvelope], None] | None = None,
        journal: Any | None = None,
        hub_saga: Any | None = None,
        on_interrupt_action: Callable[[str], None] | None = None,
        on_mode_changed: Callable[[Mode], None] | None = None,
        turn_executor: Any | None = None,
    ) -> None:
        self.runtime_instance_id = runtime_instance_id or uuid4()
        self._event_broadcaster = event_broadcaster
        self._journal = journal
        self._hub_saga = hub_saga
        # Playback-side abort path.  Without it `commit_interrupt` only bumps the
        # Core-side epoch and cancels the turn, so a barge-in, a Standby transition
        # or a Privacy Pause would leave already-scheduled audio playing.  The
        # owner of the player (server.py) supplies the flush callback, because this
        # controller deliberately holds no provider/pipeline reference.
        self._on_interrupt_action = on_interrupt_action
        # Legacy adapter hook.  The desktop shell keeps a pre-PR-009 `VoiceCore`
        # mode mirror alive until PR-037; routing that sync through a callback
        # keeps the HTTP route a pure adapter instead of a place that mutates
        # legacy state directly (I22).
        self._on_mode_changed = on_mode_changed
        # PR-010 remainder: the turn orchestration is a Core concern but must not
        # drag concrete clients into `core/`, so the executor is injected by the
        # owner (server.py) rather than imported here.
        self.turn_executor = turn_executor
        self._snapshot_version: int = 0
        self._runtime_control_revision: int = 0
        self._hub_binding_revision: int = 0
        self._event_sequence: int = 0

        self.session_controller = SessionController(self._on_session_changed)
        self.turn_controller = TurnController(
            on_turn_started=self._on_turn_started,
            on_turn_cancelled=self._on_turn_cancelled,
            on_turn_completed=self._on_turn_completed,
        )
        self.floor_controller = FloorController(self._on_floor_changed)
        self.interrupt_controller = InterruptController(
            turn_controller=self.turn_controller,
            floor_controller=self.floor_controller,
            on_interrupt_action=on_interrupt_action,
        )
        self.stale_gate = StaleEffectGate(
            get_current_turn=lambda: self.turn_controller.current_turn,
            get_current_epoch=lambda: self.interrupt_controller.provider_epoch,
        )
        self.capture_coordinator = CaptureCoordinator()
        self.capture_coordinator.request_managed_capture_off()

        self._mode: Mode = Mode.STANDBY
        self._resume_mode: Mode | None = None
        self._activity: ActivityState = ActivityState.IDLE
        self._playback: PlaybackState = PlaybackState()
        self._services: dict[str, ServiceStatus] = {}
        self._providers: dict[str, ProviderStatus] = {}
        self._hub_binding: HubBinding | None = None
        # PR-012: the effective-bind verdict from the process authority.  ``None``
        # until one arrives, which is what keeps the control gate fail-closed.
        self._hub_bind_attestation: Any | None = None
        self.record_reality_during_live: bool = False

        # Idempotency window for commands (max 500 entries)
        self._idempotency_cache: dict[str, CommandResult] = collections.OrderedDict()
        self._max_idempotency_entries = 500

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def snapshot_version(self) -> int:
        return self._snapshot_version

    @property
    def runtime_control_revision(self) -> int:
        return self._runtime_control_revision

    @property
    def hub_binding_revision(self) -> int:
        return self._hub_binding_revision

    @property
    def current_epoch(self) -> int:
        return self.interrupt_controller.provider_epoch

    def get_state(self) -> RuntimeState:
        return RuntimeState(
            schema_version="1.0",
            runtime_instance_id=self.runtime_instance_id,
            snapshot_version=self._snapshot_version,
            runtime_control_revision=self._runtime_control_revision,
            hub_binding_revision=self._hub_binding_revision,
            mode=self._mode,
            resume_mode=self._resume_mode,
            session_id=self.session_controller.current_session_id,
            current_turn=self.turn_controller.current_turn,
            floor=self.floor_controller.owner,
            activity=self._activity,
            mic_capture=self.capture_coordinator.get_capture_state(),
            managed_capture=self.capture_coordinator.get_capture_aggregate(),
            playback=self._playback,
            services=self._services,
            providers=self._providers,
            hub_binding=self._hub_binding,
            privacy_scope=self.capture_coordinator.compute_privacy_scope(self._mode),
        )

    def emit_event(
        self,
        event_type: str,
        payload: EventPayload,
        source: str = "core.runtime",
        session_id: UUID | None = None,
        turn_id: TurnId | None = None,
    ) -> EventEnvelope:
        self._event_sequence += 1
        env = EventEnvelope(
            sequence=self._event_sequence,
            runtime_instance_id=self.runtime_instance_id,
            source=source,
            session_id=session_id or self.session_controller.current_session_id,
            turn_id=turn_id or self.turn_controller.current_turn,
            type=event_type,
            payload=payload,
        )
        if self._event_broadcaster:
            self._event_broadcaster(env)
        return env

    def set_mode(self, new_mode: Mode) -> None:
        if self._mode == new_mode:
            if new_mode == Mode.STANDBY:
                self.capture_coordinator.stop_core_mic()
                self.capture_coordinator.request_managed_capture_off()
            return

        old_mode = self._mode
        log.info("Mode transition: %s -> %s", old_mode.value, new_mode.value)

        # Mode-specific transitions
        if new_mode == Mode.PRIVACY_PAUSE:
            self._resume_mode = old_mode
            self.capture_coordinator.stop_core_mic()
            self.capture_coordinator.update_managed_capture_status(managed_stopped=None)
            # Cancel active turn and interrupt AI speech if active
            self.interrupt_controller.commit_interrupt(reason="privacy_pause")
        elif new_mode == Mode.STANDBY:
            self._resume_mode = None
            self.capture_coordinator.stop_core_mic()
            self.capture_coordinator.request_managed_capture_off()
            self.interrupt_controller.commit_interrupt(reason="standby")
        elif new_mode in (Mode.PASSIVE, Mode.LIVE):
            self._resume_mode = None
            self.capture_coordinator.start_core_mic()
            if self.session_controller.current_session_id is None:
                self.session_controller.start_session()

        self._mode = new_mode
        self._runtime_control_revision += 1
        self._snapshot_version += 1
        if self._on_mode_changed:
            try:
                self._on_mode_changed(new_mode)
            except Exception as exc:  # noqa: BLE001
                log.warning("Mode-change adapter failed for %s: %s", new_mode.value, exc)

    def restore_mode(self) -> Mode:
        """Restore previous mode after privacy pause (memory-only)."""
        target = self._resume_mode or Mode.STANDBY
        self.set_mode(target)
        return target

    def set_hub_binding(self, binding: HubBinding | None) -> None:
        self._hub_binding = binding
        self._hub_binding_revision += 1
        self._snapshot_version += 1

    def set_hub_bind_attestation(self, attestation: Any | None) -> None:
        """Record the effective-bind verdict reported by the process authority.

        PR-012: the verdict arrives over the existing authenticated WS as a
        ``hub.attest_bind`` command.  This is the single write point, so the gate
        below can never disagree with what was last received.
        """
        self._hub_bind_attestation = attestation
        self._snapshot_version += 1

    @property
    def hub_bind_attestation(self) -> Any | None:
        return self._hub_bind_attestation

    def hub_control_allowed(self, *, now: Any | None = None) -> bool:
        """May Hub lifecycle/control run right now? (plan L665)

        Three conditions, all required:

        1. an attestation has been received at all -- absence is denial, not a
           benefit of the doubt;
        2. its verdict is ``VERIFIED_LOOPBACK`` -- a wildcard or non-loopback
           listener is ``VERIFIED_NON_LOOPBACK`` and an unproven bind is
           ``UNVERIFIED_BIND``, and neither permits control;
        3. it is still **fresh** -- ``revalidate_after`` is a deadline, so a
           one-time VERIFIED cannot authorise control forever.  The frozen gate is
           a continuing condition, not a ticket.
        """
        attestation = self._hub_bind_attestation
        if attestation is None:
            return False
        if getattr(attestation, "status", None) != "VERIFIED_LOOPBACK":
            return False
        deadline = getattr(attestation, "revalidate_after", None)
        if deadline is None:
            # No deadline supplied means freshness cannot be proven; a verdict with
            # no expiry would otherwise be trusted indefinitely.
            return False
        current = now or datetime.now(timezone.utc)
        return current < deadline

    def set_provider_status(self, provider_id: str, status: ProviderStatus) -> None:
        self._providers[provider_id] = status
        self._snapshot_version += 1

    def set_service_status(self, service_name: str, status: ServiceStatus) -> None:
        self._services[service_name] = status
        self._snapshot_version += 1

    def set_activity(self, activity: ActivityState) -> None:
        self._activity = activity
        self._snapshot_version += 1

    # ----------------------------------------------------------- Command Engine
    def execute_command(self, cmd: CommandEnvelope) -> CommandResult:
        # Check idempotency
        if cmd.idempotency_key and cmd.idempotency_key in self._idempotency_cache:
            cached = self._idempotency_cache[cmd.idempotency_key]
            log.debug("Idempotent command hit for key: %s", cmd.idempotency_key)
            return CommandResult(
                command_id=cmd.command_id,
                status="duplicate",
                snapshot_version=self._snapshot_version,
                revisions=dict(cached.revisions),
                data=cached.data,
                error=cached.error,
            )

        # Aggregate / object CAS (v1.2.1 §4.4)
        rejected = self._check_precondition(cmd)
        if rejected is not None:
            return rejected

        # Execute according to command type
        before = self._revision_vector()
        try:
            res = self._dispatch_command(cmd)
        except Exception as exc:
            log.exception("Error executing command %s: %s", cmd.type, exc)
            err = ErrorEnvelope(
                code=ErrorCode.INVALID_TRANSITION,
                message=str(exc),
                retryable=False,
                severity="error",
                component="core.runtime",
                correlation_id=cmd.command_id,
            )
            res = CommandResult(
                command_id=cmd.command_id,
                status="rejected",
                snapshot_version=self._snapshot_version,
                error=err,
            )

        after = self._revision_vector()
        changed = {k: v for k, v in after.items() if before.get(k) != v}
        if res.revisions:
            changed.update(res.revisions)
        res = res.model_copy(
            update={"snapshot_version": self._snapshot_version, "revisions": changed}
        )

        # Cache idempotency
        if cmd.idempotency_key:
            if len(self._idempotency_cache) >= self._max_idempotency_entries:
                self._idempotency_cache.pop(next(iter(self._idempotency_cache)))
            self._idempotency_cache[cmd.idempotency_key] = res

        return res

    def set_journal(self, journal: Any) -> None:
        self._journal = journal

    # ------------------------------------------------- v1.2.1 aggregate CAS
    CAS_REQUIRED_AGGREGATE = {
        "runtime.set_mode": "runtime_control",
        "runtime.restore_mode": "runtime_control",
        "hub.bind_model": "hub_binding",
        "hub.sleep_bound_model": "hub_binding",
        "memory.correct": "memory_event",
        "memory.hard_delete": "memory_event",
    }

    def _revision_vector(self) -> dict[str, int]:
        return {
            "runtime_control": self._runtime_control_revision,
            "hub_binding": self._hub_binding_revision,
        }

    def _current_revision(self, aggregate: str) -> int | None:
        if aggregate == "runtime_control":
            return self._runtime_control_revision
        if aggregate == "hub_binding":
            return self._hub_binding_revision
        return None

    def _memory_target_id(self, cmd: CommandEnvelope) -> str | None:
        payload = cmd.payload
        if cmd.type == "memory.correct":
            return str(payload.event_id)
        if cmd.type == "memory.hard_delete":
            ids = [str(i) for i in payload.event_ids]
            return ids[0] if ids else None
        return None

    def _memory_event_revision(self, resource_id: str | None) -> int | None:
        if self._journal is None or not resource_id:
            return None
        row = self._journal.get_event(resource_id)
        if not row:
            return None
        value = row["current_revision"]
        return int(value) if value is not None else None

    def _cas_rejection(
        self,
        cmd: CommandEnvelope,
        aggregate: str,
        current: int | None,
        expected: int | None,
    ) -> CommandResult:
        return CommandResult(
            command_id=cmd.command_id,
            status="rejected",
            snapshot_version=self._snapshot_version,
            error=ErrorEnvelope(
                code=ErrorCode.STALE_REVISION,
                message=(
                    f"{cmd.type} requires a '{aggregate}' precondition; "
                    f"current revision is {current!r}"
                ),
                retryable=True,
                severity="warning",
                component="core.runtime",
                correlation_id=cmd.command_id,
                redacted_details={
                    "aggregate": aggregate,
                    "current_revision": current,
                    "expected_revision": expected,
                    "command_type": cmd.type,
                },
            ),
        )

    def _check_precondition(self, cmd: CommandEnvelope) -> CommandResult | None:
        """Return a STALE_REVISION result when the precondition does not hold."""
        required = self.CAS_REQUIRED_AGGREGATE.get(cmd.type)
        if required is None:
            return None

        pre = getattr(cmd, "precondition", None)
        if required == "memory_event":
            target = self._memory_target_id(cmd)
            if pre is None or getattr(pre, "aggregate", None) != "memory_event":
                return self._cas_rejection(
                    cmd, "memory_event", self._memory_event_revision(target),
                    getattr(pre, "revision", None),
                )
            if target is None or target != getattr(pre, "resource_id", None):
                return self._cas_rejection(cmd, "memory_event", None, pre.revision)
            current = self._memory_event_revision(target)
            if current is None or current != pre.revision:
                return self._cas_rejection(cmd, "memory_event", current, pre.revision)
            return None

        current = self._current_revision(required)
        if pre is None or getattr(pre, "aggregate", None) != required:
            return self._cas_rejection(
                cmd, required, current, getattr(pre, "revision", None)
            )
        if current != pre.revision:
            return self._cas_rejection(cmd, required, current, pre.revision)
        return None

    def set_hub_saga(self, saga: Any) -> None:
        self._hub_saga = saga

    def _dispatch_command(self, cmd: CommandEnvelope) -> CommandResult:
        c_type = cmd.type
        payload = cmd.payload

        if c_type == "runtime.get_snapshot":
            return CommandResult(
                command_id=cmd.command_id,
                status="applied",
                snapshot_version=self._snapshot_version,
                data=self.get_state().model_dump(mode="json"),
            )
        elif c_type == "runtime.set_mode":
            self.set_mode(payload.mode)
            return CommandResult(
                command_id=cmd.command_id,
                status="applied",
                snapshot_version=self._snapshot_version,
            )
        elif c_type == "runtime.restore_mode":
            mode = self.restore_mode()
            return CommandResult(
                command_id=cmd.command_id,
                status="applied",
                snapshot_version=self._snapshot_version,
                data={"restored_mode": mode.value},
            )
        elif c_type == "turn.send_text":
            if self._mode in (Mode.PASSIVE, Mode.STANDBY, Mode.PRIVACY_PAUSE):
                err = ErrorEnvelope(
                    code=ErrorCode.PASSIVE_PROVIDER_FORBIDDEN,
                    message=f"LLM turn scheduling is forbidden in {self._mode.value} mode",
                    severity="error",
                    component="core.turn",
                    correlation_id=cmd.command_id,
                )
                return CommandResult(
                    command_id=cmd.command_id,
                    status="rejected",
                    snapshot_version=self._snapshot_version,
                    error=err,
                )
            if self.session_controller.current_session_id is None:
                self.session_controller.start_session()
            session_id = payload.session_id or self.session_controller.current_session_id
            turn = self.turn_controller.create_turn(session_id=session_id, user_text=payload.text)
            return CommandResult(
                command_id=cmd.command_id,
                status="applied",
                snapshot_version=self._snapshot_version,
                data={
                    "turn_id": turn.model_dump(mode="json"),
                    "provider_epoch": self.interrupt_controller.provider_epoch,
                },
            )
        elif c_type == "turn.cancel":
            self.interrupt_controller.commit_interrupt(reason=payload.reason)
            return CommandResult(
                command_id=cmd.command_id,
                status="applied",
                snapshot_version=self._snapshot_version,
            )
        elif c_type == "memory.search":
            if self._journal is not None:
                hits = self._journal.search(payload.query, limit=payload.limit)
                return CommandResult(
                    command_id=cmd.command_id,
                    status="applied",
                    snapshot_version=self._snapshot_version,
                    data={"hits": hits, "query": payload.query, "n": len(hits)},
                )
            return CommandResult(
                command_id=cmd.command_id,
                status="rejected",
                snapshot_version=self._snapshot_version,
                error=ErrorEnvelope(
                    code=ErrorCode.JOURNAL_BUSY,
                    message="Journal repository not configured",
                    retryable=False,
                    severity="error",
                    component="core.journal",
                    correlation_id=cmd.command_id,
                ),
            )
        elif c_type == "memory.correct":
            if self._journal is not None:
                from ..journal.corrections import CorrectionService
                service = CorrectionService(self._journal)
                rev = service.correct_event(
                    event_id=payload.event_id,
                    corrected_text=payload.corrected_text,
                    reason=payload.reason,
                    actor=payload.actor,
                )
                return CommandResult(
                    command_id=cmd.command_id,
                    status="applied",
                    snapshot_version=self._snapshot_version,
                    data={"revision": rev, "event_id": str(payload.event_id)},
                )
            return CommandResult(
                command_id=cmd.command_id,
                status="rejected",
                snapshot_version=self._snapshot_version,
                error=ErrorEnvelope(
                    code=ErrorCode.JOURNAL_BUSY,
                    message="Journal repository not configured",
                    retryable=False,
                    severity="error",
                    component="core.journal",
                    correlation_id=cmd.command_id,
                ),
            )
        elif c_type == "memory.hard_delete":
            if self._journal is not None:
                from ..journal.privacy_deletion import PrivacyDeletionService
                service = PrivacyDeletionService(self._journal)
                count = service.hard_delete_events(
                    event_ids=payload.event_ids,
                    reason_code=payload.reason_code,
                )
                return CommandResult(
                    command_id=cmd.command_id,
                    status="applied",
                    snapshot_version=self._snapshot_version,
                    data={"deleted_count": count},
                )
            return CommandResult(
                command_id=cmd.command_id,
                status="rejected",
                snapshot_version=self._snapshot_version,
                error=ErrorEnvelope(
                    code=ErrorCode.JOURNAL_BUSY,
                    message="Journal repository not configured",
                    retryable=False,
                    severity="error",
                    component="core.journal",
                    correlation_id=cmd.command_id,
                ),
            )
        elif c_type == "diagnostics.export_redacted":
            from ..observability.diagnostics import export_redacted_diagnostics
            bundle = export_redacted_diagnostics(self, self._journal)
            return CommandResult(
                command_id=cmd.command_id,
                status="applied",
                snapshot_version=self._snapshot_version,
                data=bundle,
            )
        elif c_type == "service.retry":
            return CommandResult(
                command_id=cmd.command_id,
                status="applied",
                snapshot_version=self._snapshot_version,
                data={"service_name": payload.service_name, "action": "retry_scheduled"},
            )
        elif c_type == "hub.attest_bind":
            # PR-012: the process authority reports an effective-bind verdict.  This
            # is a report, not a control action, so it is accepted even while
            # control is denied -- it is what can *lift* the denial.
            self.set_hub_bind_attestation(payload.attestation)
            return CommandResult(
                command_id=cmd.command_id,
                status="applied",
                snapshot_version=self._snapshot_version,
                data={
                    "type": c_type,
                    "status": payload.attestation.status,
                    "control_allowed": self.hub_control_allowed(),
                },
            )
        elif c_type in ("hub.refresh", "hub.bind_model", "hub.sleep_bound_model"):
            # plan L665: only a fresh VERIFIED_LOOPBACK may run Hub control.  The
            # gate is checked here rather than at the caller so no entry point can
            # reach the saga without passing it.
            if not self.hub_control_allowed():
                return CommandResult(
                    command_id=cmd.command_id,
                    status="rejected",
                    snapshot_version=self._snapshot_version,
                    error=ErrorEnvelope(
                        code=ErrorCode.HUB_BIND_UNVERIFIED,
                        message=(
                            "Hub control requires a fresh VERIFIED_LOOPBACK bind "
                            "attestation; none is available"
                        ),
                        severity="error",
                        component="core.hub",
                        correlation_id=cmd.command_id,
                    ),
                )
            if self._hub_saga is not None:
                return CommandResult(
                    command_id=cmd.command_id,
                    status="applied",
                    snapshot_version=self._snapshot_version,
                    data={"type": c_type, "status": "delegated_to_saga"},
                )
            if c_type == "hub.refresh":
                return CommandResult(
                    command_id=cmd.command_id,
                    status="accepted",
                    snapshot_version=self._snapshot_version,
                )
            if c_type == "hub.bind_model":
                prev = self._hub_binding
                self.set_hub_binding(
                    HubBinding(
                        desired_model_id=payload.model_id,
                        active_model_id=prev.active_model_id if prev else None,
                        provider_epoch=self.current_epoch,
                        load_origin=prev.load_origin if prev else "unknown",
                        status="preparing",
                    )
                )
                return CommandResult(
                    command_id=cmd.command_id,
                    status="applied",
                    snapshot_version=self._snapshot_version,
                    data={"type": c_type, "model_id": payload.model_id},
                )
            self.set_hub_binding(None)
            return CommandResult(
                command_id=cmd.command_id,
                status="applied",
                snapshot_version=self._snapshot_version,
                data={"type": c_type},
            )
        if False:
            return CommandResult(
                command_id=cmd.command_id,
                status="accepted",
                snapshot_version=self._snapshot_version,
            )

        return CommandResult(
            command_id=cmd.command_id,
            status="accepted",
            snapshot_version=self._snapshot_version,
        )

    # ---------------------------------------------------------------- Callbacks
    def _on_session_changed(self, session_id: UUID | None) -> None:
        self._snapshot_version += 1

    def _on_turn_started(self, turn_id: TurnId) -> None:
        self._snapshot_version += 1

    def _on_turn_cancelled(self, turn_id: TurnId, reason: str) -> None:
        self._snapshot_version += 1

    def _on_turn_completed(self, turn_id: TurnId) -> None:
        self._snapshot_version += 1

    def _on_floor_changed(self, old: FloorOwner, new: FloorOwner) -> None:
        self._snapshot_version += 1
