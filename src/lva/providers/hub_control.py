from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse
import httpx

from ..contracts.enums import ErrorCode
from .hub_contracts_v0_9_8_3 import (
    HubHandshake,
    HubLoadRequestV0_9_8_3,
    classify_version,
    load_request_from_profile,
    supports,
)

log = logging.getLogger("lva.providers.hub_control")


class HubOperation:
    """State of one asynchronous Hub operation (PR-012 L1255).

    ``state`` moves ``pending`` -> ``ready`` / ``failed``; ``verified`` records
    whether readiness was actually proven, so an acknowledgement alone can never
    be mistaken for completion.
    """

    def __init__(self, operation_id: str, model_id: str) -> None:
        self.operation_id = operation_id
        self.model_id = model_id
        self.state = "pending"
        self.progress_percent = 0.0
        self.message = ""
        self.finished = False
        self.verified = False


class LlamaCppHubControlClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
        api_key: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport
        # The real Hub ships with `security.apiKeyEnabled: true`, so every
        # management request must carry the key.  Held in memory only; never
        # logged and never written to disk.
        self.api_key = api_key
        self._verify_loopback_safety(self.base_url)
        self.handshake: HubHandshake | None = None
        self._operations: dict[str, "HubOperation"] = {}

    @staticmethod
    def _verify_loopback_safety(url: str) -> None:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(
                f"Non-loopback Hub management URL '{url}' is rejected for safety ({ErrorCode.HUB_CONTROL_UNSAFE})"
            )

    async def get_version(self) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            resp = await client.get(f"{self.base_url}/api/sys/version", headers=self._auth_headers())
            resp.raise_for_status()
            return resp.json()

    def _auth_headers(self) -> dict[str, str]:
        """Management-request headers.  The key is never logged."""
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    # --------------------------------------------------------- handshake (L575)
    async def probe_handshake(self) -> HubHandshake:
        """Run the versioned handshake and cache the verdict.

        Plan L575-582: version + node info decide READY / DEGRADED, and anything
        that cannot be proven disables management.  A missing or unparseable
        version is DEGRADED (reachable, capabilities disabled) -- never READY, and
        not UNAVAILABLE either, because the process answered.
        """
        try:
            info = await self.get_version()
        except Exception as exc:  # noqa: BLE001 - unreachable Hub is a valid outcome
            log.info("Hub unreachable during handshake: %s", exc)
            self.handshake = HubHandshake.UNAVAILABLE
            return self.handshake

        # The real /api/sys/version nests its payload:
        #   {"success":true,"data":{"tag":"v0.9.8.3","version":"0.9.8.3"}}
        # Reading only the top level classified a healthy pinned Hub as DEGRADED,
        # which would have disabled Hub control against every real deployment.
        reported = None
        if isinstance(info, dict):
            payload = info.get("data") if isinstance(info.get("data"), dict) else info
            reported = payload.get("version") or payload.get("tag")
            if isinstance(reported, str) and reported.startswith("v"):
                reported = reported[1:]
        self.handshake = classify_version(reported)
        log.info("Hub handshake: reported=%s verdict=%s", reported, self.handshake.value)
        return self.handshake

    def supports(self, operation: str) -> bool:
        """Whether ``operation`` may be attempted under the current handshake.

        Before a handshake the answer is **false** for everything: fail closed
        rather than assume a capability we have not confirmed.
        """
        if self.handshake is None:
            return False
        return supports(operation, self.handshake)

    async def _require(self, operation: str) -> None:
        if self.handshake is None:
            await self.probe_handshake()
        if not self.supports(operation):
            raise RuntimeError(
                f"Hub operation '{operation}' is not available under "
                f"{(self.handshake or HubHandshake.UNAVAILABLE).value}"
            )

    # -------------------------------------------------- operations (L1255)
    def begin_operation(self, operation_id: str, model_id: str) -> "HubOperation":
        """Track an async Hub operation by id.

        A Hub load is asynchronous: the HTTP response is an acknowledgement, not
        completion, so progress is tracked against an explicit operation id (the
        contract already carries ``hub.operation_progress`` with that id).
        """
        op = HubOperation(operation_id=operation_id, model_id=model_id)
        self._operations[operation_id] = op
        return op

    def operation(self, operation_id: str) -> "HubOperation | None":
        return self._operations.get(operation_id)

    def note_progress(self, operation_id: str, percent: float, message: str = "") -> None:
        op = self._operations.get(operation_id)
        if op is not None:
            op.progress_percent = percent
            op.message = message

    def complete_operation(self, operation_id: str, *, verified: bool) -> None:
        """Mark an operation finished.

        ``verified=False`` means the acknowledgement arrived but readiness was not
        proven, so the operation is reported as failed rather than silently ready.
        """
        op = self._operations.get(operation_id)
        if op is None:
            return
        op.finished = True
        op.verified = verified
        op.state = "ready" if verified else "failed"

    async def get_node_info(self) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            resp = await client.get(f"{self.base_url}/api/node/info", headers=self._auth_headers())
            resp.raise_for_status()
            return resp.json()

    async def verify_loaded(self, model_id: str, *, attempts: int = 5, delay_s: float = 0.5) -> bool:
        """Bounded poll until ``model_id`` appears in the loaded set (plan L594-595).

        This is the step that stops an HTTP acknowledgement from being misread as
        readiness: the target must actually appear as loaded.
        """
        for attempt in range(attempts):
            try:
                loaded = await self.list_loaded()
            except Exception as exc:  # noqa: BLE001
                log.info("verify_loaded attempt %d failed: %s", attempt + 1, exc)
                loaded = []
            if any(str(item.get("modelId", item.get("id", ""))) == model_id for item in loaded):
                return True
            if attempt + 1 < attempts:
                await asyncio.sleep(delay_s)
        return False

    async def list_models(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            resp = await client.get(f"{self.base_url}/api/models/list", headers=self._auth_headers())
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return data.get("data", data.get("models", []))

    async def list_loaded(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            resp = await client.get(f"{self.base_url}/api/models/loaded", headers=self._auth_headers())
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return data.get("data", data.get("models", []))

    async def refresh_models(self) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            resp = await client.get(f"{self.base_url}/api/models/refresh", headers=self._auth_headers())
            resp.raise_for_status()
            return resp.json()

    async def get_profile(self, model_id: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            resp = await client.get(f"{self.base_url}/api/models/config/get", params={"modelId": model_id}, headers=self._auth_headers())
            if resp.status_code == 404:
                raise RuntimeError(
                    f"Model profile not found for '{model_id}' ({ErrorCode.PROFILE_REQUIRED})"
                )
            resp.raise_for_status()
            data = resp.json()
            if not data or not isinstance(data, dict):
                raise RuntimeError(
                    f"Model profile missing or empty for '{model_id}' ({ErrorCode.PROFILE_REQUIRED})"
                )
            return data

    async def load_model(self, model_id: str, profile: dict | None = None) -> dict:
        """Issue load command to Hub.

        If profile is not provided, fetches it via get_profile.
        Returns the Hub operation acknowledgement. Note that this does NOT mean the model
        is ready yet; the caller must verify loaded status and inference readiness.
        """
        await self._require("models.load")
        if profile is None:
            profile = await self.get_profile(model_id)

        # Validate the profile against the pinned version before sending it, so a
        # profile missing a field the Hub requires is reported rather than guessed
        # (plan L593: LVA must not invent -ngl/-c/mmproj).
        request = load_request_from_profile(model_id, profile)

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            resp = await client.post(
                f"{self.base_url}/api/models/load",
                json=request.model_dump(exclude_none=True),
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def stop_model(self, model_id: str) -> dict:
        """Issue explicit stop command to Hub. Hub has no auto-unload."""
        await self._require("models.stop")
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            resp = await client.post(
                f"{self.base_url}/api/models/stop",
                json={"modelId": model_id},
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            return resp.json()
