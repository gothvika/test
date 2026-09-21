#!/usr/bin/env python3
"""
Standalone live-verification script for data_sources.get_top_movers().

Run this locally to see the RAW response from Alpaca's movers screener
before trusting how data_sources.py parses it. Read-only — GET only.

Usage:
    python3 test_alpaca_movers.py
    python3 test_alpaca_movers.py --limit 5
"""
import argparse
import json
import sys

import requests
import config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
        print("ALPACA_API_KEY/ALPACA_SECRET_KEY not set in your .env — aborting.")
        sys.exit(1)

    url = f"{config.ALPACA_DATA_BASE_URL}/v1beta1/screener/stocks/movers"
    headers = {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    }
    params = {"top": args.limit}

    print(f"GET {url}")
    print(f"params: {params}\n")

    resp = requests.get(url, headers=headers, params=params, timeout=15)
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
        print(
            f"Got an error status ({resp.status_code}). Could mean: the movers screener "
            f"needs a different plan/subscription than most-actives/bars, the path is wrong, "
            f"or it's outside market hours (some screener endpoints only return data while "
            f"the market is open — try again during 9:30am-4:00pm ET if this looks like a "
            f"permissions issue rather than an empty-market issue)."
        )
        sys.exit(1)

    gainers = data.get("gainers") if isinstance(data, dict) else None
    if isinstance(gainers, list) and gainers:
        print("Found a 'gainers' list. First item's keys:")
        print(list(gainers[0].keys()))
        print(
            "\nDoes this include a 'symbol' key (the only field "
            "data_sources.get_top_movers() reads)? If the key is named differently, "
            "tell me and I'll fix the parsing."
        )
    elif isinstance(gainers, list):
        print(
            "'gainers' is an empty list. Could be normal (quiet market / after hours) or a "
            "wrong param — try again during market hours if this looks unexpected."
        )
    else:
        top_level_keys = list(data.keys()) if isinstance(data, dict) else "N/A (response is not a dict)"
        print(f"No 'gainers' key found. Actual top-level keys: {top_level_keys}")


if __name__ == "__main__":
    main()
