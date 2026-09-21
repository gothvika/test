#!/usr/bin/env python3
"""
Daily runner: picks the top N "active + peer-interest" stocks and buys
$DOLLARS_PER_STOCK of each via Alpaca.

Run manually:
    python main.py

Run via cron (example, weekdays at 3:45pm ET while market is open):
    45 15 * * 1-5 cd /path/to/stock_bot && /usr/bin/python3 main.py >> cron.log 2>&1

Safety:
  - Defaults to Alpaca's PAPER trading endpoint (config.ALPACA_PAPER=True).
    Nothing here touches real money until you deliberately set
    ALPACA_PAPER=false in your environment.
  - Keeps a small on-disk record (last_run.json) so re-running the script
    on the same calendar day won't buy twice.
  - Skips the run (without buying anything) if the market is closed.
  - Before buying, checks every existing position against
    config.STOP_LOSS_PCT / config.TAKE_PROFIT_PCT and sells anything that's
    crossed a threshold — this bot previously only ever bought, so a
    losing pick would sit there indefinitely with no exit.
"""

import json
import logging
import os
import sys
from datetime import date

import config
from scorer import pick_top_stocks
from trader import buy_dollar_amount, check_market_open, apply_stop_loss_and_take_profit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("stock_bot.main")


def _load_state() -> dict:
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE) as f:
            return json.load(f)
    return {}


def _save_state(state: dict) -> None:
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def main():
    missing = [
        name for name, val in [
            ("ALPACA_API_KEY", config.ALPACA_API_KEY),
            ("ALPACA_SECRET_KEY", config.ALPACA_SECRET_KEY),
            ("ANTHROPIC_API_KEY", config.ANTHROPIC_API_KEY),
            ("FMP_API_KEY", config.FMP_API_KEY),
        ] if not val
    ]
    if missing:
        logger.error("Missing required environment variables: %s. Aborting.", ", ".join(missing))
        sys.exit(1)

    today = date.today().isoformat()
    state = _load_state()

    if state.get("last_run_date") == today:
        logger.info("Already ran today (%s). Skipping to avoid a double buy.", today)
        return

    if not check_market_open():
        logger.info("Market is currently closed. Skipping this run — try again "
                     "during market hours (9:30am-4:00pm ET, Mon-Fri).")
        return

    mode = "PAPER" if config.ALPACA_PAPER else "LIVE"
    logger.info("=== Starting daily run (%s trading) ===", mode)

    sell_results = apply_stop_loss_and_take_profit()
    if sell_results:
        logger.info("Stop-loss/take-profit actions: %s", sell_results)

    try:
        picks = pick_top_stocks()
    except Exception:
        logger.exception("Failed to pick stocks — aborting this run, no orders placed.")
        sys.exit(1)

    if not picks:
        logger.warning("No stocks were picked. Nothing to buy today.")
        return

    results = {}
    for pick in picks:
        symbol = pick["symbol"]
        try:
            order = buy_dollar_amount(symbol, config.DOLLARS_PER_STOCK)
            results[symbol] = {
                "status": "submitted",
                "order_id": order.get("id"),
                "final_score": pick["final_score"],
                "ai_summary": pick["ai_summary"],
            }
        except Exception as exc:
            logger.exception("Order failed for %s", symbol)
            results[symbol] = {"status": "failed", "error": str(exc)}

    state["last_run_date"] = today
    state["last_picks"] = results
    state["sell_actions"] = sell_results
    _save_state(state)

    succeeded = sum(1 for r in results.values() if r["status"] == "submitted")
    logger.info("=== Run complete: %d/%d orders submitted ===", succeeded, len(picks))


if __name__ == "__main__":
    main()
