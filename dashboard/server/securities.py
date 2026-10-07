"""Resolve a typed stock label to a security in the live market list.

The chart endpoint wants a numeric `stockId`, which is the `id` field from
`tradeSummary` -- *not* the `securityId` returned by `companyInfoSummery`. So
every lookup starts from a tradeSummary snapshot.

People do not type canonical symbols. They type `lolc`, `LOLC.N0000`, a stray
space, or the company name. This module accepts all of those and reports which
security it settled on, so the UI can say so rather than silently charting the
wrong line -- an important distinction when a company has both a voting
(`.N0000`) and a non-voting (`.X0000`) line trading at different prices.
"""
from __future__ import annotations


def base_ticker(symbol: str) -> str:
    """`SEYB.X0000` -> `SEYB`. The part a person actually types."""
    return symbol.split(".")[0].strip().upper()


def catalogue(rows: list[dict]) -> list[dict]:
    """Trim a tradeSummary snapshot to what the picker needs, symbol-sorted."""
    out = [
        {"symbol": r["symbol"], "name": r.get("name") or r["symbol"],
         "stockId": r.get("id")}
        for r in rows
        if r.get("symbol") and r.get("id") is not None
    ]
    out.sort(key=lambda r: r["symbol"])
    return out


def _rank(row: dict) -> tuple:
    # Voting lines are what people mean when they type a bare ticker, so they
    # sort ahead of the non-voting line of the same company.
    return (0 if ".N" in row["symbol"].upper() else 1, row["symbol"])


def resolve(rows: list[dict], query: str) -> tuple[dict | None, list[dict]]:
    """Find the security a typed label refers to.

    Returns `(match, alternatives)`. `alternatives` holds the other plausible
    readings of the same query -- the other share class, or the rest of a name
    search -- so the caller can offer them instead of guessing silently.
    """
    catalog = catalogue(rows)
    q = (query or "").strip().upper()
    if not q:
        return None, []

    exact = [r for r in catalog if r["symbol"].upper() == q]
    if exact:
        siblings = [r for r in catalog
                    if base_ticker(r["symbol"]) == base_ticker(q)
                    and r["symbol"].upper() != q]
        return exact[0], sorted(siblings, key=_rank)

    by_ticker = sorted(
        (r for r in catalog if base_ticker(r["symbol"]) == base_ticker(q)),
        key=_rank,
    )
    if by_ticker:
        return by_ticker[0], by_ticker[1:]

    # Fall back to the company name, so "softlogic" finds AAIC.N0000.
    by_name = sorted(
        (r for r in catalog if q in r["name"].upper()),
        key=_rank,
    )
    if by_name:
        return by_name[0], by_name[1:]

    return None, []
