"""
Places market buy orders via Trading212's Public API (beta).

Trading212 orders are share-quantity based, not dollar-based like Alpaca's
notional orders — buy_dollar_amount() converts a target dollar amount into
a share quantity using Alpaca's live price data, then submits a market
order for that quantity. Alpaca stays wired in purely as a market-data
source (prices, screener, momentum, market-hours clock); Trading212's
public API has no confirmed screener or historical-bars equivalent, so it
handles order execution only.

Docs: https://docs.trading212.com/api (site is not fetchable from the dev
environment this was built in; auth, instrument lookup, and order
placement have since been verified against the live demo API).
"""

import base64
import json
import logging
import math
import os
import re
import time

import requests

import config
from data_sources import get_latest_prices

logger = logging.getLogger("stock_bot.trader")

_instrument_cache = None
_INSTRUMENTS_CACHE_FILE = os.path.join(os.path.dirname(__file__), "instruments_cache.json")
_INSTRUMENTS_CACHE_MAX_AGE = 24 * 60 * 60  # 1 day — instrument lists change rarely


def _auth_header() -> dict:
    credentials = f"{config.TRADING212_API_KEY}:{config.TRADING212_API_SECRET}".encode()
    return {"Authorization": f"Basic {base64.b64encode(credentials).decode()}"}


def _fetch_raw_instruments() -> list[dict]:
    """Fetches the full raw instrument list from Trading212 (~17k entries)."""
    url = f"{config.TRADING212_BASE_URL}/api/v0/equity/metadata/instruments"
    resp = requests.get(url, headers=_auth_header(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def _get_raw_instruments() -> list[dict]:
    """
    Returns the raw instrument list, cached on disk for a day. The list is
    large (~17k entries) and changes rarely, so re-fetching it on every
    order (or every test run) wastes Trading212's rate limit for no
    benefit.
    """
    if os.path.exists(_INSTRUMENTS_CACHE_FILE):
        age = time.time() - os.path.getmtime(_INSTRUMENTS_CACHE_FILE)
        if age < _INSTRUMENTS_CACHE_MAX_AGE:
            with open(_INSTRUMENTS_CACHE_FILE) as f:
                return json.load(f)

    instruments = _fetch_raw_instruments()
    with open(_INSTRUMENTS_CACHE_FILE, "w") as f:
        json.dump(instruments, f)
    return instruments


def _get_ticker_map() -> dict[str, str]:
    """
    Returns {bare_symbol: trading212_ticker}, e.g. {"SOFI": "IPOE_US_EQ"}.
    Cached in-process for the life of the run on top of the on-disk cache.

    Keyed by Trading212's `shortName` field, NOT parsed from `ticker` —
    `ticker` codes are sometimes legacy identifiers unrelated to the
    current trading symbol (confirmed live: SoFi Technologies' ticker is
    "IPOE_US_EQ", left over from its pre-merger SPAC ticker; `shortName`
    "SOFI" is the actual current symbol). Restricted to type=="STOCK" and
    currencyCode=="USD" to skip leveraged/inverse ETF look-alikes (e.g.
    "AAPY"/"TSLI" options-income ETFs riding on Apple/Tesla's name) and
    non-US listings of the same company.
    """
    global _instrument_cache
    if _instrument_cache is not None:
        return _instrument_cache

    instruments = _get_raw_instruments()

    ticker_map = {}
    for row in instruments:
        if row.get("type") != "STOCK" or row.get("currencyCode") != "USD":
            continue
        short_name = row.get("shortName", "")
        ticker = row.get("ticker", "")
        if short_name and ticker:
            ticker_map.setdefault(short_name, ticker)

    _instrument_cache = ticker_map
    logger.info("Cached %d Trading212 instrument tickers", len(ticker_map))
    return ticker_map


_MIN_QUANTITY_RE = re.compile(r"must trade at least ([\d.]+)")
_PRECISION_RE = re.compile(r"invalid quantity precision (\d+)")
_MAX_ORDER_ATTEMPTS = 4


def _post_market_order(ticker: str, quantity: float) -> requests.Response:
    url = f"{config.TRADING212_BASE_URL}/api/v0/equity/orders/market"
    headers = {**_auth_header(), "Content-Type": "application/json"}
    payload = {"ticker": ticker, "quantity": quantity, "extendedHours": True}
    return requests.post(url, headers=headers, json=payload, timeout=15)


def _round_up(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    return math.ceil(value * factor) / factor


def buy_dollar_amount(symbol: str, dollars: float) -> dict:
    """
    Submits a market buy order for approximately `dollars` worth of
    `symbol` — converted to a share quantity via Alpaca's latest price,
    since Trading212 orders are quantity-based. Returns the order
    response JSON. Raises if the symbol has no Trading212 instrument
    mapping, no price is available, or the order request fails.

    Trading212's market-order endpoint is documented as NOT idempotent in
    beta, so this never blindly retries an ambiguous failure (timeout,
    5xx) — that could duplicate an order that actually went through. The
    exception: Trading212 enforces two per-instrument constraints not
    published anywhere in advance — a minimum share quantity (confirmed
    live: SOFI needs >=~0.079 shares, ~$1.34 at ~$17/share, well above a
    $1.00 DCA buy) and a maximum quantity decimal precision (confirmed
    live: SOFI allows only 3 decimals). Both come back as a clean 400,
    confirmed pre-execution, so retrying with a corrected quantity is
    safe. Since fixing one constraint can trigger the other (observed
    live: bumping quantity to the minimum produced 5 decimals, which then
    violated precision), this retries a bounded number of times, always
    rounding the quantity UP so a precision fix can never drop back below
    a minimum already satisfied.
    """
    ticker_map = _get_ticker_map()
    ticker = ticker_map.get(symbol)
    if ticker is None:
        raise ValueError(f"No Trading212 instrument found for symbol {symbol!r}")

    prices = get_latest_prices([symbol])
    price = prices.get(symbol)
    if not price:
        raise ValueError(f"Could not fetch a live price for {symbol} to size the order")

    quantity = round(dollars / price, 5)  # Trading212 supports fractional shares
    resp = None

    for attempt in range(_MAX_ORDER_ATTEMPTS):
        resp = _post_market_order(ticker, quantity)
        if resp.status_code < 400:
            break

        if resp.status_code != 400:
            break  # not a validation error we know how to correct

        try:
            body = resp.json()
        except ValueError:
            body = {}
        error_type = body.get("type", "")
        detail = body.get("detail", "")

        if error_type == "/api-errors/min-quantity-exceeded":
            match = _MIN_QUANTITY_RE.search(detail)
            if not match:
                break
            new_quantity = round(float(match.group(1)) * 1.0005, 5)  # tiny margin over the floor
            logger.warning(
                "%s: %.5f shares is below Trading212's minimum — retrying at %.5f shares "
                "(attempt %d/%d, confirmed pre-execution rejection).",
                symbol, quantity, new_quantity, attempt + 1, _MAX_ORDER_ATTEMPTS,
            )
            quantity = new_quantity
            continue

        if error_type == "/api-errors/quantity-precision-mismatch":
            match = _PRECISION_RE.search(detail)
            if not match:
                break
            decimals = int(match.group(1))
            new_quantity = _round_up(quantity, decimals)
            logger.warning(
                "%s: quantity %.5f exceeds max precision (%d decimals) — retrying at %s "
                "(attempt %d/%d, confirmed pre-execution rejection).",
                symbol, quantity, decimals, new_quantity, attempt + 1, _MAX_ORDER_ATTEMPTS,
            )
            quantity = new_quantity
            continue

        break  # some other validation error — not ours to correct

    if resp.status_code >= 400:
        logger.error("Order failed for %s: %s — %s", symbol, resp.status_code, resp.text)
        resp.raise_for_status()

    order = resp.json()
    logger.info(
        "Order submitted: %s $%.2f (%.5f shares of %s) -> order id %s",
        symbol, quantity * price, quantity, ticker, order.get("id"),
    )
    return order


def check_market_open() -> bool:
    """
    Checks whether the market is currently open, via Alpaca's clock
    endpoint. Informational only — Trading212 has no confirmed
    equivalent, and this never places an order, so keeping it on Alpaca
    is fine regardless of which broker executes trades.
    """
    url = f"{config.ALPACA_TRADING_BASE_URL}/v2/clock"
    headers = {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return bool(resp.json().get("is_open"))
