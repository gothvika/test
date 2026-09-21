#!/usr/bin/env python3
"""
Backtests the momentum signal against real historical Alpaca daily bars.

IMPORTANT — what this does and does NOT validate. Read this before trusting
any output:

  This replays ONLY the momentum component of the live scoring pipeline —
  rank a fixed universe of symbols by trailing N-day price return, "buy"
  the top K, hold for a forward window, measure the return, repeat. It
  does NOT and structurally CANNOT replay:

    - the volume/"most-active" and movers sourcing (Alpaca's screener is a
      live snapshot, not time-travelable — there is no way to ask "what
      was most-active 60 trading days ago")
    - the X mention signal (no historical archive access)
    - the AI research signal (there's no way to ask a model to "research
      this stock as of a past date" — running it live today would just be
      an opinion on TODAY's news, not what was known back then)
    - ROE-based filtering with proper point-in-time data (would need
      report-date-aligned historical fundamentals to avoid look-ahead
      bias; not implemented here)

  So a good result here tells you the momentum signal isn't obviously
  useless. It does NOT tell you the live pipeline — which weights AI
  research at 0.35, the single largest weight — would have made money.
  Treat this as a sanity check on one reproducible ingredient, not a
  validation of the full recipe.

Usage:
    python3 backtest.py --symbols AAPL,MSFT,TSLA,SOFI,PLTR \\
        --start 2025-01-01 --end 2025-09-01 \\
        --lookback-days 20 --hold-days 10 --top-n 3

Requires ALPACA_API_KEY / ALPACA_SECRET_KEY in your environment (same as
the rest of the bot) — uses Alpaca's historical bars endpoint, which is
free on IEX. Not yet run against the live API from this environment
(network-blocked here) — needs a real test.
"""

import argparse
import logging
from datetime import datetime

import requests

import config

logger = logging.getLogger("stock_bot.backtest")


def _fetch_daily_bars(symbols: list[str], start, end) -> dict[str, list[dict]]:
    """Returns {symbol: [bar, ...]} of Alpaca daily bars, paginating as needed."""
    url = f"{config.ALPACA_DATA_BASE_URL}/v2/stocks/bars"
    headers = {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    }
    bars_by_symbol = {s: [] for s in symbols}
    page_token = None

    while True:
        params = {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 10000,
            "adjustment": "split",
            "feed": config.ALPACA_DATA_FEED,
        }
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        for sym, bars in body.get("bars", {}).items():
            bars_by_symbol.setdefault(sym, []).extend(bars)

        page_token = body.get("next_page_token")
        if not page_token:
            break

    return bars_by_symbol


def run_backtest(symbols, start, end, lookback_days, hold_days, top_n) -> list[dict]:
    bars_by_symbol = _fetch_daily_bars(symbols, start, end)

    all_dates = sorted({bar["t"][:10] for bars in bars_by_symbol.values() for bar in bars})
    min_days_needed = lookback_days + hold_days + 1
    if len(all_dates) < min_days_needed:
        raise RuntimeError(
            f"Only {len(all_dates)} trading days of data in range — need at least "
            f"{min_days_needed} for one decision + hold cycle. Widen --start/--end."
        )

    closes = {
        sym: {bar["t"][:10]: bar["c"] for bar in bars}
        for sym, bars in bars_by_symbol.items()
    }

    trades = []
    decision_idx = lookback_days
    while decision_idx + hold_days < len(all_dates):
        decision_date = all_dates[decision_idx]
        lookback_start_date = all_dates[decision_idx - lookback_days]
        exit_date = all_dates[decision_idx + hold_days]

        momentum = {}
        for sym in symbols:
            c0 = closes.get(sym, {}).get(lookback_start_date)
            c1 = closes.get(sym, {}).get(decision_date)
            if c0 and c1:
                momentum[sym] = (c1 - c0) / c0

        picks = sorted(momentum, key=momentum.get, reverse=True)[:top_n]

        forward_returns = []
        for sym in picks:
            entry = closes.get(sym, {}).get(decision_date)
            exit_price = closes.get(sym, {}).get(exit_date)
            if entry and exit_price:
                forward_returns.append((exit_price - entry) / entry)

        if forward_returns:
            benchmark_returns = [
                (closes[s][exit_date] - closes[s][decision_date]) / closes[s][decision_date]
                for s in symbols
                if closes.get(s, {}).get(decision_date) and closes.get(s, {}).get(exit_date)
            ]
            trades.append({
                "decision_date": decision_date,
                "exit_date": exit_date,
                "picks": picks,
                "avg_return": sum(forward_returns) / len(forward_returns),
                "benchmark_avg_return": (
                    sum(benchmark_returns) / len(benchmark_returns) if benchmark_returns else None
                ),
            })

        decision_idx += hold_days  # non-overlapping cycles, no compounding assumed

    return trades


def summarize(trades: list[dict]) -> None:
    if not trades:
        print("No trades produced — check date range and symbol data availability.")
        return

    strat_returns = [t["avg_return"] for t in trades]
    bench_returns = [t["benchmark_avg_return"] for t in trades if t["benchmark_avg_return"] is not None]

    strat_avg = sum(strat_returns) / len(strat_returns)
    bench_avg = sum(bench_returns) / len(bench_returns) if bench_returns else None
    win_rate = sum(1 for r in strat_returns if r > 0) / len(strat_returns)

    print(f"\n{'=' * 60}")
    print(f"Backtest: {len(trades)} decision cycles")
    print(f"Momentum-strategy avg return per cycle:      {strat_avg:+.2%}")
    if bench_avg is not None:
        print(f"Equal-weight universe avg return per cycle:  {bench_avg:+.2%}")
        print(f"Edge vs. universe benchmark:                 {(strat_avg - bench_avg):+.2%}")
    print(f"Win rate (cycles with positive return):      {win_rate:.0%}")
    print(f"{'=' * 60}\n")

    for t in trades:
        b = f"{t['benchmark_avg_return']:+.2%}" if t["benchmark_avg_return"] is not None else "n/a"
        print(
            f"  {t['decision_date']} -> {t['exit_date']}: picks={t['picks']} "
            f"strategy={t['avg_return']:+.2%} benchmark={b}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", required=True, help="Comma-separated tickers to backtest over")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--lookback-days", type=int, default=config.MOMENTUM_LOOKBACK_DAYS)
    parser.add_argument("--hold-days", type=int, default=10, help="Trading days to hold each cycle's picks")
    parser.add_argument("--top-n", type=int, default=3, help="How many top-momentum symbols to 'buy' each cycle")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    trades = run_backtest(symbols, start, end, args.lookback_days, args.hold_days, args.top_n)
    summarize(trades)


if __name__ == "__main__":
    main()
