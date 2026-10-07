"""FastAPI app: CSE proxy, portfolio API, and the browser-facing WebSocket."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from contextlib import asynccontextmanager

from .cache import TTLCache
from .cse import CSEClient, CSEError
from .portfolio import build, load_holdings
from . import sectors, securities, ws_relay

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dashboard")

ROOT = Path(__file__).resolve().parent.parent
HOLDINGS_PATH = ROOT / "holdings.json"
WEB_DIR = ROOT / "web"

COLOMBO = ZoneInfo("Asia/Colombo")
OPEN_TIME, CLOSE_TIME = dtime(9, 30), dtime(14, 30)

# Poll fast enough to feel live, slow enough to stay a polite client.
TTL_TRADE_SUMMARY_OPEN = 15.0
TTL_TRADE_SUMMARY_CLOSED = 300.0
TTL_SECTORS = 60.0
TTL_CHART = 900.0

cache = TTLCache()
client = CSEClient()
relay = ws_relay.Relay()


@asynccontextmanager
async def lifespan(_: FastAPI):
    relay.start()
    yield
    await relay.stop()
    await client.aclose()


app = FastAPI(title="CSE Dashboard", lifespan=lifespan)


def market_is_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(COLOMBO)
    if now.weekday() >= 5:  # Sat/Sun
        return False
    return OPEN_TIME <= now.time() <= CLOSE_TIME


def trade_summary_ttl() -> float:
    return TTL_TRADE_SUMMARY_OPEN if market_is_open() else TTL_TRADE_SUMMARY_CLOSED




# --- holdings ---------------------------------------------------------------

def read_holdings() -> list[dict]:
    if not HOLDINGS_PATH.exists():
        return []
    return json.loads(HOLDINGS_PATH.read_text())


def write_holdings(rows: list[dict]) -> None:
    """Atomic write -- a crash mid-save must not corrupt the file."""
    HOLDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=HOLDINGS_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(rows, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, HOLDINGS_PATH)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def validate_holdings(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise HTTPException(400, "expected a list of holdings")
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            raise HTTPException(400, "each holding must be an object")
        try:
            symbol = str(row["symbol"]).strip().upper()
            qty = int(row["qty"])
            avg = float(row["avgPrice"])
            bes = float(row.get("besPrice") or avg)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(400, f"invalid holding {row!r}: {exc}") from exc
        if not symbol:
            raise HTTPException(400, "symbol cannot be empty")
        if qty <= 0 or avg <= 0 or bes <= 0:
            raise HTTPException(400, f"{symbol}: qty and prices must be positive")
        cleaned.append({"symbol": symbol, "qty": qty, "avgPrice": avg,
                        "besPrice": bes})
    return cleaned


@app.get("/api/holdings")
async def get_holdings():
    return read_holdings()


@app.put("/api/holdings")
async def put_holdings(rows: list = Body(...)):
    cleaned = validate_holdings(rows)
    write_holdings(cleaned)
    return cleaned


# --- market data ------------------------------------------------------------

async def cached_trade_summary() -> list[dict]:
    """The full-market price snapshot every other route builds on."""
    try:
        return await cache.get(
            "tradeSummary", trade_summary_ttl(), client.trade_summary
        )
    except CSEError as exc:
        raise HTTPException(502, f"upstream unavailable: {exc}") from exc


@app.get("/api/portfolio")
async def get_portfolio():
    summary = await cached_trade_summary()
    cached = cache.peek("tradeSummary")
    pf = build(load_holdings(read_holdings()), summary)
    return {
        "portfolio": asdict(pf),
        "asOfAgeSeconds": round(cached[1], 1) if cached else None,
        "marketOpen": market_is_open(),
    }


@app.get("/api/sectors")
async def get_sectors():
    try:
        raw = await cache.get("allSectors", TTL_SECTORS, client.all_sectors)
    except CSEError as exc:
        raise HTTPException(502, f"upstream unavailable: {exc}") from exc

    rows = []
    for s in raw:
        sector_id = s.get("sectorId")
        # Two of the 22 sectors return a null percentage; keep them in the list
        # but mark them so the UI can grey them out instead of crashing.
        pct = s.get("percentage")
        rows.append(
            {
                "sectorId": sector_id,
                "symbol": s.get("symbol"),
                "name": s.get("name") or sectors.SECTOR_NAMES.get(sector_id, "?"),
                "indexValue": s.get("indexValue"),
                "change": s.get("change"),
                "percentage": pct,
                "turnover": s.get("sectorTurnoverToday") or 0,
                "volume": s.get("sectorVolumeToday") or 0,
                "trades": s.get("sectorTradeToday") or 0,
                "hasData": pct is not None,
            }
        )
    # Indices, not sectors -- shown separately in the header.
    rows = [r for r in rows if r["sectorId"] not in (1, 40)]
    rows.sort(key=lambda r: (r["percentage"] is None, -(r["percentage"] or 0)))
    return rows


@app.get("/api/market")
async def get_market():
    """Snapshot for first paint; live updates then arrive over /ws."""
    return {
        "marketOpen": market_is_open(),
        "relayConnected": relay.connected,
        "feeds": relay.latest,
    }


@app.get("/api/chart/{stock_id}")
async def get_chart(stock_id: int, period: int = 3):
    try:
        data = await cache.get(
            f"chart:{stock_id}:{period}",
            TTL_CHART,
            lambda: client.stock_chart(stock_id, period),
        )
    except CSEError as exc:
        raise HTTPException(502, f"upstream unavailable: {exc}") from exc
    # Series points: t=epoch ms, p=price.
    return [
        {"t": p.get("t"), "p": p.get("p"), "h": p.get("h"), "l": p.get("l")}
        for p in data
        if p.get("p") is not None
    ]


# --- stock history -----------------------------------------------------------

# `period` codes accepted by companyChartDataByStock. 6 and 7 silently alias
# to 2 upstream, so they are not offered.
PERIODS = {
    1: {"label": "Intraday", "points": "~300 trades"},
    2: {"label": "1 week", "points": "5 sessions"},
    3: {"label": "1 month", "points": "20 sessions"},
    4: {"label": "1 quarter", "points": "60 sessions"},
    5: {"label": "1 year", "points": "240 sessions"},
}


@app.get("/api/securities")
async def get_securities():
    """Every tradeable symbol, for the history picker's autocomplete."""
    return securities.catalogue(await cached_trade_summary())


@app.get("/api/stock/history")
async def stock_history(symbol: str, period: int = 5):
    """Price history for one security, by typed label rather than stockId.

    The chart endpoint only accepts a numeric `stockId`, so the symbol is
    resolved against the live security list first. The response names the
    security actually charted, plus any other share class the query could have
    meant -- charting `.X0000` when someone meant `.N0000` would be wrong and
    silent otherwise.
    """
    if period not in PERIODS:
        raise HTTPException(
            400, f"period must be one of {sorted(PERIODS)} (1=intraday … 5=year)"
        )

    match, alternatives = securities.resolve(await cached_trade_summary(), symbol)
    if match is None:
        raise HTTPException(404, f"no security matches {symbol!r}")

    stock_id = match["stockId"]
    try:
        data = await cache.get(
            f"chart:{stock_id}:{period}",
            TTL_CHART,
            lambda: client.stock_chart(stock_id, period),
        )
    except CSEError as exc:
        raise HTTPException(502, f"upstream unavailable: {exc}") from exc

    # `q` is share volume -- it matches tradeSummary.sharevolume on the latest
    # point. `s` is a row id, not a statistic, so it is deliberately dropped.
    points = sorted(
        (
            {"t": p.get("t"), "p": p.get("p"), "h": p.get("h"),
             "l": p.get("l"), "q": p.get("q")}
            for p in data
            if p.get("p") is not None and p.get("t") is not None
        ),
        key=lambda p: p["t"],
    )

    return {
        "symbol": match["symbol"],
        "name": match["name"],
        "stockId": stock_id,
        "period": period,
        "periodLabel": PERIODS[period]["label"],
        "points": points,
        "alternatives": alternatives,
    }


@app.websocket("/ws")
async def ws_endpoint(socket: WebSocket):
    await socket.accept()
    queue = relay.subscribe()
    try:
        # Replay what we already hold so a new tab paints immediately.
        await socket.send_json(
            {"feed": "_snapshot",
             "data": {"feeds": relay.latest, "connected": relay.connected}}
        )
        while True:
            message = await queue.get()
            await socket.send_json(message)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as exc:
        log.info("browser socket closed: %s", exc)
    finally:
        relay.unsubscribe(queue)


@app.get("/api/health")
async def health():
    return {"ok": True, "relayConnected": relay.connected,
            "marketOpen": market_is_open()}


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
