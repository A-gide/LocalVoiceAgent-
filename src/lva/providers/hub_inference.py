from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Callable
import httpx

from ..contracts.ids import TurnId

log = logging.getLogger("lva.providers.hub_inference")


class LlamaCppHubInferenceClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        api_key: str = "",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport

    @property
    def name(self) -> str:
        return "llama_hub"

    async def list_models(self) -> list[str]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=10.0, transport=self.transport) as client:
            resp = await client.get(f"{self.base_url}/v1/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", []) if "id" in m]

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        turn_id: TurnId,
        provider_epoch: int,
        is_cancelled: Callable[[], bool] | None = None,
        model: str = "default",
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=body,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if is_cancelled and is_cancelled():
                        log.debug(
                            "Inference stream cancelled for turn %s (epoch %d)",
                            turn_id,
                            provider_epoch,
                        )
                        break

                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue

                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue
