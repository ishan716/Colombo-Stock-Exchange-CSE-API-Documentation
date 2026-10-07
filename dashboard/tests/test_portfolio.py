"""Portfolio math, pinned to independently hand-computed figures.

Quantities and cost prices are the placeholder positions from
`holdings.sample.json`, not anyone's real book -- deliberately round, so every
expectation below can be checked by hand.

Prices are real quotes observed from `tradeSummary` while building this: AAIC
82.20, ACL 98.30, RCL 49.00, SEYB.X 68.80, SPEN 140.00.
"""
import pytest

from dashboard.server.portfolio import Holding, build, load_holdings

# Mirrors holdings.sample.json. Costs: 8000 + 5000 + 25000 + 14000 + 3750.
HOLDINGS = [
    {"symbol": "AAIC.N0000", "qty": 100, "avgPrice": 80.0, "besPrice": 80.90},
    {"symbol": "ACL.N0000", "qty": 50, "avgPrice": 100.0, "besPrice": 101.10},
    {"symbol": "RCL.N0000", "qty": 500, "avgPrice": 50.0, "besPrice": 50.55},
    {"symbol": "SEYB.X0000", "qty": 200, "avgPrice": 70.0, "besPrice": 70.80},
    {"symbol": "SPEN.N0000", "qty": 25, "avgPrice": 150.0, "besPrice": 151.65},
]

SNAPSHOT = [
    {"id": 118, "symbol": "AAIC.N0000", "name": "SOFTLOGIC LIFE INSURANCE PLC",
     "price": 82.2, "previousClose": 81.7, "high": 82.6, "low": 81.0},
    {"id": 472, "symbol": "ACL.N0000", "name": "ACL CABLES PLC",
     "price": 98.3, "previousClose": 95.9, "high": 98.9, "low": 96.0},
    {"id": 503, "symbol": "RCL.N0000", "name": "ROYAL CERAMICS LANKA PLC",
     "price": 49.0, "previousClose": 49.5, "high": 49.6, "low": 48.9},
    {"id": 213, "symbol": "SEYB.X0000", "name": "SEYLAN BANK PLC",
     "price": 68.8, "previousClose": 68.5, "high": 69.0, "low": 68.3},
    {"id": 343, "symbol": "SPEN.N0000", "name": "AITKEN SPENCE PLC",
     "price": 140.0, "previousClose": 140.5, "high": 141.0, "low": 139.5},
]


@pytest.fixture
def pf():
    return build(load_holdings(HOLDINGS), SNAPSHOT)


def test_cost_basis(pf):
    assert pf.total_cost == pytest.approx(55750.00, abs=0.01)


def test_market_value_and_pnl(pf):
    # 8220 + 4915 + 24500 + 13760 + 3500
    assert pf.total_value == pytest.approx(54895.00, abs=0.01)
    assert pf.total_pnl == pytest.approx(-855.00, abs=0.01)
    assert pf.total_pnl_pct == pytest.approx(-1.53, abs=0.01)


def test_day_change(pf):
    # 100*0.5 + 50*2.4 + 500*(-0.5) + 200*0.3 + 25*(-0.5)
    assert pf.total_day_change == pytest.approx(-32.50, abs=0.01)


def test_cost_weights_replace_broker_quantity_weights(pf):
    weights = {p.symbol: p.cost_weight for p in pf.positions}
    assert weights["AAIC.N0000"] == pytest.approx(14.35, abs=0.01)
    assert weights["ACL.N0000"] == pytest.approx(8.97, abs=0.01)
    assert weights["RCL.N0000"] == pytest.approx(44.84, abs=0.01)
    assert weights["SEYB.X0000"] == pytest.approx(25.11, abs=0.01)
    assert weights["SPEN.N0000"] == pytest.approx(6.73, abs=0.01)
    assert sum(weights.values()) == pytest.approx(100.0, abs=0.01)


def test_quantity_weight_overstates_the_cheapest_line(pf):
    """The broker's share-count weight is what this replaces.

    RCL is the low-priced, high-quantity line, so quantity weight flatters it:
    500/875 = 57.14% of shares against 44.84% of cost.
    """
    total_qty = sum(p.qty for p in pf.positions)
    rcl = next(p for p in pf.positions if p.symbol == "RCL.N0000")
    qty_weight = rcl.qty / total_qty * 100
    assert qty_weight == pytest.approx(57.14, abs=0.01)
    assert qty_weight > rcl.cost_weight


def test_value_weights_sum_to_100(pf):
    total = sum(p.value_weight for p in pf.positions)
    assert total == pytest.approx(100.0, abs=0.01)


def test_bes_pnl_is_worse_than_avg_pnl(pf):
    """B.E.S. includes fees, so it must always be the harsher measure."""
    for p in pf.positions:
        assert p.pnl_vs_bes < p.pnl


def test_position_detail(pf):
    spen = next(p for p in pf.positions if p.symbol == "SPEN.N0000")
    assert spen.market_value == pytest.approx(3500.00, abs=0.01)
    assert spen.pnl == pytest.approx(-250.00, abs=0.01)
    assert spen.pnl_pct == pytest.approx(-6.67, abs=0.01)
    assert spen.day_change == pytest.approx(-12.50, abs=0.01)
    assert spen.stock_id == 343


def test_unpriced_symbol_is_kept_not_dropped():
    holdings = HOLDINGS + [{"symbol": "NOPE.N0000", "qty": 10, "avgPrice": 5.0}]
    pf = build(load_holdings(holdings), SNAPSHOT)
    assert "NOPE.N0000" in pf.unpriced
    assert len(pf.positions) == 6
    ghost = next(p for p in pf.positions if p.symbol == "NOPE.N0000")
    assert ghost.priced is False
    assert ghost.market_value is None
    # Its cost still counts, so the total cannot silently drift.
    assert pf.total_cost == pytest.approx(55750.00 + 50.0, abs=0.01)


def test_bes_defaults_to_avg_price_when_absent():
    h = load_holdings([{"symbol": "X.N0000", "qty": 1, "avgPrice": 10.0}])
    assert h[0].bes_price == 10.0


def test_sector_exposure_groups_and_sums():
    pf = build(load_holdings(HOLDINGS), SNAPSHOT)
    by_name = {s["sector"]: s for s in pf.sector_exposure}
    assert "Banks" in by_name
    assert "Insurance" in by_name
    assert "Capital Goods" in by_name
    assert sum(s["weight"] for s in pf.sector_exposure) == pytest.approx(100.0, abs=0.01)
    # ACL, RCL and SPEN all sit in Capital Goods.
    assert len(by_name["Capital Goods"]["symbols"]) == 3


def test_empty_portfolio_does_not_divide_by_zero():
    pf = build([], SNAPSHOT)
    assert pf.total_cost == 0
    assert pf.total_pnl_pct == 0.0
    assert pf.sector_exposure == []


def test_zero_previous_close_does_not_crash():
    snap = [{"id": 1, "symbol": "A.N0000", "name": "A", "price": 10.0,
             "previousClose": 0}]
    pf = build([Holding("A.N0000", 5, 8.0, 8.1)], snap)
    assert pf.positions[0].day_change_pct == 0.0
