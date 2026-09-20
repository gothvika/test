"""
Places market buy orders via Trading212's Public API (beta).

Trading212 orders are share-quantity based, not dollar-based like Alpaca's
notional orders — buy_dollar_amount() converts a target dollar amount into
a share quantity using Alpaca's live price data, then submits a market
order for that quantity. Alpaca stays wired in purely as a market-data
source (prices, screener, momentum, market-hours clock); Trading212's
public API has no confirmed screener or historical-bars equivalent, so it
handles order execution only.

Docs: https://docs.trading212.com/api (site is not fetchable from this
dev environment — endpoints below were confirmed via a third-party SDK's
source and cross-referenced against independent docs mirrors, not
against a live call. Verify your first real order carefully.)
"""

import base64
import logging

import requests

import config
from data_sources import get_latest_prices

logger = logging.getLogger("stock_bot.trader")

_instrument_cache = None


def _auth_header() -> dict:
    credentials = f"{config.TRADING212_API_KEY}:{config.TRADING212_API_SECRET}".encode()
    return {"Authorization": f"Basic {base64.b64encode(credentials).decode()}"}


def _get_ticker_map() -> dict[str, str]:
    """
    Fetches and caches Trading212's full instrument list, returning
    {bare_symbol: trading212_ticker}, e.g. {"AAPL": "AAPL_US_EQ"}. Cached
    in-process for the life of the run — the full list is large and
    doesn't change intraday, so refetching per order would be wasteful
    and eat into Trading212's rate limit.
    """
    global _instrument_cache
    if _instrument_cache is not None:
        return _instrument_cache

    url = f"{config.TRADING212_BASE_URL}/api/v0/equity/metadata/instruments"
    resp = requests.get(url, headers=_auth_header(), timeout=15)
    resp.raise_for_status()
    instruments = resp.json()

    ticker_map = {}
    for row in instruments:
        ticker = row.get("ticker", "")
        bare_symbol = ticker.split("_")[0]
        if bare_symbol:
            ticker_map[bare_symbol] = ticker

    _instrument_cache = ticker_map
    logger.info("Cached %d Trading212 instrument tickers", len(ticker_map))
    return ticker_map


def buy_dollar_amount(symbol: str, dollars: float) -> dict:
    """
    Submits a market buy order for approximately `dollars` worth of
    `symbol` — converted to a share quantity via Alpaca's latest price,
    since Trading212 orders are quantity-based. Returns the order
    response JSON. Raises if the symbol has no Trading212 instrument
    mapping, no price is available, or the order request fails.

    Trading212's market-order endpoint is documented as NOT idempotent
    in beta — do not add automatic retries here, a retried request can
    duplicate the order.
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

    url = f"{config.TRADING212_BASE_URL}/api/v0/equity/orders/market"
    headers = {**_auth_header(), "Content-Type": "application/json"}
    payload = {"ticker": ticker, "quantity": quantity}

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    if resp.status_code >= 400:
        logger.error("Order failed for %s: %s — %s", symbol, resp.status_code, resp.text)
        resp.raise_for_status()

    order = resp.json()
    logger.info(
        "Order submitted: %s $%.2f (%.5f shares of %s) -> order id %s",
        symbol, dollars, quantity, ticker, order.get("id"),
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
