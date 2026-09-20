"""
Data sources:
  - get_most_active_stocks(): volume-based "activity" from Alpaca's screener
  - get_x_mentions(symbols): peer-interest proxy via X (Twitter) mention counts
  - get_latest_prices(symbols): current trade price, for price filtering
  - get_momentum(symbols): trailing price momentum, for momentum scoring
"""

import re
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import requests

import config

logger = logging.getLogger("stock_bot.data_sources")

TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")

# Common English words that look like tickers and cause false-positive matches
COMMON_WORD_BLOCKLIST = {
    "A", "I", "THE", "FOR", "AND", "ARE", "YOU", "ALL", "NOT", "BUY", "SELL",
    "CEO", "IPO", "USA", "USD", "EPS", "ATH", "ETF", "PUT", "DD", "IMO",
    "TOS", "EOD", "YOLO", "FOMO", "IT", "IS", "TO", "OF", "ON", "IN", "AT",
    "OR", "BE", "SO", "DO", "GO", "UP", "US", "AM", "PM", "RIP", "LOL",
}


def get_most_active_stocks(limit: int = None) -> list[str]:
    """
    Returns a list of ticker symbols with the highest recent trading volume,
    via Alpaca's market-data screener endpoint.
    """
    limit = limit or config.CANDIDATE_POOL_SIZE
    url = f"{config.ALPACA_DATA_BASE_URL}/v1beta1/screener/stocks/most-actives"
    headers = {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    }
    params = {"top": limit, "by": "volume"}

    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    symbols = [row["symbol"] for row in data.get("most_actives", [])]
    logger.info("Fetched %d most-active symbols from Alpaca", len(symbols))
    return symbols


def get_latest_prices(symbols: list[str]) -> dict[str, float]:
    """
    Returns {symbol: latest_trade_price} via Alpaca's latest-trades endpoint.
    Symbols Alpaca has no recent trade for are simply omitted.
    """
    if not symbols:
        return {}

    url = f"{config.ALPACA_DATA_BASE_URL}/v2/stocks/trades/latest"
    headers = {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    }
    params = {"symbols": ",".join(symbols), "feed": config.ALPACA_DATA_FEED}

    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    trades = resp.json().get("trades", {})

    prices = {sym: row["p"] for sym, row in trades.items() if "p" in row}
    logger.info("Fetched latest prices for %d/%d symbols", len(prices), len(symbols))
    return prices


def get_momentum(symbols: list[str], lookback_days: int = None) -> dict[str, float]:
    """
    Returns {symbol: pct_change} — simple return from the earliest to the
    latest daily close over roughly the last `lookback_days` trading days,
    via Alpaca's daily bars endpoint. Positive = upward momentum. Symbols
    with fewer than 2 bars in range (e.g. newly listed) are omitted.
    """
    if not symbols:
        return {}

    lookback_days = lookback_days or config.MOMENTUM_LOOKBACK_DAYS
    end = date.today()
    start = end - timedelta(days=int(lookback_days * 1.6) + 5)  # pad for weekends/holidays

    url = f"{config.ALPACA_DATA_BASE_URL}/v2/stocks/bars"
    headers = {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    }
    params = {
        "symbols": ",".join(symbols),
        "timeframe": "1Day",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": lookback_days + 10,
        "adjustment": "split",
        "feed": config.ALPACA_DATA_FEED,
    }

    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    bars_by_symbol = resp.json().get("bars", {})

    momentum = {}
    for sym, bars in bars_by_symbol.items():
        if len(bars) < 2:
            continue
        first_close = bars[0]["c"]
        last_close = bars[-1]["c"]
        if first_close:
            momentum[sym] = (last_close - first_close) / first_close

    logger.info("Computed momentum for %d/%d symbols", len(momentum), len(symbols))
    return momentum


def _batch_symbols_for_query(symbols: list[str], max_query_len: int = 400) -> list[list[str]]:
    """Groups symbols into batches whose OR'd cashtag query stays under X's query length cap."""
    batches = []
    current = []
    current_len = 0
    for sym in symbols:
        term_len = len(f'"${sym}" OR ')
        if current and current_len + term_len > max_query_len:
            batches.append(current)
            current = []
            current_len = 0
        current.append(sym)
        current_len += term_len
    if current:
        batches.append(current)
    return batches


def get_x_mentions(symbols: list[str], lookback_hours: int = None) -> Counter:
    """
    Counts how many times each symbol is mentioned (as a $CASHTAG) in
    recent English-language posts on X, in the last X_LOOKBACK_HOURS hours.
    Uses X API v2's recent-search endpoint (7-day max lookback). Requires
    an X developer app — as of 2026 this endpoint has no free tier, it's
    pay-per-use, so X_BEARER_TOKEN must be on a billed developer account.

    Searches plain "$TICKER" text (not the dedicated cashtag $ operator,
    which is gated to higher access tiers) and re-extracts/validates
    tickers from the matched text with the same regex + blocklist used for
    Reddit, so a partial/incidental text match doesn't get counted as a
    real mention.
    """
    if not symbols:
        return Counter()

    lookback_hours = lookback_hours or config.X_LOOKBACK_HOURS
    start_time = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    url = f"{config.X_API_BASE_URL}/tweets/search/recent"
    headers = {"Authorization": f"Bearer {config.X_BEARER_TOKEN}"}
    mentions = Counter()

    for batch in _batch_symbols_for_query(symbols):
        cashtags = " OR ".join(f'"${sym}"' for sym in batch)
        query = f"({cashtags}) -is:retweet lang:en"
        params = {
            "query": query,
            "max_results": config.X_MAX_RESULTS_PER_QUERY,
            "start_time": start_time,
            "tweet.fields": "text",
        }

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            tweets = resp.json().get("data", [])
        except Exception as exc:
            logger.warning("X search failed for batch %s: %s", batch, exc)
            continue

        symbol_set = set(batch)
        for tweet in tweets:
            text = tweet.get("text", "").upper()
            found = {t for t in TICKER_RE.findall(text) if t in symbol_set}
            found -= COMMON_WORD_BLOCKLIST
            for ticker in found:
                mentions[ticker] += 1

    logger.info("X mention counts: %s", dict(mentions.most_common(15)))
    return mentions
