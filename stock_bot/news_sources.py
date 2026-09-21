"""
Recent company news via Financial Modeling Prep's stock-news endpoint —
used to ground the AI research step in real, dated, source-linked articles
instead of relying solely on the model's own web search, which can't be
logged or checked after the fact.

Docs: https://site.financialmodelingprep.com/developer/docs

NOTE: endpoint path/response field names are assumed from FMP's published
/stable/ API docs, following the same pattern as fundamentals.py's
profile/income-statement/balance-sheet-statement calls. Not yet confirmed
against the live API from this environment (financialmodelingprep.com is
network-blocked here) — needs a real test, and the field names below may
need adjusting once it's run live (same as /stable/profile did).
"""

from __future__ import annotations

import logging

import requests

import config

logger = logging.getLogger("stock_bot.news_sources")


def get_recent_news(symbol: str, limit: int = None) -> list[dict]:
    """
    Returns up to `limit` recent news articles for `symbol`, most recent
    first, as [{"title": ..., "date": ..., "url": ..., "snippet": ...}].

    Never raises — returns [] on any lookup failure (missing coverage,
    rate limit, endpoint hiccup), so a news-API problem can't take down a
    whole day's run. ai_research.py treats an empty list as "no articles
    available" and falls back to the model's own web search only.
    """
    limit = limit or config.NEWS_ARTICLES_PER_SYMBOL
    url = f"{config.FMP_BASE_URL}/news/stock"
    params = {"symbols": symbol, "limit": limit, "apikey": config.FMP_API_KEY}

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

    articles = []
    for row in rows[:limit]:
        articles.append({
            "title": row.get("title"),
            "date": row.get("publishedDate"),
            "url": row.get("url"),
            "snippet": (row.get("text") or "")[:300],
        })

    logger.info("Fetched %d news articles for %s", len(articles), symbol)
    return articles
