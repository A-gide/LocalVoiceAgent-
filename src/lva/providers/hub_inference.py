"""Hub inference provider (v1.2.1 PR-013).

`Current -> target` (plan L1263): the 1234 default client becomes a Hub `/v1`
streaming client with a generic fallback.  Steps (L1265): model binding
header/body; SSE parser; **reasoning/content separation**; cancel close; **error
mapping**.  Acceptance (L1267): streaming / cancel / reconnect / **partial UTF-8**;
no direct child endpoint dependency.

Hard constraint 2 keeps the Hub as the model runtime authority: this module never
spawns or supervises a backend, it only speaks HTTP/SSE to the Hub.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Callable

import httpx

from ..contracts.enums import ErrorCode
from .. import config as C
from ..contracts.errors import ErrorEnvelope
from ..contracts.ids import TurnId

log = logging.getLogger("lva.providers.hub_inference")

#: Bounded retry for a stream that drops before delivering anything.
RECONNECT_ATTEMPTS = 3
RECONNECT_BACKOFF_S = 0.5


class HubInferenceError(RuntimeError):
    """An inference failure carrying a frozen error code.

    `raise_for_status()` alone would hand the caller an httpx exception, which
    cannot be classified at the boundary; this carries the stable code instead.
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_envelope(self, correlation_id: str | None = None) -> ErrorEnvelope:
        return ErrorEnvelope(
            code=self.code,
            message=str(self),
            severity="error",
            component="providers.hub_inference",
            correlation_id=correlation_id,
        )


def _classify_status(status: int) -> ErrorCode:
    if status in (401, 403):
        return ErrorCode.AUTH_FAILED
    if status == 404:
        return ErrorCode.MODEL_LOAD_FAILED
    if status >= 500:
        return ErrorCode.PROVIDER_DISCONNECTED
    return ErrorCode.HUB_UNAVAILABLE


class LlamaCppHubInferenceClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str = "",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
        bound_model_id: str | None = None,
    ) -> None:
        # Single source: the configured Hub endpoint (see `config.hub_base_url`).
        self.base_url = (base_url or C.hub_base_url()).rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport
        # The *bound* model identity, pinned per request.  Leaving it to the Hub
        # default would let a switch silently answer from the previous model.
        self.bound_model_id = bound_model_id

    @property
    def name(self) -> str:
        return "llama_hub"

    def bind_model(self, model_id: str | None) -> None:
        """Pin the model this client should answer from (PR-014 commits it)."""
        self.bound_model_id = model_id

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.bound_model_id:
            # Model binding header (plan L1265): lets the Hub route to the bound
            # instance even when several models are loaded.
            headers["X-LVA-Bound-Model"] = self.bound_model_id
        return headers

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10.0, transport=self.transport) as client:
            resp = await client.get(f"{self.base_url}/v1/models", headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", []) if "id" in m]

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        turn_id: TurnId,
        provider_epoch: int,
        is_cancelled: Callable[[], bool] | None = None,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream content deltas, separating reasoning from the spoken reply.

        Reasoning deltas are dropped rather than spoken: a reasoning model that
        leaks its thinking into the reply would read it aloud.  A stream that
        drops before delivering anything is retried with bounded backoff; once a
        delta has been yielded a retry would duplicate text, so it is not done.
        """
        model_id = model or self.bound_model_id or "default"
        body = {
            "model": model_id,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        emitted = False
        for attempt in range(1, RECONNECT_ATTEMPTS + 1):
            try:
                async for piece in self._stream_once(body, turn_id, provider_epoch, is_cancelled):
                    emitted = True
                    yield piece
                return
            except HubInferenceError:
                raise
            except Exception as exc:  # noqa: BLE001 - transport failure
                if emitted or attempt >= RECONNECT_ATTEMPTS:
                    raise HubInferenceError(
                        ErrorCode.PROVIDER_DISCONNECTED,
                        f"Hub inference stream failed after {attempt} attempt(s): {exc}",
                    ) from exc
                delay = RECONNECT_BACKOFF_S * attempt
                log.warning(
                    "Hub inference stream dropped before any output (attempt %d/%d); retrying in %.1fs: %s",
                    attempt, RECONNECT_ATTEMPTS, delay, exc,
                )
                await asyncio.sleep(delay)

    async def _stream_once(
        self,
        body: dict,
        turn_id: TurnId,
        provider_epoch: int,
        is_cancelled: Callable[[], bool] | None,
    ) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json=body,
            ) as response:
                if response.status_code >= 400:
                    raise HubInferenceError(
                        _classify_status(response.status_code),
                        f"Hub inference returned HTTP {response.status_code}",
                    )
                # SSE is a byte stream: a multi-byte character can be split across
                # chunks, so iterate bytes and decode incrementally rather than
                # decoding each chunk on its own.
                buffer = b""
                async for raw in response.aiter_bytes():
                    if is_cancelled and is_cancelled():
                        log.debug(
                            "Inference stream cancelled for turn %s (epoch %d)",
                            turn_id, provider_epoch,
                        )
                        return
                    buffer += raw
                    while b"\n" in buffer:
                        line_bytes, buffer = buffer.split(b"\n", 1)
                        line = line_bytes.decode("utf-8", errors="replace").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            return
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        # Reasoning stays out of the spoken reply.
                        if delta.get("reasoning_content") or delta.get("reasoning"):
                            log.debug("Dropping reasoning delta for turn %s", turn_id)
                            continue
                        content = delta.get("content", "")
                        if content:
                            yield content
