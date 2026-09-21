"""
Tests for scorer.py's hard exclusions (ETF/fund, negative ROE, crypto) and
for the movers-merge in stage 1 sourcing. All external data sources are
mocked — these test the pipeline's logic, not live API integration.
"""

from collections import Counter
from unittest.mock import patch

import config
import scorer


def _profile(**overrides):
    profile = {
        "symbol": "TEST", "name": "Test Co", "sector": "Technology",
        "industry": "Software", "market_cap": 1e8, "price": 10.0,
        "pe_ratio": 15.0, "roe": 0.15, "is_etf": False, "is_fund": False,
        "is_actively_trading": True, "description": "Makes software.",
        "website": "http://test.example",
    }
    profile.update(overrides)
    return profile


# --- crypto keyword/known-symbol filter -------------------------------------

def test_crypto_keyword_true_positive():
    profile = _profile(description="Operates a bitcoin mining and cryptocurrency exchange platform.")
    assert scorer._is_crypto_linked(profile) is True


def test_crypto_keyword_no_false_positive_on_cryptography():
    # "cryptography" contains the literal substring "crypto" — a naive
    # substring match would wrongly flag any encryption/security company.
    profile = _profile(description="Develops cryptography and encryption software for banks.")
    assert scorer._is_crypto_linked(profile) is False


def test_crypto_known_symbol_override():
    # MSTR's FMP profile describes it as "enterprise analytics software",
    # not crypto — the known-symbol list catches what the keyword scan can't.
    profile = _profile(symbol="MSTR", description="Enterprise analytics software company.")
    assert scorer._is_crypto_linked(profile) is True


def test_crypto_unrelated_company_not_flagged():
    profile = _profile(description="Builds quantum sensors for industrial clients.")
    assert scorer._is_crypto_linked(profile) is False


def test_crypto_digital_asset_treasury_matched():
    profile = _profile(sector="Financial Services", industry="Digital Asset Treasury",
                        description="Holds bitcoin as a treasury reserve asset.")
    assert scorer._is_crypto_linked(profile) is True


# --- full pipeline: hard exclusions ------------------------------------------

FAKE_SYMBOLS = ["GOOD", "NEGROE", "CRYPTOCO", "ETFCO", "OTHER"]

FAKE_PROFILES = {
    "GOOD": _profile(symbol="GOOD", name="Grounded Science Co", roe=0.18, price=12.0,
                      description="Makes lab equipment."),
    "NEGROE": _profile(symbol="NEGROE", name="Losing Money Inc", roe=-0.05, price=8.0,
                        description="Makes widgets at a loss."),
    "CRYPTOCO": _profile(symbol="CRYPTOCO", name="Bitcoin Treasury Holdings", roe=0.30, price=5.0,
                          sector="Financial Services", industry="Digital Asset Treasury",
                          description="Holds bitcoin as a treasury reserve asset."),
    "ETFCO": _profile(symbol="ETFCO", name="Leveraged ETF", roe=0.10, price=20.0,
                       is_etf=True, description="3x leveraged single-stock ETF."),
    "OTHER": _profile(symbol="OTHER", name="Quantum Sensing Corp", roe=0.12, price=10.0,
                       industry="Quantum Computing", description="Builds quantum sensors with proven revenue."),
}


def test_pick_top_stocks_excludes_negative_roe_crypto_and_etf():
    def fake_get_most_active_stocks(limit=None):
        return FAKE_SYMBOLS

    def fake_get_top_movers(limit=None):
        return []

    def fake_get_latest_prices(symbols):
        return {s: FAKE_PROFILES[s]["price"] for s in symbols}

    def fake_get_x_mentions(symbols):
        return Counter({s: 3 for s in symbols})

    def fake_get_momentum(symbols):
        return {s: 0.05 for s in symbols}

    def fake_get_profiles(symbols):
        return {s: dict(FAKE_PROFILES[s]) for s in symbols if s in FAKE_PROFILES}

    def fake_get_recent_news(symbol, limit=None):
        return []

    def fake_research_companies(profiles):
        return {s: {"symbol": s, "score": 0.8, "summary": "Looks fine.", "sources": []} for s in profiles}

    with patch("scorer.get_most_active_stocks", fake_get_most_active_stocks), \
         patch("scorer.get_top_movers", fake_get_top_movers), \
         patch("scorer.get_latest_prices", fake_get_latest_prices), \
         patch("scorer.get_x_mentions", fake_get_x_mentions), \
         patch("scorer.get_momentum", fake_get_momentum), \
         patch("scorer.get_profiles", fake_get_profiles), \
         patch("scorer.get_recent_news", fake_get_recent_news), \
         patch("scorer.research_companies", fake_research_companies), \
         patch.object(config, "MAX_STOCK_PRICE", 100.0), \
         patch.object(config, "SHORTLIST_SIZE", 5), \
         patch.object(config, "NUM_STOCKS", 5):

        picks = scorer.pick_top_stocks()
        picked_symbols = {p["symbol"] for p in picks}

    assert picked_symbols == {"GOOD", "OTHER"}


# --- movers merge in stage 1 --------------------------------------------------

def test_stage1_shortlist_includes_movers_not_in_actives():
    def fake_get_most_active_stocks(limit=None):
        return ["AAA", "BBB"]

    def fake_get_top_movers(limit=None):
        return ["CCC"]

    def fake_get_latest_prices(symbols):
        return {s: 10.0 for s in symbols}

    def fake_get_x_mentions(symbols):
        return Counter({s: 1 for s in symbols})

    def fake_get_momentum(symbols):
        return {s: 0.01 for s in symbols}

    with patch("scorer.get_most_active_stocks", fake_get_most_active_stocks), \
         patch("scorer.get_top_movers", fake_get_top_movers), \
         patch("scorer.get_latest_prices", fake_get_latest_prices), \
         patch("scorer.get_x_mentions", fake_get_x_mentions), \
         patch("scorer.get_momentum", fake_get_momentum), \
         patch.object(config, "MAX_STOCK_PRICE", 100.0):

        shortlist, _ = scorer._stage1_shortlist(pool_size=10, shortlist_size=10)

    assert "CCC" in shortlist


def test_stage1_shortlist_dedupes_movers_already_in_actives():
    def fake_get_most_active_stocks(limit=None):
        return ["AAA", "BBB"]

    def fake_get_top_movers(limit=None):
        return ["AAA"]  # already in most-actives — shouldn't be double-counted

    def fake_get_latest_prices(symbols):
        return {s: 10.0 for s in symbols}

    def fake_get_x_mentions(symbols):
        return Counter({s: 1 for s in symbols})

    def fake_get_momentum(symbols):
        return {s: 0.01 for s in symbols}

    with patch("scorer.get_most_active_stocks", fake_get_most_active_stocks), \
         patch("scorer.get_top_movers", fake_get_top_movers), \
         patch("scorer.get_latest_prices", side_effect=fake_get_latest_prices) as mock_prices, \
         patch("scorer.get_x_mentions", fake_get_x_mentions), \
         patch("scorer.get_momentum", fake_get_momentum), \
         patch.object(config, "MAX_STOCK_PRICE", 100.0):

        scorer._stage1_shortlist(pool_size=10, shortlist_size=10)

    # get_latest_prices should have been called with each symbol exactly once
    called_symbols = mock_prices.call_args[0][0]
    assert sorted(called_symbols) == ["AAA", "BBB"]
