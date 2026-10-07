"""Upstream CSE REST client.

CSE rejects cross-origin browsers: a request carrying any `Origin` other than
`https://www.cse.lk` gets a 403, and the preflight returns no
`Access-Control-Allow-Origin`. So every call here sets the site's own origin, and
the browser never talks to cse.lk directly -- it only ever talks to this server.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger(__name__)

BASE = "https://www.cse.lk/api"

# Without these exact headers the upstream returns 403.
HEADERS = {
    "Origin": "https://www.cse.lk",
    "Referer": "https://www.cse.lk/",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}


class CSEError(RuntimeError):
    """Upstream call failed after retries."""


class CSEClient:
    def __init__(self, timeout: float = 20.0) -> None:
        self._client = httpx.AsyncClient(
            headers=HEADERS,
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=10),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def post(self, path: str, data: dict | None = None, attempts: int = 3):
        """POST to an API path, retrying with backoff. Returns decoded JSON."""
        last: Exception | None = None
        for i in range(attempts):
            try:
                r = await self._client.post(f"{BASE}/{path}", data=data or {})
                r.raise_for_status()
                return r.json()
            except Exception as exc:  # network, HTTP status, or JSON decode
                last = exc
                if i < attempts - 1:
                    await asyncio.sleep(0.5 * 2**i)
        log.warning("CSE %s failed after %d attempts: %s", path, attempts, last)
        raise CSEError(f"{path}: {last}") from last

    # --- endpoint wrappers -------------------------------------------------

    async def trade_summary(self) -> list[dict]:
        """All 291 securities with live price and previousClose.

        This is the only full-market price source. `todaySharePrice` returns
        just 10 rows, so it cannot price an arbitrary portfolio.
        """
        return (await self.post("tradeSummary"))["reqTradeSummery"]

    async def all_sectors(self) -> list[dict]:
        return await self.post("allSectors")

    async def market_status(self) -> dict:
        return await self.post("marketStatus")

    async def market_summary(self) -> dict:
        return await self.post("marketSummery")

    async def aspi(self) -> dict:
        return await self.post("aspiData")

    async def snp(self) -> dict:
        return await self.post("snpData")

    async def top_gainers(self) -> list[dict]:
        return await self.post("topGainers")

    async def top_losers(self) -> list[dict]:
        return await self.post("topLooses")

    async def most_active(self) -> list[dict]:
        return await self.post("mostActiveTrades")

    async def stock_chart(self, stock_id: int, period: int = 3) -> list[dict]:
        """Per-stock OHLC series. stockId is `id` from tradeSummary.

        This endpoint wraps its series in a {"chartData": [...]} envelope,
        unlike `chartData` which returns a bare list.
        """
        body = await self.post(
            "companyChartDataByStock", {"stockId": stock_id, "period": period}
        )
        if isinstance(body, dict):
            return body.get("chartData") or []
        return body or []

    async def index_chart(self, chart_id: int, period: int = 3) -> list[dict]:
        """Index/sector series. chartId is sectorId (1=ASPI, 40=S&P SL20)."""
        return await self.post("chartData", {"chartId": chart_id, "period": period})
