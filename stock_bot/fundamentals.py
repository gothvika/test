"""
PLACEHOLDER — you mentioned more files are coming; if you already have a
fundamentals.py, send it and I'll swap this out. Until then, this gives the
bot a working implementation so it runs end-to-end.

Pulls company profile data (name, sector, industry, market cap, P/E,
description) from Financial Modeling Prep's /profile endpoint, keyed by
symbol. Symbols FMP has no data for are simply omitted from the result,
matching how scorer.py expects to use it.
"""

import logging

import requests

import config

logger = logging.getLogger("stock_bot.fundamentals")

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"


def get_profiles(symbols: list[str]) -> dict[str, dict]:
    """
    Returns {symbol: {name, sector, industry, market_cap, pe_ratio,
    description}} for each symbol FMP has profile data for.
    """
    if not symbols:
        return {}

    url = f"{FMP_BASE_URL}/profile/{','.join(symbols)}"
    params = {"apikey": config.FMP_API_KEY}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        logger.warning("Failed to fetch fundamentals from FMP: %s", exc)
        return {}

    profiles = {}
    for row in rows or []:
        symbol = row.get("symbol")
        if not symbol:
            continue
        profiles[symbol] = {
            "symbol": symbol,
            "name": row.get("companyName"),
            "sector": row.get("sector"),
            "industry": row.get("industry"),
            "market_cap": row.get("mktCap"),
            "pe_ratio": row.get("pe"),
            "description": row.get("description"),
        }

    missing = set(symbols) - set(profiles)
    if missing:
        logger.warning("No FMP profile data for: %s", missing)

    logger.info("Fetched fundamentals for %d/%d symbols", len(profiles), len(symbols))
    return profiles
