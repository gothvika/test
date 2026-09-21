"""
Tests for news_sources.py's institutional-filing boilerplate filter. The
fixture articles below are the REAL response fetched live from FMP for
AAPL on 2026-09-21 (via test_fmp_news.py) — one genuine news article and
four auto-generated 13F-holdings blurbs, confirming the filter behaves
correctly against actual observed data, not just synthetic examples.
"""

from unittest.mock import MagicMock, patch

import config
import news_sources

REAL_AAPL_ARTICLE = {
    "symbol": "AAPL",
    "publishedDate": "2026-09-21 07:00:00",
    "publisher": "GlobeNewsWire",
    "title": "New iPhone Models Are the First Apple Devices to Operate on Dedicated Anterix 900 MHz Private Networks",
    "site": "globenewswire.com",
    "text": (
        "iPhone 18 Pro and iPhone Duo launch with Anterix 900 MHz connectivity, extending "
        "dedicated private wireless to one of the world's most widely used device platforms"
    ),
    "url": "https://www.globenewswire.com/news-release/2026/09/21/3365353/0/en/new-iphone-models.html",
}

REAL_13F_BLURBS = [
    {
        "symbol": "AAPL",
        "publishedDate": "2026-09-21 06:43:27",
        "publisher": "Defense World",
        "title": "SGL Investment Advisors Inc. Invests $11.73 Million in Apple Inc. $AAPL",
        "site": "defenseworld.net",
        "text": (
            "SGL Investment Advisors Inc. acquired a new position in shares of Apple Inc. "
            "(NASDAQ: AAPL) during the undefined quarter, according to its most recent "
            "disclosure with the SEC."
        ),
        "url": "https://www.defenseworld.net/2026/09/21/sgl-investment-advisors-inc.html",
    },
    {
        "symbol": "AAPL",
        "publishedDate": "2026-09-21 06:43:26",
        "publisher": "Defense World",
        "title": "Ninepoint Partners LP Buys Shares of 6,227 Apple Inc. $AAPL",
        "site": "defenseworld.net",
        "text": (
            "Ninepoint Partners LP purchased a new position in shares of Apple Inc. (NASDAQ: AAPL) "
            "in the undefined quarter, according to the company in its most recent Form 13F filing "
            "with the Securities and Exchange Commission (SEC)."
        ),
        "url": "https://www.defenseworld.net/2026/09/21/ninepoint-partners-lp.html",
    },
    {
        "symbol": "AAPL",
        "publishedDate": "2026-09-21 06:43:24",
        "publisher": "Defense World",
        "title": "PCM Encore LLC Makes New $25.31 Million Investment in Apple Inc. $AAPL",
        "site": "defenseworld.net",
        "text": (
            "PCM Encore LLC purchased a new position in shares of Apple Inc. (NASDAQ: AAPL) during "
            "the second quarter, according to the company in its most recent disclosure with the "
            "Securities and Exchange Commission."
        ),
        "url": "https://www.defenseworld.net/2026/09/21/pcm-encore-llc.html",
    },
    {
        "symbol": "AAPL",
        "publishedDate": "2026-09-21 06:43:22",
        "publisher": "Defense World",
        "title": "OVERSEA CHINESE BANKING Corp Ltd Makes New Investment in Apple Inc. $AAPL",
        "site": "defenseworld.net",
        "text": (
            "OVERSEA CHINESE BANKING Corp Ltd acquired a new stake in shares of Apple Inc. "
            "(NASDAQ: AAPL) during the second quarter, according to its most recent disclosure "
            "with the SEC."
        ),
        "url": "https://www.defenseworld.net/2026/09/21/oversea-chinese-banking-corp-ltd.html",
    },
]


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def test_filters_out_real_13f_boilerplate_articles():
    for row in REAL_13F_BLURBS:
        assert news_sources._is_institutional_filing_boilerplate(row) is True


def test_keeps_real_genuine_article():
    assert news_sources._is_institutional_filing_boilerplate(REAL_AAPL_ARTICLE) is False


def test_get_recent_news_end_to_end_filters_and_limits():
    all_rows = [REAL_AAPL_ARTICLE] + REAL_13F_BLURBS
    with patch("news_sources.requests.get", return_value=_mock_response(all_rows)), \
         patch.object(config, "NEWS_ARTICLES_PER_SYMBOL", 4):

        articles = news_sources.get_recent_news("AAPL")

    # Only the one genuine article should survive out of the five fetched.
    assert len(articles) == 1
    assert "iPhone" in articles[0]["title"]


def test_get_recent_news_fails_soft_on_error():
    with patch("news_sources.requests.get", side_effect=Exception("network error")):
        articles = news_sources.get_recent_news("AAPL")

    assert articles == []
