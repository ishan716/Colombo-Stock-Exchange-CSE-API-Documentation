"""Symbol resolution for the price-history lookup.

The case that matters most is the voting/non-voting split: SEYB.N0000 and
SEYB.X0000 are different securities at different prices, so a bare "SEYB" must
resolve predictably and say what else it could have meant.
"""
from dashboard.server import securities

ROWS = [
    {"id": 118, "symbol": "AAIC.N0000", "name": "SOFTLOGIC LIFE INSURANCE PLC"},
    {"id": 410, "symbol": "LOLC.N0000", "name": "LOLC HOLDINGS PLC"},
    {"id": 200, "symbol": "SEYB.N0000", "name": "SEYLAN BANK PLC"},
    {"id": 201, "symbol": "SEYB.X0000", "name": "SEYLAN BANK PLC"},
    {"id": 378, "symbol": "CLND.N0000", "name": "COLOMBO LAND PLC"},
]


def test_exact_symbol_wins():
    match, alts = securities.resolve(ROWS, "SEYB.X0000")
    assert match["stockId"] == 201
    assert [a["symbol"] for a in alts] == ["SEYB.N0000"]


def test_bare_ticker_prefers_the_voting_line():
    """Someone typing "SEYB" means the ordinary share, not the non-voting one."""
    match, alts = securities.resolve(ROWS, "SEYB")
    assert match["symbol"] == "SEYB.N0000"
    assert [a["symbol"] for a in alts] == ["SEYB.X0000"]


def test_case_and_whitespace_are_forgiven():
    assert securities.resolve(ROWS, "  lolc.n0000 ")[0]["stockId"] == 410
    assert securities.resolve(ROWS, "lolc")[0]["stockId"] == 410


def test_company_name_search():
    match, _ = securities.resolve(ROWS, "softlogic")
    assert match["symbol"] == "AAIC.N0000"


def test_unknown_symbol_resolves_to_nothing():
    assert securities.resolve(ROWS, "NOPE.N0000") == (None, [])
    assert securities.resolve(ROWS, "") == (None, [])


def test_single_line_has_no_alternatives():
    match, alts = securities.resolve(ROWS, "CLND")
    assert match["stockId"] == 378
    assert alts == []


def test_catalogue_is_sorted_and_skips_incomplete_rows():
    rows = ROWS + [{"symbol": "BAD.N0000"}, {"id": 9, "name": "no symbol"}]
    cat = securities.catalogue(rows)
    assert [c["symbol"] for c in cat] == sorted(c["symbol"] for c in cat)
    assert all(c["stockId"] is not None for c in cat)
    assert "BAD.N0000" not in [c["symbol"] for c in cat]


def test_base_ticker():
    assert securities.base_ticker("SEYB.X0000") == "SEYB"
    assert securities.base_ticker(" seyb ") == "SEYB"
