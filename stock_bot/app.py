#!/usr/bin/env python3
"""
Local web interface for the stock bot.

Three deliberate steps, each its own click — nothing runs automatically:
  1. Landing page (GET /): shows mode (PAPER/LIVE) and market status.
  2. Generate report (POST /report): runs the full picking pipeline (this
     calls paid APIs — Anthropic, FMP, X — so it's a real cost per click,
     which is why it's a button press, not something that fires on every
     page load) and any due stop-loss/take-profit sells, then shows a
     report with a "Confirm & Buy" form.
  3. Execute (POST /execute): places the exact orders shown in that
     report — never a freshly recomputed set — and only once (the run_id
     is single-use, so double-submitting a form can't double-buy).

This is a second, interactive entry point alongside main.py (which stays
as the non-interactive path for cron/scheduled runs) — nothing here
changes how main.py behaves.

Run:
    python3 app.py

Then open http://127.0.0.1:5000 — bound to localhost only, not your
network, since this handles real trading credentials and (if
ALPACA_PAPER=false) real orders.
"""
import json
import logging
import os
import secrets
import sys
from datetime import date, datetime

from flask import Flask, render_template, request, url_for

import config
import history
from data_sources import get_latest_prices
from fundamentals import get_company_profile
from scorer import pick_top_stocks
from trader import (
    buy_dollar_amount,
    check_market_open,
    apply_stop_loss_and_take_profit,
    get_account,
    get_positions,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(config.LOG_FILE), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("stock_bot.app")

app = Flask(__name__)

# In-memory cache of the most recently generated report, keyed by a
# one-time run_id. /execute acts on the EXACT picks shown to the user —
# never a freshly recomputed set (prices/scores could differ, and
# recomputing would mean paying for AI research twice) — and the run_id
# is popped once used, so a duplicate form submission can't double-buy.
# This is process-local by design: restarting the server invalidates any
# pending report, which is the safe failure mode here.
_last_report = {}


def _missing_env_vars():
    return [
        name for name, val in [
            ("ALPACA_API_KEY", config.ALPACA_API_KEY),
            ("ALPACA_SECRET_KEY", config.ALPACA_SECRET_KEY),
            ("ANTHROPIC_API_KEY", config.ANTHROPIC_API_KEY),
            ("FMP_API_KEY", config.FMP_API_KEY),
        ] if not val
    ]


def _load_state():
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE) as f:
            return json.load(f)
    return {}


def _save_state(state):
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _already_ran_today():
    return _load_state().get("last_run_date") == date.today().isoformat()


def _mode():
    return "PAPER" if config.ALPACA_PAPER else "LIVE"


@app.route("/")
def index():
    missing = _missing_env_vars()
    if missing:
        return render_template("error.html", message=f"Missing required environment variables: {', '.join(missing)}")

    try:
        market_open = check_market_open()
    except Exception as exc:
        logger.exception("Failed to check market status")
        return render_template("error.html", message=f"Failed to check market status: {exc}")

    return render_template(
        "index.html",
        market_open=market_open,
        already_ran=_already_ran_today(),
        mode=_mode(),
        dollars_per_stock=config.DOLLARS_PER_STOCK,
    )


@app.route("/portfolio")
def portfolio():
    """
    Live snapshot of the actual Alpaca account — current positions and
    their real broker-reported P/L, plus a sector breakdown to flag
    concentration. Unlike the report page, this reads live account state
    directly, not anything cached from a prior /report call.
    """
    missing = _missing_env_vars()
    if missing:
        return render_template("error.html", message=f"Missing required environment variables: {', '.join(missing)}")

    try:
        positions = get_positions()
    except Exception as exc:
        logger.exception("Failed to fetch positions")
        return render_template("error.html", message=f"Failed to fetch positions: {exc}")

    try:
        account = get_account()
    except Exception:
        logger.exception("Failed to fetch account info")
        account = None

    total_market_value = 0.0
    total_unrealized_pl = 0.0
    total_cost_basis = 0.0
    sector_value = {}
    rows = []

    for pos in positions:
        try:
            profile = get_company_profile(pos["symbol"])
        except Exception:
            profile = None
        sector = (profile or {}).get("sector") or "Unknown"

        market_value = pos.get("market_value") or 0.0
        unrealized_pl = pos.get("unrealized_pl") or 0.0
        cost_basis = pos.get("cost_basis") or 0.0
        total_market_value += market_value
        total_unrealized_pl += unrealized_pl
        total_cost_basis += cost_basis
        sector_value[sector] = sector_value.get(sector, 0.0) + market_value

        rows.append({**pos, "sector": sector})

    sector_breakdown = sorted(
        (
            {"sector": s, "value": v, "pct": (v / total_market_value if total_market_value else 0)}
            for s, v in sector_value.items()
        ),
        key=lambda x: -x["value"],
    )

    return render_template(
        "portfolio.html",
        positions=rows,
        account=account,
        total_market_value=total_market_value,
        total_unrealized_pl=total_unrealized_pl,
        total_unrealized_pct=(total_unrealized_pl / total_cost_basis if total_cost_basis else None),
        sector_breakdown=sector_breakdown,
        mode=_mode(),
        generated_at=datetime.now().strftime("%H:%M:%S"),
    )


@app.route("/history")
def history_list():
    """Every day a report was generated, most recent first."""
    records = list(reversed(history.load_all()))
    return render_template("history_list.html", records=records)


@app.route("/history/<day>")
def history_detail(day):
    """
    One day's full record: picks, any stop-loss/take-profit sells, orders
    placed (with fill price/slippage if executed), and the full shortlist
    split into bought vs. skipped — each with a live hypothetical return
    since that day, the same "did the ranking add value" check
    review_history.py does, but for a single day in the browser.
    """
    record = next((r for r in history.load_all() if r.get("date") == day), None)
    if not record:
        return render_template("error.html", message=f"No history record found for {day}.")

    picks = record.get("picks") or []
    full_shortlist = record.get("full_shortlist") or []
    top_symbols = {p["symbol"] for p in picks}

    symbols = sorted({e["symbol"] for e in full_shortlist if e.get("price")})
    current_prices = {}
    if symbols:
        try:
            current_prices = get_latest_prices(symbols)
        except Exception:
            logger.exception("Failed to fetch current prices for history detail %s", day)

    shortlist_rows = []
    for e in full_shortlist:
        current = current_prices.get(e["symbol"])
        hypothetical_return = (
            (current - e["price"]) / e["price"] if current is not None and e.get("price") else None
        )
        shortlist_rows.append({
            **e,
            "in_top_n": e["symbol"] in top_symbols,
            "current_price": current,
            "hypothetical_return": hypothetical_return,
        })
    shortlist_rows.sort(key=lambda r: (not r["in_top_n"], -(r.get("final_score") or 0)))

    return render_template(
        "history_detail.html",
        record=record,
        picks=picks,
        sell_results=record.get("sell_results") or {},
        execution=record.get("execution") or {},
        shortlist_rows=shortlist_rows,
    )


@app.route("/report", methods=["POST"])
def report():
    missing = _missing_env_vars()
    if missing:
        return render_template("error.html", message=f"Missing required environment variables: {', '.join(missing)}")

    try:
        market_open = check_market_open()
    except Exception as exc:
        logger.exception("Failed to check market status")
        return render_template("error.html", message=f"Failed to check market status: {exc}")

    already_ran = _already_ran_today()

    # Stop-loss/take-profit runs as part of generating the report (same
    # point in the flow as main.py) — it's risk management, not a new
    # trade decision, so it isn't gated behind its own confirm step.
    sell_results = {}
    if market_open and not already_ran:
        sell_results = apply_stop_loss_and_take_profit()

    try:
        picks, full_shortlist = pick_top_stocks()
    except Exception as exc:
        logger.exception("Failed to pick stocks")
        return render_template("error.html", message=f"Failed to generate picks: {exc}")

    run_id = secrets.token_urlsafe(16)
    _last_report.clear()  # only the most recent report is ever valid
    _last_report[run_id] = {"picks": picks, "sell_results": sell_results}

    history.record_report(picks, sell_results, market_open, _mode(), full_shortlist=full_shortlist)

    return render_template(
        "report.html",
        run_id=run_id,
        picks=picks,
        sell_results=sell_results,
        market_open=market_open,
        already_ran=already_ran,
        mode=_mode(),
        dollars_per_stock=config.DOLLARS_PER_STOCK,
        total_cost=config.DOLLARS_PER_STOCK * len(picks),
        today=date.today().isoformat(),
    )


@app.route("/execute", methods=["POST"])
def execute():
    run_id = request.form.get("run_id")
    cached = _last_report.get(run_id)
    if not cached:
        return render_template(
            "error.html",
            message="This report has expired, was already executed, or the server restarted "
                    "since it was generated. Go back and generate a fresh report before confirming.",
        )

    if _already_ran_today():
        _last_report.pop(run_id, None)
        return render_template("error.html", message="Already ran today — refusing to buy twice.")

    try:
        if not check_market_open():
            return render_template("error.html", message="Market is closed — refusing to place orders.")
    except Exception as exc:
        logger.exception("Failed to check market status before executing")
        return render_template("error.html", message=f"Failed to check market status: {exc}")

    picks = cached["picks"]
    results = {}
    for pick in picks:
        symbol = pick["symbol"]
        try:
            order = buy_dollar_amount(symbol, config.DOLLARS_PER_STOCK)
            results[symbol] = {
                "status": "submitted",
                "order_id": order.get("id"),
                "final_score": pick["final_score"],
                "scored_price": pick["price"],
                "filled_avg_price": order.get("filled_avg_price"),
            }
        except Exception as exc:
            logger.exception("Order failed for %s", symbol)
            results[symbol] = {"status": "failed", "error": str(exc)}

    state = _load_state()
    state["last_run_date"] = date.today().isoformat()
    state["last_picks"] = results
    state["sell_actions"] = cached["sell_results"]
    _save_state(state)

    history.record_execution(results)

    _last_report.pop(run_id, None)  # one-time use

    succeeded = sum(1 for r in results.values() if r["status"] == "submitted")
    return render_template(
        "executed.html",
        results=results,
        mode=_mode(),
        dollars_per_stock=config.DOLLARS_PER_STOCK,
        succeeded=succeeded,
        total=len(results),
    )


if __name__ == "__main__":
    if not config.ALPACA_PAPER:
        print("\n" + "=" * 60)
        print("WARNING: ALPACA_PAPER=false — this will place REAL orders with REAL money.")
        print("=" * 60 + "\n")
    # 127.0.0.1 only — never 0.0.0.0 — this handles trading credentials
    # and can place real orders; it must not be reachable from the network.
    app.run(host="127.0.0.1", port=5000, debug=False)
