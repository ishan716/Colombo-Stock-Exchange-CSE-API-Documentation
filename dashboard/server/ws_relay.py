"""One upstream STOMP connection, fanned out to every browser client.

WEBSOCKET.md asks callers to keep to one connection and not hammer
`/app/request-*`, so the server holds exactly one and rebroadcasts. Browser tabs
connect to our own /ws instead.

Two documented quirks are handled here:
  * the server negotiates `heart-beat:0,0` and sends nothing while idle, so the
    socket read must time out and be retried rather than treated as a failure;
  * a feed's timestamp is an epoch int on `/user/topic/*` replies but an ISO-8601
    string on `/topic/*` broadcasts. Both are normalised to epoch ms before
    reaching the browser.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime

import websocket

log = logging.getLogger(__name__)

URL = "wss://www.cse.lk/api/ws/websocket"
NUL = "\x00"
RECONNECT_DELAY = 5.0  # the site's own client uses reconnectDelay: 5000

FEEDS = [
    "aspi",
    "snp",
    "summary",
    "status",
    "top-gainers",
    "top-looses",
    "most-active-trades",
]

# Fields that arrive as either epoch ms or ISO-8601 depending on the path.
TIME_FIELDS = ("timestamp", "tradeDate", "tradesTime", "lastTradedTime")


def _frame(command: str, headers: dict, body: str = "") -> str:
    head = "".join(f"{k}:{v}\n" for k, v in headers.items())
    return f"{command}\n{head}\n{body}{NUL}"


def _parse(msg: str) -> tuple[str, dict, str]:
    head, _, body = msg.partition("\n\n")
    lines = head.split("\n")
    headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
    return lines[0], headers, body.rstrip(NUL)


def _to_epoch_ms(value):
    """Normalise a CSE timestamp to epoch milliseconds."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value:
        try:
            # e.g. "2026-09-07T06:41:48.539+0000"
            return int(
                datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z").timestamp() * 1000
            )
        except ValueError:
            return value
    return value


def normalise(payload):
    """Recursively rewrite timestamp fields to epoch ms."""
    if isinstance(payload, list):
        return [normalise(x) for x in payload]
    if isinstance(payload, dict):
        return {
            k: (_to_epoch_ms(v) if k in TIME_FIELDS else normalise(v))
            for k, v in payload.items()
        }
    return payload


class Relay:
    """Holds the upstream feed and the set of connected browser clients."""

    def __init__(self) -> None:
        self.latest: dict[str, object] = {}   # feed -> most recent payload
        self.connected = False
        self._subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    # --- browser side ------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _publish(self, feed: str, payload) -> None:
        self.latest[feed] = payload
        message = {"feed": feed, "data": payload}
        for q in list(self._subscribers):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                # A slow tab must not stall the relay; it will catch up from
                # the snapshot on its next reconnect.
                pass

    # --- upstream side -----------------------------------------------------

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._pump)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("relay error: %s", exc)
            self.connected = False
            self._notify_status()
            await asyncio.sleep(RECONNECT_DELAY)

    def _notify_status(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(
            self._publish, "_relay", {"connected": self.connected}
        )

    def _pump(self) -> None:
        """Blocking STOMP loop. Runs on a worker thread."""
        ws = websocket.create_connection(
            URL,
            timeout=30,
            origin="https://www.cse.lk",
            header={"User-Agent": "Mozilla/5.0"},
        )
        try:
            ws.send(_frame("CONNECT", {"accept-version": "1.2", "host": "www.cse.lk"}))
            command, _, _ = _parse(ws.recv())
            if command != "CONNECTED":
                raise RuntimeError(f"expected CONNECTED, got {command}")

            for i, feed in enumerate(FEEDS):
                ws.send(_frame("SUBSCRIBE", {"id": f"s{i}",
                                             "destination": f"/topic/{feed}"}))
                ws.send(_frame("SUBSCRIBE", {"id": f"u{i}",
                                             "destination": f"/user/topic/{feed}"}))
            # One snapshot request per feed on connect, then broadcasts only.
            for feed in FEEDS:
                ws.send(_frame("SEND", {"destination": f"/app/request-{feed}"}))

            self.connected = True
            self._notify_status()
            log.info("relay connected to %s", URL)

            ws.settimeout(5)
            while True:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue  # heart-beat:0,0 -- silence is normal
                if not raw:
                    raise RuntimeError("upstream closed")
                command, headers, body = _parse(raw)
                if command != "MESSAGE":
                    continue
                destination = headers.get("destination", "")
                feed = destination.rsplit("/", 1)[-1]
                if feed not in FEEDS:
                    continue
                try:
                    payload = normalise(json.loads(body))
                except json.JSONDecodeError:
                    continue
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(self._publish, feed, payload)
        finally:
            with contextlib.suppress(Exception):
                ws.close()
