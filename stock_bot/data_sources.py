"""
Data sources:
  - get_most_active_stocks(): volume-based "activity" from Alpaca's screener
  - get_reddit_mentions(symbols): peer-interest proxy via Reddit mention counts
"""

import re
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

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


def get_reddit_mentions(symbols: list[str]) -> Counter:
    """
    Counts how many times each symbol is mentioned in recent posts (title +
    selftext) across the configured subreddits, in the last
    REDDIT_LOOKBACK_HOURS hours. Requires a Reddit "script" app (praw).
    """
    import praw  # imported here so the rest of the bot works without praw installed

    reddit = praw.Reddit(
        client_id=config.REDDIT_CLIENT_ID,
        client_secret=config.REDDIT_CLIENT_SECRET,
        user_agent=config.REDDIT_USER_AGENT,
    )

    symbol_set = set(symbols)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.REDDIT_LOOKBACK_HOURS)
    mentions = Counter()

    for sub_name in config.REDDIT_SUBREDDITS:
        try:
            subreddit = reddit.subreddit(sub_name)
            for post in subreddit.new(limit=config.REDDIT_POST_LIMIT):
                post_time = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
                if post_time < cutoff:
                    break  # 'new' is sorted newest-first; stop once too old

                text = f"{post.title} {post.selftext}".upper()
                found = {t for t in TICKER_RE.findall(text) if t in symbol_set}
                found -= COMMON_WORD_BLOCKLIST
                for ticker in found:
                    mentions[ticker] += 1
        except Exception as exc:
            logger.warning("Failed scanning r/%s: %s", sub_name, exc)

    logger.info("Reddit mention counts: %s", dict(mentions.most_common(15)))
    return mentions
