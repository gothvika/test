"""
Central configuration, loaded from environment variables (see .env.example).
Uses python-dotenv so a local .env file works for manual runs; in
production/cron, set real environment variables instead.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    val = os.environ.get(name)
    return int(val) if val else default


def _float(name: str, default: float) -> float:
    val = os.environ.get(name)
    return float(val) if val else default


# --- Alpaca ---
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = _bool("ALPACA_PAPER", True)
ALPACA_TRADING_BASE_URL = (
    "https://paper-api.alpaca.markets" if ALPACA_PAPER else "https://api.alpaca.markets"
)
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"

# --- Anthropic (Claude) ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

# --- Financial Modeling Prep (fundamentals data) ---
FMP_API_KEY = os.environ.get("FMP_API_KEY", "")

# --- Reddit (optional; only needed if data_sources.get_reddit_mentions is used) ---
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "stock_bot/1.0")
REDDIT_SUBREDDITS = [
    s.strip() for s in os.environ.get(
        "REDDIT_SUBREDDITS", "wallstreetbets,stocks,investing"
    ).split(",") if s.strip()
]
REDDIT_LOOKBACK_HOURS = _int("REDDIT_LOOKBACK_HOURS", 24)
REDDIT_POST_LIMIT = _int("REDDIT_POST_LIMIT", 200)

# --- Candidate pool / scoring ---
CANDIDATE_POOL_SIZE = _int("CANDIDATE_POOL_SIZE", 50)
SHORTLIST_SIZE = _int("SHORTLIST_SIZE", 15)
NUM_STOCKS = _int("NUM_STOCKS", 10)

WEIGHT_VOLUME = _float("WEIGHT_VOLUME", 0.3)
WEIGHT_REDDIT = _float("WEIGHT_REDDIT", 0.2)
WEIGHT_AI_RESEARCH = _float("WEIGHT_AI_RESEARCH", 0.5)

# --- Trading ---
DOLLARS_PER_STOCK = _float("DOLLARS_PER_STOCK", 1.0)

# --- State / logging ---
STATE_FILE = os.environ.get("STATE_FILE", "last_run.json")
LOG_FILE = os.environ.get("LOG_FILE", "stock_bot.log")
