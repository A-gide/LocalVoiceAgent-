from __future__ import annotations

import logging
from typing import Any
import httpx

log = logging.getLogger("lva.screenpipe_importer.client")


class ScreenpipeRestClient:
    def __init__(self, base_url: str = "http://127.0.0.1:3030", timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def check_health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    async def probe_capabilities(self) -> dict[str, Any]:
        """Probe Screenpipe REST endpoint and verify capabilities per Part 7.2."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                health_resp = await client.get(f"{self.base_url}/health")
                is_healthy = health_resp.status_code == 200
                version = "unknown"
                try:
                    version_resp = await client.get(f"{self.base_url}/version")
                    if version_resp.status_code == 200:
                        version = version_resp.json().get("version", "unknown")
                except Exception:
                    pass
                return {
                    "healthy": is_healthy,
                    "version": version,
                    "supported": is_healthy,
                    "base_url": self.base_url,
                }
        except Exception as exc:
            log.warning("Screenpipe capability probe failed: %s", exc)
            return {
                "healthy": False,
                "version": "unknown",
                "supported": False,
                "base_url": self.base_url,
                "error": str(exc),
            }


    async def search(
        self,
        content_type: str = "audio",
        limit: int = 50,
        offset: int = 0,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[dict]:
        params: dict[str, str | int] = {
            "content_type": content_type,
            "limit": limit,
            "offset": offset,
        }
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/search", params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [])
