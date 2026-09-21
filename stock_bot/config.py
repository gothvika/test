"""
Configuration — reads all secrets from environment variables.
Never hardcode API keys in source files.

Required environment variables:
  ALPACA_API_KEY        - your Alpaca API key. Used both as the
                           market-data source (screener, prices, momentum,
                           market-hours clock) and to execute buy orders.
                           (Trading212 was evaluated as an alternate order
                           executor but its public API can't place orders
                           in a currency other than the account's primary
                           one — no USD orders on a GBP account — so this
                           stays on Alpaca.)
  ALPACA_SECRET_KEY     - your Alpaca API secret
  ALPACA_PAPER          - "true" (default) or "false". KEEP THIS "true"
                           until you've watched the bot run correctly —
                           "false" places real orders with real money.
  X_BEARER_TOKEN         - X (Twitter) API v2 app-only bearer token, from a
                            billed developer account (developer.x.com) — the
                            recent-search endpoint has no free tier as of 2026
  ANTHROPIC_API_KEY      - Claude API key (console.anthropic.com) — used to
                            research each shortlisted company's CEO, recent
                            news, and future prospects via web search
  ANTHROPIC_MODEL         - default "claude-haiku-4-5" (cost-optimized;
                            roughly half the per-call cost of Sonnet 5, at
                            some loss of research nuance on ambiguous
                            calls). Set to "claude-sonnet-5" for better
                            judgment on close cases at higher cost.
  FMP_API_KEY             - Financial Modeling Prep API key (free tier at
                            financialmodelingprep.com) — used for company
                            fundamentals: market cap, P/E, sector, CEO name

Optional:
  DOLLARS_PER_STOCK      - default 2.00
  NUM_STOCKS             - default 10
  CANDIDATE_POOL_SIZE    - how many "most active" symbols to pull before
                            scoring, default 50
  SHORTLIST_SIZE          - how many candidates advance to deep AI research
                            (fundamentals + CEO + prospects), default 12.
                            Keep this modest — each one costs an API call.
  MOVERS_POOL_SIZE        - how many of today's top % gainers (Alpaca's
                            movers screener, separate from most-actives) to
                            merge into the candidate pool, default 25. This
                            exists because the most-actives screener can
                            only ever surface names that are ALREADY
                            heavily traded — a stock having a strong move
                            without (yet) being top-volume would never
                            enter the pool otherwise. Set to 0 to disable.
  NEWS_ARTICLES_PER_SYMBOL - how many recent news articles (from FMP) to
                            fetch per shortlisted symbol and hand to the AI
                            research step as grounding context, default 4.
  ALPACA_DATA_FEED        - "iex" (default, free/paper accounts) or "sip"
                            (needs a paid market-data subscription)
  MAX_STOCK_PRICE         - only consider stocks trading below this price,
                            default 30.00
  MIN_STOCK_PRICE         - only consider stocks trading at or above this
                            price, default 2.00. Added after live testing
                            of the movers screener showed 8/10 "top
                            gainers" were sub-$1 penny stocks/warrants
                            with huge but illiquid-noise percentage swings
                            (e.g. +2967% on a $0.007 warrant) — exactly
                            the opposite of "grounded, proven" businesses.
  MOMENTUM_LOOKBACK_DAYS  - trading-day window used to compute price
                            momentum (% change), default 20 (~1 month)
  WEIGHT_VOLUME           - default 0.10. NOTE: lower volume scores
                            *better* — this prefers the least-active names
                            within the day's active pool over the most-active
                            (Alpaca's screener only exposes rank order, not
                            raw share counts, so this is relative, not an
                            absolute volume ceiling)
  X_LOOKBACK_HOURS        - how far back to search X mentions, default 24
  X_MAX_RESULTS_PER_QUERY - posts fetched per search batch (max 100 on the
                            recent-search endpoint), default 100
  WEIGHT_X                - default 0.15 — higher X mention count scores
                            better
  WEIGHT_MOMENTUM         - default 0.20 — higher trailing price momentum
                            scores better
  WEIGHT_ROE              - default 0.20 — higher return on equity (TTM,
                            from FMP) scores better
  WEIGHT_AI_RESEARCH       - default 0.35 (covers CEO reputation and
                            near-term prospects/valuation sanity check)
  MIN_AI_SCORE_THRESHOLD  - default 0.10. A stock whose AI research score
                            falls below this is excluded from the final
                            picks entirely, regardless of its other
                            scores — a hard veto rather than letting a
                            clear red flag (leveraged/inverse ETF, no
                            real business, fraud conviction, etc.) just
                            get diluted into the blend.

Hard exclusions (not configurable — see scorer.py):
  - Negative ROE (equity-destroying, not just weaker than peers).
  - Crypto-linked businesses (miners, exchanges, "digital asset treasury"
    vehicles) — matched by keyword against sector/industry/name/description,
    plus a small hand-maintained list of known crypto-adjacent tickers
    whose FMP profile text doesn't reliably self-describe as crypto (e.g.
    legacy company names). The strategy targets grounded, proven
    science/tech businesses with real income rather than speculative
    crypto exposure.

Risk management (sell side — this bot previously only ever bought):
  STOP_LOSS_PCT           - default -0.20 (sell a position once it's down
                            20% from average entry price). Always active.
  TAKE_PROFIT_PCT         - default 0 (disabled — "let winners ride").
                            Set e.g. to 0.40 to sell a position once it's
                            up 40% from average entry price.
"""

import os

from dotenv import load_dotenv

load_dotenv(override=True)  # .env always wins over a stale shell-exported var


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
# "iex" works on free/paper accounts; "sip" needs a paid market-data
# subscription and 403s otherwise.
ALPACA_DATA_FEED = os.getenv("ALPACA_DATA_FEED", "iex")

X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")
X_API_BASE_URL = "https://api.x.com/2"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")

FMP_API_KEY = os.getenv("FMP_API_KEY", "")
# FMP's old /api/v3/ endpoints are legacy-only (need a subscription predating
# Aug 2025) and 403 otherwise; /stable/ is the current, freely-accessible base.
FMP_BASE_URL = "https://financialmodelingprep.com/stable"

DOLLARS_PER_STOCK = float(os.getenv("DOLLARS_PER_STOCK", "2.00"))
NUM_STOCKS = int(os.getenv("NUM_STOCKS", "10"))
CANDIDATE_POOL_SIZE = int(os.getenv("CANDIDATE_POOL_SIZE", "50"))
SHORTLIST_SIZE = int(os.getenv("SHORTLIST_SIZE", "12"))
MOVERS_POOL_SIZE = int(os.getenv("MOVERS_POOL_SIZE", "25"))
NEWS_ARTICLES_PER_SYMBOL = int(os.getenv("NEWS_ARTICLES_PER_SYMBOL", "4"))

MAX_STOCK_PRICE = float(os.getenv("MAX_STOCK_PRICE", "30.00"))
MIN_STOCK_PRICE = float(os.getenv("MIN_STOCK_PRICE", "2.00"))
MOMENTUM_LOOKBACK_DAYS = int(os.getenv("MOMENTUM_LOOKBACK_DAYS", "20"))

WEIGHT_VOLUME = float(os.getenv("WEIGHT_VOLUME", "0.10"))
WEIGHT_X = float(os.getenv("WEIGHT_X", "0.15"))
WEIGHT_MOMENTUM = float(os.getenv("WEIGHT_MOMENTUM", "0.20"))
WEIGHT_ROE = float(os.getenv("WEIGHT_ROE", "0.20"))
WEIGHT_AI_RESEARCH = float(os.getenv("WEIGHT_AI_RESEARCH", "0.35"))

MIN_AI_SCORE_THRESHOLD = float(os.getenv("MIN_AI_SCORE_THRESHOLD", "0.10"))

STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "-0.20"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0"))  # 0 = disabled

X_LOOKBACK_HOURS = int(os.getenv("X_LOOKBACK_HOURS", "24"))
X_MAX_RESULTS_PER_QUERY = int(os.getenv("X_MAX_RESULTS_PER_QUERY", "100"))

STATE_FILE = os.path.join(os.path.dirname(__file__), "last_run.json")
LOG_FILE = os.path.join(os.path.dirname(__file__), "bot.log")
