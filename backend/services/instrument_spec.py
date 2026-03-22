# backend/services/instrument_spec.py
"""Instrument-level specifications shared across the trading system."""


def contract_size(symbol: str) -> float:
    """Return standard lot contract size for a symbol.

    XAUUSD/XAGUSD: 100 oz per lot (not 100,000 — gold is priced per oz)
    Indices (US30, NAS, SPX, DAX, FTSE, CAC): 1 unit per lot
    Crude oil (OIL, BRENT, WTI): 1,000 barrels per lot
    Forex (all others): 100,000 units per lot
    """
    sym = symbol.upper()
    if any(m in sym for m in ("XAU", "XAG")):
        return 100        # Gold/Silver: 100 troy oz per standard lot
    if any(m in sym for m in ("XPT", "XPD")):
        return 50         # Platinum/Palladium: 50 oz
    if any(m in sym for m in ("US30", "NAS", "SPX", "DAX", "FTSE", "CAC", "NDX", "UK100", "JP225")):
        return 1          # Index CFDs: 1 unit (broker-dependent, 1 is safest default)
    if any(m in sym for m in ("OIL", "BRENT", "WTI", "USOIL", "UKOIL")):
        return 1_000      # Crude oil: 1,000 barrels per standard lot
    return 100_000        # Standard forex: 100,000 units per lot
