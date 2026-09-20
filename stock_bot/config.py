"""
Configuration — reads all secrets from environment variables.
Never hardcode API keys in source files.

Required environment variables:
  ALPACA_API_KEY        - your Alpaca API key
  ALPACA_SECRET_KEY     - your Alpaca API secret
  ALPACA_PAPER          - "true" (default) or "false". KEEP THIS "true" until
                           you've watched the bot run correctly for a while.
  REDDIT_CLIENT_ID       - Reddit app client id (from reddit.com/prefs/apps)
  REDDIT_CLIENT_SECRET   - Reddit app secret
  REDDIT_USER_AGENT      - e.g. "stock-activity-bot/1.0 by u/yourname"
  ANTHROPIC_API_KEY      - Claude API key (console.anthropic.com) — used to
                            research each shortlisted company's CEO, recent
                            news, and future prospects via web search
  FMP_API_KEY             - Financial Modeling Prep API key (free tier at
                            financialmodelingprep.com) — used for company
                            fundamentals: market cap, P/E, sector, CEO name

Optional:
  DOLLARS_PER_STOCK      - default 1.00
  NUM_STOCKS             - default 10
  CANDIDATE_POOL_SIZE    - how many "most active" symbols to pull before
                            scoring, default 50
  SHORTLIST_SIZE          - how many candidates advance to deep AI research
                            (fundamentals + CEO + prospects), default 20.
                            Keep this modest — each one costs an API call.
  WEIGHT_VOLUME           - default 0.25
  WEIGHT_REDDIT           - default 0.20
  WEIGHT_AI_RESEARCH       - default 0.55 (covers value/fundamentals, CEO,
                            and future-prospects combined)
"""

import os

def _bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y")

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = _bool_env("ALPACA_PAPER", True)

ALPACA_TRADING_BASE_URL = (
    "https://paper-api.alpaca.markets" if ALPACA_PAPER else "https://api.alpaca.markets"
)
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "stock-activity-bot/1.0")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

FMP_API_KEY = os.getenv("FMP_API_KEY", "")
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"

DOLLARS_PER_STOCK = float(os.getenv("DOLLARS_PER_STOCK", "1.00"))
NUM_STOCKS = int(os.getenv("NUM_STOCKS", "10"))
CANDIDATE_POOL_SIZE = int(os.getenv("CANDIDATE_POOL_SIZE", "50"))
SHORTLIST_SIZE = int(os.getenv("SHORTLIST_SIZE", "20"))

WEIGHT_VOLUME = float(os.getenv("WEIGHT_VOLUME", "0.25"))
WEIGHT_REDDIT = float(os.getenv("WEIGHT_REDDIT", "0.20"))
WEIGHT_AI_RESEARCH = float(os.getenv("WEIGHT_AI_RESEARCH", "0.55"))

REDDIT_SUBREDDITS = ["wallstreetbets", "stocks", "investing"]
REDDIT_POST_LIMIT = 100          # posts scanned per subreddit
REDDIT_LOOKBACK_HOURS = 24

STATE_FILE = os.path.join(os.path.dirname(__file__), "last_run.json")
LOG_FILE = os.path.join(os.path.dirname(__file__), "bot.log")
