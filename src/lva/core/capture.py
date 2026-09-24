from __future__ import annotations

import logging
from typing import Callable

from ..contracts.enums import Mode, PrivacyScope
from ..contracts.state import CaptureAggregate, CaptureState

log = logging.getLogger("lva.core.capture")


class CaptureCoordinator:
    def __init__(
        self,
        on_stop_mic: Callable[[], None] | None = None,
        on_start_mic: Callable[[], None] | None = None,
    ) -> None:
        self._on_stop_mic = on_stop_mic
        self._on_start_mic = on_start_mic
        self.core_mic_stopped: bool = True
        self.managed_screenpipe_stopped: bool | None = None
        self.external_screenpipe_detected: bool = False
        self.frames_captured: int = 0
        self.device_name: str | None = None

    def start_core_mic(self) -> None:
        self.core_mic_stopped = False
        log.info("Core mic capture started")
        if self._on_start_mic:
            self._on_start_mic()

    def stop_core_mic(self) -> None:
        self.core_mic_stopped = True
        log.info("Core mic capture physically stopped")
        if self._on_stop_mic:
            self._on_stop_mic()

    def request_managed_capture_off(self) -> None:
        self.managed_screenpipe_stopped = True
        log.info("Requested managed capture off")

    def update_managed_capture_status(
        self,
        managed_stopped: bool | None = None,
        external_detected: bool = False,
    ) -> None:
        self.managed_screenpipe_stopped = managed_stopped
        self.external_screenpipe_detected = external_detected
        log.debug(
            "Updated capture status: managed_stopped=%s, external_detected=%s",
            managed_stopped,
            external_detected,
        )

    def compute_privacy_scope(self, mode: Mode) -> PrivacyScope:
        if mode != Mode.PRIVACY_PAUSE:
            return PrivacyScope.NOT_PAUSED

        if (
            self.core_mic_stopped
            and self.managed_screenpipe_stopped is True
            and not self.external_screenpipe_detected
        ):
            return PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF

        if self.external_screenpipe_detected:
            return PrivacyScope.LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT

        return PrivacyScope.LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN

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
