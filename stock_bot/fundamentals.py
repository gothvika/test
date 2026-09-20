"""
Company fundamentals — market cap, P/E, sector, CEO name, and a short
business description, via the Financial Modeling Prep free API.

Docs: https://site.financialmodelingprep.com/developer/docs
"""

from __future__ import annotations  # `float | None` syntax needs this on Python < 3.10

import logging
import requests
import config

logger = logging.getLogger("stock_bot.fundamentals")


def get_roe(symbol: str) -> float | None:
    """
    Returns trailing-twelve-month return on equity (as a decimal, e.g. 0.25
    for 25%) from FMP's ratios-ttm endpoint, or None if unavailable.
    """
    url = f"{config.FMP_BASE_URL}/ratios-ttm/{symbol}"
    params = {"apikey": config.FMP_API_KEY}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("ROE lookup failed for %s: %s", symbol, exc)
        return None

    if not data:
        return None

    return data[0].get("returnOnEquityTTM")


def get_company_profile(symbol: str) -> dict | None:
    """
    Returns a dict with keys: name, ceo, sector, industry, market_cap,
    price, pe_ratio, roe, description, website — or None if the lookup fails.
    """
    url = f"{config.FMP_BASE_URL}/profile/{symbol}"
    params = {"apikey": config.FMP_API_KEY}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Fundamentals lookup failed for %s: %s", symbol, exc)
        return None

    if not data:
        logger.warning("No fundamentals data returned for %s", symbol)
        return None

    row = data[0]
    return {
        "symbol": symbol,
        "name": row.get("companyName"),
        "ceo": row.get("ceo"),
        "sector": row.get("sector"),
        "industry": row.get("industry"),
        "market_cap": row.get("mktCap"),
        "price": row.get("price"),
        "pe_ratio": row.get("pe"),
        "roe": get_roe(symbol),
        "description": row.get("description"),
        "website": row.get("website"),
    }


def get_profiles(symbols: list[str]) -> dict[str, dict]:
    """Fetches profiles for a list of symbols, skipping any that fail."""
    profiles = {}
    for sym in symbols:
        profile = get_company_profile(sym)
        if profile:
            profiles[sym] = profile
    return profiles
