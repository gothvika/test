#!/usr/bin/env python3
"""
Live snapshot analysis of your actual Alpaca account — what the broker
itself reports right now (current positions, their real-time P/L, cash,
equity), not a reconstruction from local logs (that's what
review_history.py does from stock_bot/history/). Also breaks the
portfolio down by sector to flag concentration risk.

Since this bot only ever buys what it picks, this account should only
ever contain its picks (plus anything you've bought manually in it) —
this script doesn't try to distinguish the two, it just reports what's
actually held.

Usage:
    python3 analyze_portfolio.py
"""
import sys
from collections import defaultdict

from fundamentals import get_company_profile
from trader import get_account, get_positions

CONCENTRATION_WARNING_PCT = 0.40  # flag any sector holding more than this share of the portfolio


def main():
    try:
        positions = get_positions()
    except Exception as exc:
        print(f"Failed to fetch positions: {exc}")
        sys.exit(1)

    try:
        account = get_account()
    except Exception as exc:
        print(f"Failed to fetch account info: {exc}")
        account = None

    if not positions:
        print("No open positions right now.")
        if account:
            print(f"Cash: ${account['cash']:.2f}   Portfolio value: ${account['portfolio_value']:.2f}")
        sys.exit(0)

    print(f"\n{'=' * 78}")
    print(f"Portfolio snapshot — {len(positions)} position(s)")
    print(f"{'=' * 78}\n")

    total_market_value = 0.0
    total_unrealized_pl = 0.0
    total_cost_basis = 0.0
    sector_value = defaultdict(float)
    rows = []

    for pos in positions:
        symbol = pos["symbol"]
        market_value = pos.get("market_value")
        unrealized_pl = pos.get("unrealized_pl")
        cost_basis = pos.get("cost_basis")

        if market_value is not None:
            total_market_value += market_value
        if unrealized_pl is not None:
            total_unrealized_pl += unrealized_pl
        if cost_basis is not None:
            total_cost_basis += cost_basis

        try:
            profile = get_company_profile(symbol)
        except Exception:
            profile = None
        sector = (profile or {}).get("sector") or "Unknown"
        if market_value is not None:
            sector_value[sector] += market_value

        rows.append((pos, sector))

    header = f"{'Symbol':<8}{'Qty':>10}{'Avg entry':>12}{'Current':>12}{'Value':>12}{'P/L':>11}{'P/L %':>9}  Sector"
    print(header)
    print("-" * len(header))
    for pos, sector in rows:
        current = pos.get("current_price")
        value = pos.get("market_value")
        pl = pos.get("unrealized_pl")
        plpc = pos.get("unrealized_plpc")
        current_str = f"${current:.2f}" if current is not None else "n/a"
        value_str = f"${value:.2f}" if value is not None else "n/a"
        pl_str = f"${pl:+.2f}" if pl is not None else "n/a"
        print(
            f"{pos['symbol']:<8}{pos['qty']:>10.4f}"
            f"{'$' + format(pos['avg_entry_price'], '.2f'):>12}"
            f"{current_str:>12}{value_str:>12}{pl_str:>11}"
            f"{format(plpc * 100, '+.1f') + '%':>9}  {sector}"
        )

    print(f"\nTotal market value: ${total_market_value:.2f}")
    if total_cost_basis:
        print(f"Total unrealized P/L: ${total_unrealized_pl:+.2f} ({total_unrealized_pl / total_cost_basis:+.1%})")
    if account:
        print(f"Cash: ${account['cash']:.2f}   Total equity: ${account['equity']:.2f}")

    print("\n--- Sector concentration ---")
    if total_market_value > 0:
        for sector, value in sorted(sector_value.items(), key=lambda x: -x[1]):
            pct = value / total_market_value
            flag = f"  <-- over {CONCENTRATION_WARNING_PCT:.0%} of portfolio in one sector" if pct > CONCENTRATION_WARNING_PCT else ""
            print(f"  {sector:<25}${value:>10.2f}  {pct:>6.1%}{flag}")

    print(f"\n{'=' * 78}\n")


if __name__ == "__main__":
    main()
