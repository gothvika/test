"""
Places notional (dollar-amount) market buy orders on Alpaca, and manages
basic downside/upside risk on existing positions (stop-loss, optional
take-profit).
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


def _optional_float(row: dict, key: str):
    val = row.get(key)
    return float(val) if val is not None else None


def get_positions() -> list[dict]:
    """
    Returns currently held Alpaca positions:
    [{"symbol": ..., "qty": ..., "avg_entry_price": ..., "unrealized_plpc": ...,
      "current_price": ..., "market_value": ..., "unrealized_pl": ...,
      "cost_basis": ...}]
    unrealized_plpc is Alpaca's own fractional unrealized P/L, e.g. -0.15
    means the position is down 15% from its average entry price.
    The current_price/market_value/unrealized_pl/cost_basis fields are
    None if Alpaca's response doesn't include them (kept optional rather
    than required so this stays backward compatible with the fields
    apply_stop_loss_and_take_profit() actually needs).
    """
    url = f"{config.ALPACA_TRADING_BASE_URL}/v2/positions"
    headers = {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    rows = resp.json()
    return [
        {
            "symbol": row["symbol"],
            "qty": float(row["qty"]),
            "avg_entry_price": float(row["avg_entry_price"]),
            "unrealized_plpc": float(row["unrealized_plpc"]),
            "current_price": _optional_float(row, "current_price"),
            "market_value": _optional_float(row, "market_value"),
            "unrealized_pl": _optional_float(row, "unrealized_pl"),
            "cost_basis": _optional_float(row, "cost_basis"),
        }
        for row in rows
    ]


def get_account() -> dict:
    """
    Returns an account-level snapshot from Alpaca:
    {"cash": ..., "portfolio_value": ..., "equity": ..., "buying_power": ...}
    """
    url = f"{config.ALPACA_TRADING_BASE_URL}/v2/account"
    headers = {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    row = resp.json()
    return {
        "cash": float(row["cash"]),
        "portfolio_value": float(row["portfolio_value"]),
        "equity": float(row["equity"]),
        "buying_power": float(row["buying_power"]),
    }


def close_position(symbol: str) -> dict:
    """Market-sells the entire position in `symbol`. Returns the order response JSON."""
    url = f"{config.ALPACA_TRADING_BASE_URL}/v2/positions/{symbol}"
    headers = {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    }
    resp = requests.delete(url, headers=headers, timeout=15)
    if resp.status_code >= 400:
        logger.error("Close position failed for %s: %s — %s", symbol, resp.status_code, resp.text)
        resp.raise_for_status()
    order = resp.json()
    logger.info("Position closed: %s -> order id %s", symbol, order.get("id"))
    return order


def apply_stop_loss_and_take_profit() -> dict:
    """
    Checks every current position against config.STOP_LOSS_PCT (always
    active — this bot previously had no sell logic at all, so a losing
    pick would just sit there indefinitely) and config.TAKE_PROFIT_PCT
    (only if set to a non-zero value; 0 means "let winners ride").
    Closes any position that's crossed either threshold.

    Returns {symbol: {"action": "sold_stop_loss"|"sold_take_profit"|
    "failed_...", "unrealized_plpc": float, ...}} for whatever was acted
    on. Never raises — a failed position fetch or a single failed close is
    logged and skipped so it can't block the rest of the daily run.
    """
    results = {}
    try:
        positions = get_positions()
    except Exception:
        logger.exception("Failed to fetch positions — skipping stop-loss/take-profit check.")
        return results

    for pos in positions:
        symbol = pos["symbol"]
        plpc = pos["unrealized_plpc"]

        reason = None
        if plpc <= config.STOP_LOSS_PCT:
            reason = "stop_loss"
        elif config.TAKE_PROFIT_PCT and plpc >= config.TAKE_PROFIT_PCT:
            reason = "take_profit"
        if reason is None:
            continue

        try:
            order = close_position(symbol)
            results[symbol] = {
                "action": f"sold_{reason}",
                "unrealized_plpc": plpc,
                "order_id": order.get("id"),
            }
            logger.info(
                "%s triggered for %s (unrealized_plpc=%.1f%%) — sold.",
                reason, symbol, plpc * 100,
            )
        except Exception as exc:
            logger.exception("Failed to close %s on %s trigger", symbol, reason)
            results[symbol] = {"action": f"failed_{reason}", "error": str(exc)}

    return results
