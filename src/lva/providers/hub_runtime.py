from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from ..contracts.enums import ErrorCode
from ..contracts.state import HubBinding
from .hub_control import LlamaCppHubControlClient
from .hub_inference import LlamaCppHubInferenceClient

log = logging.getLogger("lva.providers.hub_runtime")


class HubRuntimeSaga:
    def __init__(
        self,
        control_client: LlamaCppHubControlClient,
        inference_client: LlamaCppHubInferenceClient,
        on_binding_changed: Callable[[HubBinding], None] | None = None,
        on_interrupt: Callable[[str], int] | None = None,
    ) -> None:
        self.control = control_client
        self.inference = inference_client
        self.on_binding_changed = on_binding_changed
        self.on_interrupt = on_interrupt

        self.binding = HubBinding(
            desired_model_id=None,
            active_model_id=None,
            provider_epoch=0,
            load_origin="unknown",
            status="unbound",
        )
        #: The binding in effect before the current attempt (plan L636: a failed
        #: switch records it so an *explicit* rollback operation can re-bind).
        self.previous_binding: HubBinding | None = None
        #: A conflict that the caller should be told about but that does not abort
        #: the switch.  It has its own field because `_update_status` assigns
        #: `last_error` from its argument, so anything stored there is erased by the
        #: next status change.
        self.pending_conflict: str | None = None

    def _update_status(
        self,
        status: HubBinding["status"],
        last_error: str | None = None,
    ) -> None:
        self.binding.status = status
        self.binding.last_error = last_error
        if self.on_binding_changed:
            self.on_binding_changed(self.binding)

    def consume_conflict(self) -> str | None:
        """Return and clear the pending conflict, so it is reported exactly once.

        B5: the conflict is not an error -- plan 5.5 requires confirmation only for
        *stopping* a preexisting model, not for loading a new one, so the load
        proceeds.  But the code must be observable, otherwise
        `MODEL_CONFLICT_REQUIRES_CONFIRMATION` is dead and neither a caller nor the
        UI can tell the user that their old model is still resident.
        """
        conflict = self.pending_conflict
        self.pending_conflict = None
        return conflict

    def publish_conflict(self) -> None:
        """Expose the pending conflict on the binding, without consuming it.

        Called after a switch settles so a caller reading the binding (or the UI
        reading the published state) can see that the old model is still resident.
        The status stays whatever the saga decided -- a conflict is not a failure.
        """
        if self.pending_conflict and self.binding.last_error is None:
            self.binding.last_error = self.pending_conflict
            if self.on_binding_changed:
                self.on_binding_changed(self.binding)

    def rollback(self, previous: HubBinding) -> HubBinding:
        """Record the pre-attempt binding after a failed switch (L1275/L1278).

        Plan L636 is explicit about the resulting status: a failure leaves the
        binding in ``FAILED/DEGRADED``, the old turn is **not** resurrected, and
        re-binding the old model requires an **explicit rollback operation** --
        "restoring old in-memory state and pretending success" is forbidden.

        So this method records *what was serving before* for the caller to act on,
        but it must **not** flip the status back to ``ready``.  Reporting ``ready``
        here would be exactly the pretence L636 forbids: the switch did not
        succeed, so the binding has to keep saying so.
        """
        self.previous_binding = previous.model_copy(deep=True)
        self.binding.active_model_id = previous.active_model_id
        self.binding.load_origin = previous.load_origin
        # Status stays FAILED/DEGRADED -- see the docstring.  ``_update_status``
        # is deliberately not called here; the failure path already set it.
        log.warning(
            "Model switch failed; recorded previous active=%s for an explicit "
            "rollback operation (status stays %s)",
            previous.active_model_id,
            self.binding.status,
        )
        return self.binding

    async def switch_model(
        self,
        target_model_id: str,
        force_stop_preexisting: bool = False,
    ) -> HubBinding:
        """Execute explicit model change saga according to Part 5.5."""
        log.info("Starting model switch saga -> target: %s", target_model_id)
        # Remember where we were so a failure can roll back rather than leaving the
        # binding describing a model that is not actually serving.
        previous = self.binding.model_copy(deep=True)
        self.binding.desired_model_id = target_model_id
        self._update_status("preparing")

        # Step 1: PREPARE - cancel current turn and bump epoch
        if self.on_interrupt:
            new_epoch = self.on_interrupt("model_switch")
            self.binding.provider_epoch = new_epoch

        # Step 2: RESOLVE CONFLICT
        # Check currently loaded models in Hub
        try:
            loaded_models = await self.control.list_loaded()
        except Exception as exc:
            log.warning("Failed to query loaded models from Hub: %s", exc)
            loaded_models = []

        loaded_ids = {m.get("modelId") or m.get("id") for m in loaded_models}

        # If target is already loaded, skip stop/load and just verify
        if target_model_id in loaded_ids:
            log.info("Target model %s is already loaded in Hub", target_model_id)
            self._update_status("verifying")
            await self._verify_target(target_model_id)
            self.binding.active_model_id = target_model_id
            self.binding.load_origin = "preexisting"
            self._update_status("ready")
            return self.binding

        # Old model cleanup if authorized
        old_model = self.binding.active_model_id
        if old_model and old_model in loaded_ids:
            if self.binding.load_origin == "loaded_by_lva" or force_stop_preexisting:
                self._update_status("stopping")
                try:
                    await self.control.stop_model(old_model)
                    log.info("Stopped old model %s", old_model)
                except Exception as exc:
                    log.warning("Failed to stop old model %s: %s", old_model, exc)
            else:
                # Recorded on its own field so the next `_update_status` (which
                # assigns `last_error` from its argument) cannot erase it.  The
                # load still proceeds: plan 5.5 requires confirmation for
                # *stopping* a preexisting model, not for loading a new one.
                self.pending_conflict = (
                    f"{ErrorCode.MODEL_CONFLICT_REQUIRES_CONFIRMATION.value}: "
                    f"old model {old_model} was preexisting/unknown and was left "
                    "running; stopping it requires explicit confirmation"
                )
                log.warning(
                    "Old model %s was preexisting/unknown; stopping requires confirmation (%s)",
                    old_model,
                    ErrorCode.MODEL_CONFLICT_REQUIRES_CONFIRMATION,
                )

        # Step 3: LOAD TARGET
        self._update_status("loading")
        try:
            profile = await self.control.get_profile(target_model_id)
            await self.control.load_model(target_model_id, profile)
        except Exception as exc:
            # A model whose Hub profile is missing must be reported as
            # PROFILE_REQUIRED, not loaded with invented parameters (plan L593:
            # LVA must not guess -ngl/-c/mmproj).
            missing_profile = "profile" in str(exc).lower() and (
                "not found" in str(exc).lower() or "missing" in str(exc).lower() or "empty" in str(exc).lower()
            )
            code = ErrorCode.PROFILE_REQUIRED if missing_profile else ErrorCode.MODEL_LOAD_FAILED
            err_msg = f"{code.value}: failed to load model {target_model_id}: {exc}"
            log.exception(err_msg)
            self._update_status("failed", last_error=err_msg)
            # Roll back to the previously verified binding: the failed target is
            # not serving, so the binding must not claim it is.
            self.rollback(previous)
            raise

        # Step 4: VERIFY
        self._update_status("verifying")
        await self._verify_target(target_model_id)

        # Step 5: COMMIT BINDING
        self.binding.active_model_id = target_model_id
        self.binding.load_origin = "loaded_by_lva"
        # Pin the model on the inference client too.  Without this the client keeps
        # answering from the Hub default, which is exactly the "a switch silently
        # answers from the previous model" case the client documents as guarded.
        if hasattr(self.inference, "bind_model"):
            self.inference.bind_model(target_model_id)
        self._update_status("ready")
        # Surface any conflict the caller should know about (B5).  Done after the
        # status settles, because `_update_status` assigns `last_error` itself.
        self.publish_conflict()
        log.info("Model switch saga successfully committed for %s", target_model_id)
        return self.binding

    async def _verify_target(
        self,
        target_model_id: str,
        timeout: float = 30.0,
        interval: float = 1.0,
    ) -> None:
        """Poll Hub until target model appears in loaded and /v1/models."""
        # `get_event_loop()` is deprecated and returns a *new* loop when none is
        # running; a monotonic clock is both correct and simpler here.
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                models = await self.inference.list_models()
                # Exact identity, matching the conflict-resolution step below.
                # A substring test would accept `qwen3-4b` when only
                # `qwen3-4b-instruct` is actually loaded.
                if target_model_id in set(models):
                    return
            except Exception:
                pass
            await asyncio.sleep(interval)

        raise RuntimeError(
            f"Verification timed out: model '{target_model_id}' did not appear in /v1/models ({ErrorCode.MODEL_LOAD_FAILED})"
        )

    async def sleep_bound_model(self, force: bool = False) -> None:
        """Execute Sleep AI command: stops bound model if loaded by LVA (or confirmed)."""
        active = self.binding.active_model_id
        if not active:
            return

        if self.binding.load_origin == "loaded_by_lva" or force:
            self._update_status("stopping")
            try:
                await self.control.stop_model(active)
                self.binding.active_model_id = None
                self._update_status("unbound")
                log.info("Sleep AI: successfully stopped bound model %s", active)
            except Exception as exc:
                err_msg = f"Failed to stop bound model {active}: {exc}"
                self._update_status("failed", last_error=err_msg)
                raise
        else:
            log.info(
                "Sleep AI: model %s was preexisting/unknown, not stopping without confirmation",
                active,
            )
