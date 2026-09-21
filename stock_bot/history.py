"""
Persistent local history of every report generated and every order
executed — so results can actually be reviewed after running the bot for
a while, instead of only ever seeing "today" (last_run.json gets
overwritten daily; bot.log is unstructured text, not analyzable).

Writes one JSON file per calendar date to HISTORY_DIR
(stock_bot/history/YYYY-MM-DD.json): created when a report is generated,
updated in place if orders are executed that same day. Each file ends up
a complete record of "what happened that day" — the picks, why they were
picked, any stop-loss/take-profit sells, and whether/what was bought.
Local-only (gitignored) — this is your own run history, not code.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date

logger = logging.getLogger("stock_bot.history")

HISTORY_DIR = os.path.join(os.path.dirname(__file__), "history")


def _file_for(day: str) -> str:
    return os.path.join(HISTORY_DIR, f"{day}.json")


def record_report(
    picks: list, sell_results: dict, market_open: bool, mode: str,
    full_shortlist: list = None, day: str = None,
) -> None:
    """
    Writes today's report record (picks + any stop-loss/take-profit
    sells). full_shortlist — every symbol that survived exclusions and
    got AI-researched, before truncating to the top picks (see
    scorer.pick_top_stocks) — is kept alongside `picks` so
    review_history.py can later check whether the ranking actually added
    value over the rest of the shortlist, not just whether the top picks
    went up or down.
    """
    day = day or date.today().isoformat()
    os.makedirs(HISTORY_DIR, exist_ok=True)
    record = {
        "date": day,
        "mode": mode,
        "market_open": market_open,
        "sell_results": sell_results,
        "picks": picks,
        "full_shortlist": full_shortlist or [],
        "executed": False,
        "execution": None,
    }
    try:
        with open(_file_for(day), "w") as f:
            json.dump(record, f, indent=2, default=str)
    except Exception:
        logger.exception("Failed to write history record for %s", day)


def record_execution(results: dict, day: str = None) -> None:
    """Updates today's report record with the orders that were actually placed."""
    day = day or date.today().isoformat()
    path = _file_for(day)
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        if os.path.exists(path):
            with open(path) as f:
                record = json.load(f)
        else:
            # main.py/app.py always call record_report() first, but don't
            # assume it — fall back to a minimal record rather than losing
            # the execution data.
            record = {"date": day, "picks": [], "sell_results": {}}
        record["executed"] = True
        record["execution"] = results
        with open(path, "w") as f:
            json.dump(record, f, indent=2, default=str)
    except Exception:
        logger.exception("Failed to update history record with execution for %s", day)


def load_all() -> list[dict]:
    """Returns every day's history record, oldest first. [] if none yet."""
    if not os.path.isdir(HISTORY_DIR):
        return []
    records = []
    for name in sorted(os.listdir(HISTORY_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(HISTORY_DIR, name)) as f:
                records.append(json.load(f))
        except Exception:
            logger.warning("Skipping unreadable history file: %s", name)
    return records
