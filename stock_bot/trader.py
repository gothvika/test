"""
Places notional (dollar-amount) market buy orders on Alpaca.
"""

import logging
import requests
import config

logger = logging.getLogger("stock_bot.trader")


def buy_dollar_amount(symbol: str, dollars: float) -> dict:
    """
    Submits a market buy order for a fixed dollar amount (fractional share).
    Returns the order response JSON. Raises on HTTP error.
    """
    url = f"{config.ALPACA_TRADING_BASE_URL}/v2/orders"
    headers = {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "symbol": symbol,
        "notional": f"{dollars:.2f}",
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    if resp.status_code >= 400:
        logger.error("Order failed for %s: %s — %s", symbol, resp.status_code, resp.text)
        resp.raise_for_status()

    order = resp.json()
    logger.info("Order submitted: %s $%.2f -> order id %s", symbol, dollars, order.get("id"))
    return order


def check_market_open() -> bool:
    """Checks whether the market is currently open via Alpaca's clock endpoint."""
    url = f"{config.ALPACA_TRADING_BASE_URL}/v2/clock"
    headers = {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return bool(resp.json().get("is_open"))
