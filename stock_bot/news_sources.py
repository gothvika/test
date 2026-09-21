"""
Recent company news via Financial Modeling Prep's stock-news endpoint —
used to ground the AI research step in real, dated, source-linked articles
instead of relying solely on the model's own web search, which can't be
logged or checked after the fact.

Docs: https://site.financialmodelingprep.com/developer/docs

Endpoint path and response field names (symbol, publishedDate, publisher,
title, image, site, text, url) confirmed live against
/stable/news/stock?symbols=...&limit=...&apikey=... — verified 2026-09-21
via test_fmp_news.py against AAPL.
"""

from __future__ import annotations

import logging
import re

import requests

import config

logger = logging.getLogger("stock_bot.news_sources")

# Auto-generated "institutional holdings" filler articles (a fund/bank
# bought or trimmed some shares, per its latest 13F) — confirmed live to
# make up the bulk of a typical feed (4 of 5 articles fetched for AAPL).
# These are template-written from routine SEC filings, not analysis or
# news in any useful sense, so they'd just crowd out real signal in the
# AI research prompt. Matched on the boilerplate disclosure phrasing every
# one of them uses, not on publisher name (too fragile/endless to
# maintain a mill blocklist).
_INSTITUTIONAL_FILING_PATTERN = re.compile(
    r"disclosure with the (?:securities and exchange commission|sec)"
    r"|form 13f filing"
    r"|\b13f filing\b"
    r"|according to (?:its|the company.s) most recent (?:13f )?filing",
    re.IGNORECASE,
)

# Over-fetch from FMP so that filtering out boilerplate still leaves
# `limit` real articles where possible, without unbounded cost.
_FETCH_MULTIPLIER = 5
_MAX_FETCH = 25


def _is_institutional_filing_boilerplate(row: dict) -> bool:
    text = f"{row.get('title') or ''} {row.get('text') or ''}"
    return bool(_INSTITUTIONAL_FILING_PATTERN.search(text))


def get_recent_news(symbol: str, limit: int = None) -> list[dict]:
    """
    Returns up to `limit` recent, non-boilerplate news articles for
    `symbol`, most recent first, as
    [{"title": ..., "date": ..., "url": ..., "snippet": ...}].

    Never raises — returns [] on any lookup failure (missing coverage,
    rate limit, endpoint hiccup), so a news-API problem can't take down a
    whole day's run. ai_research.py treats an empty list as "no articles
    available" and falls back to the model's own web search only.
    """
    limit = limit or config.NEWS_ARTICLES_PER_SYMBOL
    fetch_limit = min(limit * _FETCH_MULTIPLIER, _MAX_FETCH)

    url = f"{config.FMP_BASE_URL}/news/stock"
    params = {"symbols": symbol, "limit": fetch_limit, "apikey": config.FMP_API_KEY}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        logger.warning("News lookup failed for %s: %s", symbol, exc)
        return []

    if not isinstance(rows, list):
        logger.warning("Unexpected news response shape for %s: %r", symbol, type(rows))
        return []

    filtered_rows = [row for row in rows if not _is_institutional_filing_boilerplate(row)]
    dropped = len(rows) - len(filtered_rows)
    if dropped:
        logger.info("Filtered %d institutional-filing boilerplate article(s) for %s", dropped, symbol)

    articles = []
    for row in filtered_rows[:limit]:
        articles.append({
            "title": row.get("title"),
            "date": row.get("publishedDate"),
            "url": row.get("url"),
            "snippet": (row.get("text") or "")[:300],
        })

    logger.info("Fetched %d usable news articles for %s", len(articles), symbol)
    return articles
