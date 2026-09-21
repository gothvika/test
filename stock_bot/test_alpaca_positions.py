#!/usr/bin/env python3
"""
Standalone live-verification script for trader.get_positions() and the
fields apply_stop_loss_and_take_profit() relies on.

READ-ONLY: this only calls GET /v2/positions. It never places or closes
an order, so it's safe to run regardless of ALPACA_PAPER.

Usage:
    python3 test_alpaca_positions.py
"""
import json
import sys

import requests
import config


def main():
    if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
        print("ALPACA_API_KEY/ALPACA_SECRET_KEY not set in your .env — aborting.")
        sys.exit(1)

    mode = "PAPER" if config.ALPACA_PAPER else "LIVE"
    url = f"{config.ALPACA_TRADING_BASE_URL}/v2/positions"
    headers = {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    }

    print(f"GET {url}  (mode: {mode})\n")

    resp = requests.get(url, headers=headers, timeout=15)
    print(f"status: {resp.status_code}\n")

    try:
        data = resp.json()
    except Exception:
        print("Response was not valid JSON. Raw text:")
        print(resp.text[:2000])
        sys.exit(1)

    print("--- raw JSON (pretty-printed) ---")
    print(json.dumps(data, indent=2)[:4000])
    print("---\n")

    if resp.status_code >= 400:
        print(f"Got an error status ({resp.status_code}).")
        sys.exit(1)

    if isinstance(data, list) and data:
        print("Found open position(s). First one's keys:")
        print(list(data[0].keys()))
        expected = {"symbol", "qty", "avg_entry_price", "unrealized_plpc"}
        missing = expected - set(data[0].keys())
        if missing:
            print(f"\nMISSING expected field(s): {missing} — trader.get_positions() will KeyError "
                  f"on these. Tell me the actual field names and I'll fix it.")
        else:
            print("\nAll fields trader.get_positions() expects are present. Looks good.")
    elif isinstance(data, list):
        print(
            "No open positions right now — this is expected if you haven't run main.py "
            "with real buys yet (preview_picks.py never places orders). The endpoint itself "
            "responded correctly (empty list, not an error); we just can't confirm the exact "
            "field names until there's at least one position. That's fine to leave for later — "
            "worth re-running this once you've bought something in paper trading."
        )
    else:
        print(f"Unexpected response shape: {type(data)}.")


if __name__ == "__main__":
    main()
