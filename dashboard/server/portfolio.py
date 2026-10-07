"""Portfolio valuation. Pure functions over holdings + a tradeSummary snapshot.

Two deliberate departures from the broker's own portfolio screen:

1. The broker's "Holding % (Quantity)" is share-count weight (qty / total shares).
   That is close to meaningless for allocation: in the sample book RCL shows
   57.14% there while being 44.84% of cost. We compute cost weight and
   market-value weight instead.

2. Profit is shown against the B.E.S. (break-even sale) price as well as the
   average price. B.E.S. includes round-trip fees, so it is the price you
   actually have to clear to not lose money.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import sectors


@dataclass
class Holding:
    symbol: str
    qty: int
    avg_price: float
    bes_price: float

    @property
    def cost(self) -> float:
        return self.qty * self.avg_price


@dataclass
class Position:
    symbol: str
    name: str
    qty: int
    avg_price: float
    bes_price: float
    cost: float
    sector: str
    sector_id: int | None
    stock_id: int | None = None
    last_price: float | None = None
    previous_close: float | None = None
    market_value: float | None = None
    pnl: float | None = None
    pnl_pct: float | None = None
    pnl_vs_bes: float | None = None
    pnl_vs_bes_pct: float | None = None
    day_change: float | None = None
    day_change_pct: float | None = None
    cost_weight: float | None = None
    value_weight: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    priced: bool = False


@dataclass
class Portfolio:
    positions: list[Position] = field(default_factory=list)
    total_cost: float = 0.0
    total_value: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    total_day_change: float = 0.0
    total_day_change_pct: float = 0.0
    unpriced: list[str] = field(default_factory=list)
    sector_exposure: list[dict] = field(default_factory=list)


def load_holdings(raw: list[dict]) -> list[Holding]:
    out = []
    for h in raw:
        out.append(
            Holding(
                symbol=str(h["symbol"]).strip().upper(),
                qty=int(h["qty"]),
                avg_price=float(h["avgPrice"]),
                # B.E.S. is optional; fall back to avg price when absent.
                bes_price=float(h.get("besPrice") or h["avgPrice"]),
            )
        )
    return out


def build(holdings: list[Holding], trade_summary: list[dict]) -> Portfolio:
    """Value `holdings` against a tradeSummary snapshot.

    A symbol missing from the snapshot is kept in the table as unpriced rather
    than dropped -- silently omitting a position would misstate the total.
    """
    by_symbol = {r["symbol"]: r for r in trade_summary}
    pf = Portfolio()

    for h in holdings:
        row = by_symbol.get(h.symbol)
        sector_id, sector_name = sectors.lookup(h.symbol)
        pos = Position(
            symbol=h.symbol,
            name=(row or {}).get("name") or h.symbol,
            qty=h.qty,
            avg_price=h.avg_price,
            bes_price=h.bes_price,
            cost=h.cost,
            sector=sector_name,
            sector_id=sector_id,
        )
        pf.total_cost += h.cost

        if row is None or row.get("price") in (None, 0):
            pf.unpriced.append(h.symbol)
            pf.positions.append(pos)
            continue

        last = float(row["price"])
        prev = float(row.get("previousClose") or last)
        pos.stock_id = row.get("id")
        pos.last_price = last
        pos.previous_close = prev
        pos.day_high = row.get("high")
        pos.day_low = row.get("low")
        pos.market_value = h.qty * last
        pos.pnl = pos.market_value - h.cost
        pos.pnl_pct = (pos.pnl / h.cost * 100) if h.cost else 0.0
        bes_cost = h.qty * h.bes_price
        pos.pnl_vs_bes = pos.market_value - bes_cost
        pos.pnl_vs_bes_pct = (pos.pnl_vs_bes / bes_cost * 100) if bes_cost else 0.0
        pos.day_change = h.qty * (last - prev)
        pos.day_change_pct = ((last - prev) / prev * 100) if prev else 0.0
        pos.priced = True

        pf.total_value += pos.market_value
        pf.total_day_change += pos.day_change
        pf.positions.append(pos)

    # Weights are computed after the totals are known.
    for pos in pf.positions:
        pos.cost_weight = (pos.cost / pf.total_cost * 100) if pf.total_cost else 0.0
        if pos.market_value is not None and pf.total_value:
            pos.value_weight = pos.market_value / pf.total_value * 100

    pf.total_pnl = pf.total_value - pf.total_cost
    pf.total_pnl_pct = (pf.total_pnl / pf.total_cost * 100) if pf.total_cost else 0.0
    prev_value = pf.total_value - pf.total_day_change
    pf.total_day_change_pct = (
        (pf.total_day_change / prev_value * 100) if prev_value else 0.0
    )
    pf.sector_exposure = _sector_exposure(pf)
    return pf


def _sector_exposure(pf: Portfolio) -> list[dict]:
    """Group market value by sector, largest first."""
    buckets: dict[str, dict] = {}
    for pos in pf.positions:
        if pos.market_value is None:
            continue
        b = buckets.setdefault(
            pos.sector,
            {"sector": pos.sector, "sectorId": pos.sector_id, "value": 0.0,
             "symbols": []},
        )
        b["value"] += pos.market_value
        b["symbols"].append(pos.symbol)
    for b in buckets.values():
        b["weight"] = (b["value"] / pf.total_value * 100) if pf.total_value else 0.0
    return sorted(buckets.values(), key=lambda b: -b["value"])
