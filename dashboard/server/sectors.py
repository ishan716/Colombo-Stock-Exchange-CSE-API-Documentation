"""Symbol -> sector mapping.

The CSE API exposes no sector for a security. `tradeSummary`,
`companyInfoSummery`, `allSecurityCode` and `cntSecurity` all lack the field, and
there is no sector-constituent endpoint. `/api/allSectors` gives the 22 sector
*indices* but never says which company sits in which -- so the mapping has to be
maintained by hand here.

These classifications are entered manually and have NOT been verified against an
authoritative CSE source; treat them as a best-effort starting point and correct
any that are wrong. Sector ids come from /api/allSectors.

Unmapped symbols fall through to "Unclassified" so the allocation charts still
render instead of dropping a position on the floor.
"""
from __future__ import annotations

SECTOR_NAMES: dict[int, str] = {
    223: "Energy",
    224: "Materials",
    225: "Capital Goods",
    226: "Commercial & Professional Services",
    227: "Transportation",
    228: "Automobiles & Components",
    229: "Consumer Durables & Apparel",
    230: "Consumer Services",
    232: "Retailing",
    233: "Food & Staples Retailing",
    234: "Food, Beverage & Tobacco",
    235: "Household & Personal Products",
    236: "Health Care Equipment & Services",
    238: "Banks",
    239: "Diversified Financials",
    240: "Insurance",
    241: "Software & Services",
    244: "Telecommunication Services",
    245: "Utilities",
    246: "Real Estate Management & Development",
}

# symbol -> sectorId
SYMBOL_SECTOR: dict[str, int] = {
    "AAIC.N0000": 240,  # Softlogic Life Insurance
    "ACL.N0000": 225,   # ACL Cables
    "RCL.N0000": 225,   # Royal Ceramics Lanka
    "SEYB.N0000": 238,  # Seylan Bank (voting)
    "SEYB.X0000": 238,  # Seylan Bank (non-voting)
    "SPEN.N0000": 225,  # Aitken Spence
}

UNCLASSIFIED = "Unclassified"


def lookup(symbol: str) -> tuple[int | None, str]:
    """Return (sectorId, sectorName) for a symbol."""
    sid = SYMBOL_SECTOR.get(symbol.upper())
    if sid is None:
        # Voting/non-voting lines of the same company share a sector, so try
        # the base ticker before giving up.
        base = symbol.split(".")[0].upper()
        for sym, mapped in SYMBOL_SECTOR.items():
            if sym.split(".")[0] == base:
                sid = mapped
                break
    if sid is None:
        return None, UNCLASSIFIED
    return sid, SECTOR_NAMES.get(sid, UNCLASSIFIED)
