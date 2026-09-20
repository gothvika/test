"""
Two-stage scoring, targeting cheap, lower-volume, quality-momentum stocks:

  Stage 1 (cheap, broad): pull Alpaca's active-stock pool, keep only names
  priced under MAX_STOCK_PRICE, then rank the survivors by a blend of
  (inverted) trading volume, Reddit mentions, and price momentum; keep the
  top SHORTLIST_SIZE.

  Stage 2 (deeper, narrow): for just the shortlist, pull fundamentals
  (value/CEO/sector/ROE) and run AI web-search research (CEO reputation,
  future prospects, valuation sanity check). Combine all signals into a
  final score and return the top NUM_STOCKS.
"""

import logging
import config
from data_sources import get_most_active_stocks, get_reddit_mentions, get_latest_prices, get_momentum
from fundamentals import get_profiles
from ai_research import research_companies

logger = logging.getLogger("stock_bot.scorer")


def _rank_score(ordered_items: list, item: str) -> float:
    """1.0 for best rank, decaying toward 0 for worse ranks; 0 if absent."""
    if item not in ordered_items:
        return 0.0
    idx = ordered_items.index(item)
    n = len(ordered_items)
    return (n - idx) / n


def _stage1_shortlist(pool_size: int, shortlist_size: int) -> tuple[list[str], dict]:
    volume_ranked = get_most_active_stocks(limit=pool_size)
    if not volume_ranked:
        raise RuntimeError("No candidate symbols returned from Alpaca screener.")

    prices = get_latest_prices(volume_ranked)
    candidates = [
        sym for sym in volume_ranked
        if prices.get(sym) is not None and prices[sym] < config.MAX_STOCK_PRICE
    ]
    if not candidates:
        raise RuntimeError(
            f"No candidates under ${config.MAX_STOCK_PRICE:.2f} found in today's active pool."
        )
    logger.info(
        "Price filter (<$%.2f) kept %d/%d candidates",
        config.MAX_STOCK_PRICE, len(candidates), len(volume_ranked),
    )

    mention_counts = get_reddit_mentions(candidates)
    mention_ranked = [sym for sym, _ in mention_counts.most_common()]

    momentum = get_momentum(candidates)
    momentum_ranked = sorted(candidates, key=lambda s: momentum.get(s, float("-inf")), reverse=True)

    # Smaller trading volume is preferred: Alpaca's screener orders
    # highest-volume-first, so reverse it to score the least-active of the
    # eligible candidates best. (Relative to the active pool, not an
    # absolute share-count threshold — Alpaca doesn't expose raw counts here.)
    volume_ranked_candidates = [sym for sym in volume_ranked if sym in candidates]
    smaller_volume_ranked = list(reversed(volume_ranked_candidates))

    stage1_scores = {}
    for sym in candidates:
        stage1_scores[sym] = {
            "price": prices[sym],
            "volume_score": _rank_score(smaller_volume_ranked, sym),
            "mention_score": _rank_score(mention_ranked, sym),
            "mention_count": mention_counts.get(sym, 0),
            "momentum_score": _rank_score(momentum_ranked, sym),
            "momentum_pct": momentum.get(sym),
        }

    ranked = sorted(
        candidates,
        key=lambda s: (
            stage1_scores[s]["volume_score"]
            + stage1_scores[s]["mention_score"]
            + stage1_scores[s]["momentum_score"]
        ),
        reverse=True,
    )
    shortlist = ranked[:shortlist_size]
    logger.info("Stage 1 shortlist (%d symbols): %s", len(shortlist), shortlist)
    return shortlist, stage1_scores


def pick_top_stocks(num_stocks: int = None) -> list[dict]:
    """
    Returns a list of dicts (best first), each:
      {symbol, final_score, price, volume_score, mention_score, mention_count,
       momentum_score, momentum_pct, roe, roe_score, ai_score, ai_summary}
    """
    num_stocks = num_stocks or config.NUM_STOCKS

    shortlist, stage1_scores = _stage1_shortlist(
        config.CANDIDATE_POOL_SIZE, config.SHORTLIST_SIZE
    )

    profiles = get_profiles(shortlist)
    # Drop shortlist entries we couldn't get fundamentals for — can't
    # meaningfully research "value"/"ROE"/"CEO" without a profile.
    usable_symbols = [s for s in shortlist if s in profiles]
    dropped = set(shortlist) - set(usable_symbols)
    if dropped:
        logger.warning("Dropping from shortlist (no fundamentals data): %s", dropped)

    roe_ranked = sorted(
        usable_symbols,
        key=lambda s: profiles[s].get("roe") if profiles[s].get("roe") is not None else float("-inf"),
        reverse=True,
    )

    # Feed price/momentum into the profile dict so ai_research's prompt has
    # the same numbers this stage scored on.
    for sym in usable_symbols:
        profiles[sym]["price"] = stage1_scores[sym]["price"]
        profiles[sym]["momentum_pct"] = stage1_scores[sym]["momentum_pct"]

    ai_results = research_companies({s: profiles[s] for s in usable_symbols})

    combined = []
    for sym in usable_symbols:
        s1 = stage1_scores[sym]
        roe_score = _rank_score(roe_ranked, sym)
        ai = ai_results.get(sym, {"score": 0.5, "summary": ""})
        final_score = (
            config.WEIGHT_VOLUME * s1["volume_score"]
            + config.WEIGHT_REDDIT * s1["mention_score"]
            + config.WEIGHT_MOMENTUM * s1["momentum_score"]
            + config.WEIGHT_ROE * roe_score
            + config.WEIGHT_AI_RESEARCH * ai["score"]
        )
        combined.append({
            "symbol": sym,
            "final_score": final_score,
            "price": s1["price"],
            "volume_score": s1["volume_score"],
            "mention_score": s1["mention_score"],
            "mention_count": s1["mention_count"],
            "momentum_score": s1["momentum_score"],
            "momentum_pct": s1["momentum_pct"],
            "roe": profiles[sym].get("roe"),
            "roe_score": roe_score,
            "ai_score": ai["score"],
            "ai_summary": ai["summary"],
        })

    combined.sort(key=lambda row: row["final_score"], reverse=True)
    top = combined[:num_stocks]

    logger.info("=== Final top %d picks (price < $%.2f) ===", len(top), config.MAX_STOCK_PRICE)
    for row in top:
        roe_str = f"{row['roe']:.1%}" if row["roe"] is not None else "n/a"
        momentum_str = f"{row['momentum_pct']:+.1%}" if row["momentum_pct"] is not None else "n/a"
        logger.info(
            "  %s  $%.2f  final=%.3f  vol=%.2f  reddit=%.2f(%d)  mom=%.2f(%s)  roe=%s  ai=%.2f — %s",
            row["symbol"], row["price"], row["final_score"], row["volume_score"],
            row["mention_score"], row["mention_count"], row["momentum_score"], momentum_str,
            roe_str, row["ai_score"], row["ai_summary"][:100],
        )

    return top
