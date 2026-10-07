"""TTL cache with single-flight.

Ten browser tabs must not become ten upstream calls -- the WEBSOCKET.md
disclaimer asks us to be a polite client. Concurrent callers for the same key
await one in-flight fetch; everyone else is served from memory until the TTL
expires.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)


class TTLCache:
    def __init__(self) -> None:
        self._values: dict[str, tuple[float, Any]] = {}
        self._flights: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def peek(self, key: str) -> tuple[Any, float] | None:
        """Return (value, age_seconds) if present, ignoring TTL."""
        hit = self._values.get(key)
        if hit is None:
            return None
        ts, value = hit
        return value, time.monotonic() - ts

    async def get(
        self,
        key: str,
        ttl: float,
        fetch: Callable[[], Awaitable[Any]],
        *,
        stale_ok: bool = True,
    ) -> Any:
        """Return a cached value, refreshing it if older than `ttl`.

        If the refresh fails but we hold a stale value, serve the stale value
        rather than failing the whole dashboard -- a slightly old price beats an
        error card. Callers can check freshness via `peek`.
        """
        hit = self._values.get(key)
        if hit is not None and time.monotonic() - hit[0] < ttl:
            return hit[1]

        async with self._lock:
            # Someone may have refreshed it while we waited for the lock.
            hit = self._values.get(key)
            if hit is not None and time.monotonic() - hit[0] < ttl:
                return hit[1]
            task = self._flights.get(key)
            if task is None:
                task = asyncio.create_task(fetch())
                self._flights[key] = task

        try:
            value = await asyncio.shield(task)
        except Exception:
            if stale_ok and hit is not None:
                log.warning("refresh of %s failed; serving stale value", key)
                return hit[1]
            raise
        finally:
            self._flights.pop(key, None)

        self._values[key] = (time.monotonic(), value)
        return value
