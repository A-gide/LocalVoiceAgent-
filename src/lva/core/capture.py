from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

from ..contracts.enums import Mode, PrivacyScope
from ..contracts.state import CaptureAggregate, CaptureState

log = logging.getLogger("lva.core.capture")

#: How long a managed-capture operation may stay unacknowledged before it is
#: declared timed out.  Plan L1337: on timeout the scope is *unknown*, never
#: success -- so this deadline is what protects the privacy claim.
CAPTURE_ACK_TIMEOUT = timedelta(seconds=5)

OperationKind = Literal["stop", "resume"]
OperationStatus = Literal["pending", "acknowledged", "timed_out"]


@dataclass
class CaptureOperation:
    """One request to the capture executor, correlated by operation_id.

    Plan L1335/L1345: Standby and Privacy Pause *send a managed-capture-off
    operation* and the executor answers with an operation-id ack.  A bare
    boolean cannot express "asked but not yet answered", which is exactly the
    state in which a verified scope must be refused (L1337).
    """

    operation_id: str
    kind: OperationKind
    requested_at: datetime
    deadline: datetime
    status: OperationStatus = "pending"

    def is_overdue(self, now: datetime) -> bool:
        return self.status == "pending" and now >= self.deadline


@dataclass
class CaptureCoordinator:
    on_stop_mic: Callable[[], None] | None = None
    on_start_mic: Callable[[], None] | None = None
    now: Callable[[], datetime] | None = None
    ack_timeout: timedelta = CAPTURE_ACK_TIMEOUT

    def __post_init__(self) -> None:
        self.core_mic_stopped = True
        self.managed_screenpipe_stopped: bool | None = None
        self.external_screenpipe_detected = False
        self.frames_captured = 0
        self.device_name: str | None = None
        self.operations: list[CaptureOperation] = []
        self._counter = 0

    # ---------------------------------------------------------------- clock
    def _now(self) -> datetime:
        if self.now is not None:
            return self.now()
        return datetime.now(timezone.utc)

    # ------------------------------------------------------------------ mic
    def start_core_mic(self) -> None:
        if self.on_start_mic is not None:
            try:
                self.on_start_mic()
            except Exception as exc:  # noqa: BLE001
                # L1338: never report a capture state the device did not reach.
                log.error("Core mic failed to start: %s", exc)
                self.core_mic_stopped = True
                return
        self.core_mic_stopped = False
        log.info("Core mic capture started")

    def stop_core_mic(self) -> None:
        """Physically stop the Core mic, then record the ack (plan L1335).

        The flag follows the *outcome*, not the intent: a device that refused to
        close must not be reported as stopped (L1338).
        """
        if self.on_stop_mic is not None:
            try:
                self.on_stop_mic()
            except Exception as exc:  # noqa: BLE001
                log.error("Core mic failed to stop: %s", exc)
                self.core_mic_stopped = False
                return
        self.core_mic_stopped = True
        log.info("Core mic capture physically stopped")

    # ------------------------------------------------------------ operations
    def _new_operation(self, kind: OperationKind) -> CaptureOperation:
        self._counter += 1
        requested = self._now()
        op = CaptureOperation(
            operation_id=f"cap-{self._counter}",
            kind=kind,
            requested_at=requested,
            deadline=requested + self.ack_timeout,
        )
        self.operations.append(op)
        return op

    def request_managed_capture_off(self, *, track: bool = True) -> CaptureOperation | None:
        """Ask the executor to stop LVA-managed reality capture (L1335).

        track=False is for the startup assumption only: nothing has been spawned
        yet, so there is no one to acknowledge and no operation to correlate.
        """
        if not track:
            self.managed_screenpipe_stopped = True
            return None
        op = self._new_operation("stop")
        self.managed_screenpipe_stopped = True
        log.info("Requested managed capture off (%s)", op.operation_id)
        return op

    def request_managed_capture_on(self) -> CaptureOperation:
        """Ask the executor to run LVA-managed reality capture (Passive / Live)."""
        op = self._new_operation("resume")
        self.managed_screenpipe_stopped = False
        log.info("Requested managed capture on (%s)", op.operation_id)
        return op

    def pending_operations(self) -> list[CaptureOperation]:
        return [op for op in self.operations if op.status == "pending"]

    def last_operation(self) -> CaptureOperation | None:
        return self.operations[-1] if self.operations else None

    def unsettled_stop_operations(self) -> list[CaptureOperation]:
        """Stop requests that were never answered -- pending or timed out."""
        return [
            op for op in self.operations
            if op.kind == "stop" and op.status in ("pending", "timed_out")
        ]

    def acknowledge(self, operation_id: str, managed_stopped: bool | None = None,
                    external_detected: bool | None = None) -> bool:
        """Settle the operation an executor reported on (L1345 ack)."""
        for op in self.operations:
            if op.operation_id == operation_id:
                if op.status != "pending":
                    log.warning("Ignoring duplicate ack for %s", operation_id)
                    return False
                op.status = "acknowledged"
                if managed_stopped is not None:
                    self.managed_screenpipe_stopped = managed_stopped
                if external_detected is not None:
                    self.external_screenpipe_detected = external_detected
                log.info("Capture operation %s acknowledged", operation_id)
                return True
        log.warning("Ack for unknown capture operation %s ignored", operation_id)
        return False

    def expire_overdue(self, now: datetime | None = None) -> list[CaptureOperation]:
        """Fail closed on unanswered requests (L1337/L1338).

        A timeout means the truth is *unknown*: the requested state is dropped
        rather than assumed, so the scope cannot claim success.
        """
        moment = now or self._now()
        expired: list[CaptureOperation] = []
        for op in self.operations:
            if op.is_overdue(moment):
                op.status = "timed_out"
                if op.kind == "stop":
                    self.managed_screenpipe_stopped = None
                expired.append(op)
                log.warning("Capture operation %s timed out", op.operation_id)
        return expired

    def update_managed_capture_status(
        self,
        managed_stopped: bool | None = None,
        external_detected: bool = False,
    ) -> None:
        """Legacy status report.  A definite value is also an acknowledgement.

        Kept because the shipped fault/invariant suites drive it directly, and
        because "the executor reported a definite state" is precisely what an ack
        means -- so it settles outstanding stop requests rather than leaving them
        pending forever.
        """
        self.managed_screenpipe_stopped = managed_stopped
        self.external_screenpipe_detected = external_detected
        if managed_stopped is not None:
            for op in self.operations:
                if op.kind == "stop" and op.status == "pending":
                    op.status = "acknowledged"
        log.debug(
            "Updated capture status: managed_stopped=%s, external_detected=%s",
            managed_stopped,
            external_detected,
        )

    # ----------------------------------------------------------------- scope
    def unverified_reasons(self, mode: Mode) -> list[str]:
        if mode != Mode.PRIVACY_PAUSE:
            return []
        reasons: list[str] = []
        if not self.core_mic_stopped:
            reasons.append("core_mic_still_capturing")
        if [op for op in self.pending_operations() if op.kind == "stop"]:
            reasons.append("managed_capture_off_not_acknowledged")
        if any(op.status == "timed_out" for op in self.operations if op.kind == "stop"):
            reasons.append("managed_capture_off_ack_timeout")
        if self.external_screenpipe_detected:
            reasons.append("external_screenpipe_detected")
        if self.managed_screenpipe_stopped is None:
            reasons.append("managed_capture_state_unknown")
        return reasons

    def compute_privacy_scope(self, mode: Mode) -> PrivacyScope:
        if mode != Mode.PRIVACY_PAUSE:
            return PrivacyScope.NOT_PAUSED

        # Evaluate the deadline at read time.  Nothing else ticks in production, so
        # a request whose ack never arrived has to be recognised as unanswered by
        # the very read that reports the scope (L1337).
        if any(op.status == "pending" for op in self.operations):
            self.expire_overdue()

        # L1337/L1338: an unanswered stop request can never become "verified".
        if self.unsettled_stop_operations():
            return PrivacyScope.LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN

        if self.external_screenpipe_detected:
            return PrivacyScope.LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT

        if self.core_mic_stopped and self.managed_screenpipe_stopped is True:
            return PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF

        return PrivacyScope.LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN

    # ----------------------------------------------------------------- state
    def get_capture_state(self) -> CaptureState:
        return CaptureState(
            active=not self.core_mic_stopped,
            device_name=self.device_name,
            frames_captured=self.frames_captured,
        )

    def get_capture_aggregate(self) -> CaptureAggregate:
        return CaptureAggregate(
            core_mic_stopped=self.core_mic_stopped,
            managed_screenpipe_stopped=self.managed_screenpipe_stopped,
            external_screenpipe_detected=self.external_screenpipe_detected,
        )
