#!/usr/bin/env python3
"""
Reviews the local history/ directory built up by app.py/main.py over
time — run this after a stretch of daily use (e.g. a 2-week trial) to see
how the bot's actual picks performed, not just what it predicted at the
time.

Reports: how many picks were shown, average AI research score, most
frequently picked symbols, any stop-loss/take-profit sells and their
P/L, and — for every executed buy — current price vs. entry price
(fetched live from Alpaca), aggregated into a win rate and average
return.

Usage:
    python3 review_history.py
"""
import sys
from collections import Counter

import history
from data_sources import get_latest_prices


def main():
    records = history.load_all()
    if not records:
        print("No history yet — history/ is empty. Generate at least one report via app.py or main.py first.")
        sys.exit(0)

    print(f"\n{'=' * 60}")
    print(f"History review: {len(records)} day(s) recorded")
    print(f"{'=' * 60}\n")

    total_picks = 0
    executed_days = 0
    symbol_counts = Counter()
    ai_scores = []
    sell_actions = []
    executed_positions = []  # [{date, symbol, entry_price}]

    for rec in records:
        picks = rec.get("picks") or []
        total_picks += len(picks)
        for p in picks:
            symbol_counts[p["symbol"]] += 1
            if p.get("ai_score") is not None:
                ai_scores.append(p["ai_score"])

        for sym, r in (rec.get("sell_results") or {}).items():
            sell_actions.append((rec.get("date"), sym, r))

        if rec.get("executed"):
            executed_days += 1
            execution = rec.get("execution") or {}
            for sym, r in execution.items():
                if r.get("status") == "submitted":
                    entry_price = next((p["price"] for p in picks if p["symbol"] == sym), None)
                    executed_positions.append({
                        "date": rec.get("date"), "symbol": sym, "entry_price": entry_price,
                    })

    print(f"Total picks shown across all reports: {total_picks}")
    print(f"Days with orders executed: {executed_days}/{len(records)}")
    if ai_scores:
        print(f"Average AI research score across all picks: {sum(ai_scores) / len(ai_scores):.2f}")
    if symbol_counts:
        print(f"Most frequently picked symbols: {symbol_counts.most_common(10)}")

    if sell_actions:
        print("\nStop-loss / take-profit actions taken:")
        for d, sym, r in sell_actions:
            plpc = r.get("unrealized_plpc")
            plpc_str = f"{plpc * 100:+.1f}%" if plpc is not None else "n/a"
            print(f"  {d}  {sym:6s}  {r.get('action')}  (P/L {plpc_str})")

    if executed_positions:
        print("\n--- Performance of executed buys (current price vs. entry) ---")
        symbols = sorted({p["symbol"] for p in executed_positions})
        try:
            current_prices = get_latest_prices(symbols)
        except Exception as exc:
            print(f"Could not fetch current prices: {exc}")
            current_prices = {}

        returns = []
        for pos in executed_positions:
            current = current_prices.get(pos["symbol"])
            if current is not None and pos["entry_price"]:
                pct = (current - pos["entry_price"]) / pos["entry_price"]
                returns.append(pct)
                print(
                    f"  {pos['date']}  {pos['symbol']:6s}  entry=${pos['entry_price']:.2f}  "
                    f"now=${current:.2f}  {pct:+.1%}"
                )
            else:
                print(f"  {pos['date']}  {pos['symbol']:6s}  entry=${pos['entry_price']}  now=n/a")

        if returns:
            win_rate = sum(1 for r in returns if r > 0) / len(returns)
            avg_return = sum(returns) / len(returns)
            print(f"\nAcross {len(returns)} executed position(s): avg return {avg_return:+.1%}, win rate {win_rate:.0%}")
    else:
        print("\nNo executed buys yet to evaluate.")

    print(f"\n{'=' * 60}\n")


if __name__ == "__main__":
    main()
