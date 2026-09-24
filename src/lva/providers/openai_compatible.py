from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Callable
import httpx

from ..contracts.ids import TurnId

log = logging.getLogger("lva.providers.openai_compatible")


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080/v1",
        api_key: str = "",
        model: str = "default",
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "openai_compatible"

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        turn_id: TurnId,
        provider_epoch: int,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> AsyncIterator[str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if is_cancelled and is_cancelled():
                        log.debug("Cancelled stream for turn %s", turn_id)
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
