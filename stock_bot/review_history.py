#!/usr/bin/env python3
"""
Reviews the local history/ directory built up by app.py/main.py over
time — run this after a stretch of daily use (e.g. a 2-week trial) to see
how the bot's actual picks performed, not just what it predicted at the
time.

Reports:
  - How many picks were shown, average AI research score, most frequently
    picked symbols, any stop-loss/take-profit sells and their P/L.
  - For every executed buy: current price vs. entry price (fetched live
    from Alpaca), aggregated into a win rate and average return, plus
    execution slippage (filled price vs. the price the pipeline scored
    on) if fill data was captured.
  - Whether the ranking actually added value: a hypothetical "what if
    you'd bought everything in the shortlist" comparison between the
    top-N picks that got bought and the rest of that day's shortlist —
    without this, all you can ever say is "the picks went up/down X%",
    with no way to tell whether the AI's ranking did anything.

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
    executed_positions = []  # [{date, symbol, entry_price, filled_price}]
    shortlist_entries = []  # [{date, symbol, price, in_top_n}]

    for rec in records:
        picks = rec.get("picks") or []
        full_shortlist = rec.get("full_shortlist") or []
        top_symbols = {p["symbol"] for p in picks}

        total_picks += len(picks)
        for p in picks:
            symbol_counts[p["symbol"]] += 1
            if p.get("ai_score") is not None:
                ai_scores.append(p["ai_score"])

        for entry in full_shortlist:
            if entry.get("price"):
                shortlist_entries.append({
                    "date": rec.get("date"), "symbol": entry["symbol"],
                    "price": entry["price"], "in_top_n": entry["symbol"] in top_symbols,
                })

        for sym, r in (rec.get("sell_results") or {}).items():
            sell_actions.append((rec.get("date"), sym, r))

        if rec.get("executed"):
            executed_days += 1
            execution = rec.get("execution") or {}
            for sym, r in execution.items():
                if r.get("status") == "submitted":
                    entry_price = r.get("scored_price") or next(
                        (p["price"] for p in picks if p["symbol"] == sym), None
                    )
                    filled_price = r.get("filled_avg_price")
                    executed_positions.append({
                        "date": rec.get("date"), "symbol": sym,
                        "entry_price": entry_price,
                        "filled_price": float(filled_price) if filled_price else None,
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
        slippages = []
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

            if pos["filled_price"] and pos["entry_price"]:
                slippages.append((pos["filled_price"] - pos["entry_price"]) / pos["entry_price"])

        if returns:
            win_rate = sum(1 for r in returns if r > 0) / len(returns)
            avg_return = sum(returns) / len(returns)
            print(f"\nAcross {len(returns)} executed position(s): avg return {avg_return:+.1%}, win rate {win_rate:.0%}")

        if slippages:
            avg_slip = sum(slippages) / len(slippages)
            print(
                f"Avg execution slippage vs. scored price: {avg_slip:+.2%} across {len(slippages)} fill(s) "
                f"— positive means you paid more than the price the pipeline scored on."
            )
        else:
            print("No fill-price data captured yet (older records, or fills that timed out before a price was seen).")
    else:
        print("\nNo executed buys yet to evaluate.")

    if shortlist_entries:
        print("\n--- Did the ranking add value? (hypothetical return if bought: top-N vs. rest of shortlist) ---")
        symbols = sorted({e["symbol"] for e in shortlist_entries})
        try:
            current_prices = get_latest_prices(symbols)
        except Exception as exc:
            print(f"Could not fetch current prices for shortlist comparison: {exc}")
            current_prices = {}

        top_returns, rest_returns = [], []
        for e in shortlist_entries:
            current = current_prices.get(e["symbol"])
            if current is None:
                continue
            pct = (current - e["price"]) / e["price"]
            (top_returns if e["in_top_n"] else rest_returns).append(pct)

        if top_returns:
            print(f"  Top-N (bought) picks:        avg hypothetical return {sum(top_returns) / len(top_returns):+.1%}  (n={len(top_returns)})")
        if rest_returns:
            print(f"  Rest of shortlist (skipped): avg hypothetical return {sum(rest_returns) / len(rest_returns):+.1%}  (n={len(rest_returns)})")
        if top_returns and rest_returns:
            edge = sum(top_returns) / len(top_returns) - sum(rest_returns) / len(rest_returns)
            verdict = "ranking added value" if edge > 0 else "ranking did NOT add value (or hurt)"
            print(f"  Ranking edge (top-N minus rest): {edge:+.1%}  -> {verdict}")
    else:
        print("\nNo full-shortlist data yet (only present in reports generated after this feature was added).")

    print(f"\n{'=' * 60}\n")


if __name__ == "__main__":
    main()
