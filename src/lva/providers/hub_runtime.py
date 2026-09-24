from __future__ import annotations

import asyncio
import logging
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

    def _update_status(
        self,
        status: HubBinding["status"],
        last_error: str | None = None,
    ) -> None:
        self.binding.status = status
        self.binding.last_error = last_error
        if self.on_binding_changed:
            self.on_binding_changed(self.binding)

    async def switch_model(
        self,
        target_model_id: str,
        force_stop_preexisting: bool = False,
    ) -> HubBinding:
        """Execute explicit model change saga according to Part 5.5."""
        log.info("Starting model switch saga -> target: %s", target_model_id)
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
            err_msg = f"Failed to load model {target_model_id}: {exc}"
            log.exception(err_msg)
            self._update_status("failed", last_error=err_msg)
            raise

        # Step 4: VERIFY
        self._update_status("verifying")
        await self._verify_target(target_model_id)

        # Step 5: COMMIT BINDING
        self.binding.active_model_id = target_model_id
        self.binding.load_origin = "loaded_by_lva"
        self._update_status("ready")
        log.info("Model switch saga successfully committed for %s", target_model_id)
        return self.binding

    async def _verify_target(
        self,
        target_model_id: str,
        timeout: float = 30.0,
        interval: float = 1.0,
    ) -> None:
        """Poll Hub until target model appears in loaded and /v1/models."""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            try:
                models = await self.inference.list_models()
                if any(target_model_id in m for m in models):
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
