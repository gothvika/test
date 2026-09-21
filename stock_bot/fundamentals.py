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


def _first_row(data) -> dict | None:
    """FMP's /stable/ endpoints return a bare object for some calls and a
    single-item list for others depending on the endpoint; handle both."""
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data or None
    return None


def get_roe(symbol: str) -> float | None:
    """
    Returns return on equity (net income / total stockholders' equity, most
    recent annual period) as a decimal, e.g. 0.25 for 25%.

    Computed from raw income-statement + balance-sheet-statement data
    rather than FMP's ratios-ttm endpoint, which returned 402 Payment
    Required on a free-tier key (that endpoint needs a paid plan). These
    are basic fundamentals rather than a "ratios"/TTM product, so they're
    more likely to be free tier — but this hasn't been confirmed against
    the live API from this environment (financialmodelingprep.com is
    network-blocked here), so it needs a real test.

    Returns None if either statement is unavailable, or if equity is zero
    or negative (ROE isn't meaningful there — e.g. a company with a
    stockholders' deficit from heavy buybacks/losses).
    """
    params = {"symbol": symbol, "period": "annual", "limit": 1, "apikey": config.FMP_API_KEY}

    try:
        income_resp = requests.get(f"{config.FMP_BASE_URL}/income-statement", params=params, timeout=15)
        income_resp.raise_for_status()
        income_row = _first_row(income_resp.json())

        balance_resp = requests.get(f"{config.FMP_BASE_URL}/balance-sheet-statement", params=params, timeout=15)
        balance_resp.raise_for_status()
        balance_row = _first_row(balance_resp.json())
    except Exception as exc:
        logger.warning("ROE lookup failed for %s: %s", symbol, exc)
        return None

    if not income_row or not balance_row:
        return None

    net_income = income_row.get("netIncome")
    equity = balance_row.get("totalStockholdersEquity")
    if net_income is None or equity is None or equity <= 0:
        return None

    return net_income / equity


def get_company_profile(symbol: str) -> dict | None:
    """
    Returns a dict with keys: name, ceo, sector, industry, market_cap,
    price, pe_ratio, roe, is_etf, is_fund, is_actively_trading,
    description, website — or None if the lookup fails.
    """
    url = f"{config.FMP_BASE_URL}/profile"
    params = {"symbol": symbol, "apikey": config.FMP_API_KEY}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        row = _first_row(resp.json())
    except Exception as exc:
        logger.warning("Fundamentals lookup failed for %s: %s", symbol, exc)
        return None

    if not row:
        logger.warning("No fundamentals data returned for %s", symbol)
        return None

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
        # Used to hard-exclude leveraged/inverse single-stock ETFs and
        # similar look-alike products before spending an AI research call
        # on something that was never a real operating company (e.g.
        # "NVD"/"CONL" — leveraged ETFs riding a real ticker's name).
        "is_etf": bool(row.get("isEtf")),
        "is_fund": bool(row.get("isFund")),
        "is_actively_trading": row.get("isActivelyTrading", True),
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
