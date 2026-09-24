"""Hub event-stream client with bounded-backoff reconnect (v1.2.1 PR-012).

The control client speaks request/response over HTTP.  Load is asynchronous, so
progress arrives on the Hub's event stream instead; that stream can drop, and the
frozen step list asks for **WS reconnect**.  This module owns that one concern.

Direction: this is a *client* connecting to the Hub (the opposite of the Rust
bridge, which is a client of LVA Core).  It never inspects Windows process state --
that stays on the Rust side (plan L1256).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

log = logging.getLogger("lva.providers.hub_events")

#: Bounded exponential backoff: the stream must not spin when the Hub is down.
RECONNECT_MIN_S = 0.5
RECONNECT_MAX_S = 10.0


class HubEventStreamClient:
    """Reconnecting subscriber for the Hub event stream.

    ``connect`` is injected (a websocket-connect factory) so the reconnect policy
    can be tested without a live Hub; the policy is the part this module owns.
    """

    def __init__(
        self,
        connect: Callable[[], Awaitable[object]],
        on_event: Callable[[object], None] | None = None,
        reconnect_min_s: float = RECONNECT_MIN_S,
        reconnect_max_s: float = RECONNECT_MAX_S,
    ) -> None:
        self._connect = connect
        self._on_event = on_event
        self._reconnect_min_s = reconnect_min_s
        self._reconnect_max_s = reconnect_max_s
        self._stopped = False
        self.reconnect_count = 0
        self.last_backoff_s = 0.0

    def stop(self) -> None:
        self._stopped = True

    def _next_backoff(self) -> float:
        """Grow the backoff towards the cap, starting from the floor."""
        if self.last_backoff_s <= 0.0:
            self.last_backoff_s = self._reconnect_min_s
        else:
            self.last_backoff_s = min(self.last_backoff_s * 2, self._reconnect_max_s)
        return self.last_backoff_s

    async def run(self, max_reconnects: int | None = None) -> None:
        """Connect, forward events, and reconnect with bounded backoff.

        ``max_reconnects`` bounds the loop for a test or a caller that wants a
        single attempt; production leaves it unbounded and relies on ``stop()``.
        """
        while not self._stopped:
            try:
                connection = await self._connect()
                # A successful connection resets the backoff: the next failure is
                # a fresh failure, not a continuation of the old one.
                self.last_backoff_s = 0.0
                await self._pump(connection)
            except Exception as exc:  # noqa: BLE001 - any failure means reconnect
                log.info("Hub event stream dropped: %s", exc)

            if self._stopped:
                return
            if max_reconnects is not None and self.reconnect_count >= max_reconnects:
                return

            delay = self._next_backoff()
            self.reconnect_count += 1
            log.info("Reconnecting to Hub event stream in %.2fs (attempt %d)", delay, self.reconnect_count)
            await asyncio.sleep(delay)

    async def _pump(self, connection: object) -> None:
        """Forward events until the connection fails or is stopped.

        The concrete transport is intentionally opaque here: whatever object the
        injected ``connect`` returns only has to be async-iterable.
        """
        async for event in connection:  # type: ignore[attr-defined]
            if self._stopped:
                return
            if self._on_event is not None:
                self._on_event(event)
