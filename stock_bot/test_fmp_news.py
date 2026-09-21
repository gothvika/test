#!/usr/bin/env python3
"""
Standalone live-verification script for news_sources.get_recent_news().

Run this locally (where financialmodelingprep.com isn't network-blocked)
to see the RAW response from FMP's news endpoint before trusting how
news_sources.py parses it. If the shape doesn't match what's expected
below, tell me the printed output and I'll fix the parsing.

Usage:
    python3 test_fmp_news.py AAPL
    python3 test_fmp_news.py SOFI --limit 3
"""
import argparse
import json
import sys

import requests
import config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    if not config.FMP_API_KEY:
        print("FMP_API_KEY not set in your .env — aborting.")
        sys.exit(1)

    url = f"{config.FMP_BASE_URL}/news/stock"
    params = {"symbols": args.symbol, "limit": args.limit, "apikey": config.FMP_API_KEY}

    print(f"GET {url}")
    print(f"params: {dict(params, apikey='***redacted***')}\n")

    resp = requests.get(url, params=params, timeout=15)
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
        print(f"Got an error status ({resp.status_code}). If it's 404, the endpoint path "
              f"'{url}' is probably wrong for the /stable/ API — check "
              f"https://site.financialmodelingprep.com/developer/docs for the correct "
              f"stock-news path and tell me what it should be.")
        sys.exit(1)

    if isinstance(data, list) and data:
        print("Looks like a list of articles. First item's keys:")
        print(list(data[0].keys()))
        print("\nDoes this match news_sources.py's expected fields "
              "(title, publishedDate, url, text)? If any key names differ, tell me "
              "the actual keys and I'll fix news_sources.py to match.")
    elif isinstance(data, list):
        print("Got an empty list — either this symbol has no recent news, or the "
              "params/endpoint are wrong. Try a very liquid symbol like AAPL to rule that out.")
    else:
        print(f"Unexpected response shape: {type(data)}. news_sources.py currently assumes "
              f"a bare list — if FMP wraps it in an object (e.g. {{'news': [...]}}), tell me "
              f"the wrapper key and I'll fix the parsing.")


if __name__ == "__main__":
    main()
