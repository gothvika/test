"""
Two-stage scoring:

  Stage 1 (cheap, broad): rank the full candidate pool by a blend of trading
  volume and Reddit mentions; keep the top SHORTLIST_SIZE.

  Stage 2 (deeper, narrow): for just the shortlist, pull fundamentals
  (value/CEO/sector) and run AI web-search research (CEO reputation, future
  prospects, valuation sanity check). Combine all signals into a final score
  and return the top NUM_STOCKS.
"""

import logging
import config
from data_sources import get_most_active_stocks, get_reddit_mentions
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

    mention_counts = get_reddit_mentions(volume_ranked)
    mention_ranked = [sym for sym, _ in mention_counts.most_common()]

    stage1_scores = {}
    for sym in volume_ranked:
        vol_score = _rank_score(volume_ranked, sym)
        mention_score = _rank_score(mention_ranked, sym)
        stage1_scores[sym] = {
            "volume_score": vol_score,
            "mention_score": mention_score,
            "mention_count": mention_counts.get(sym, 0),
        }

    ranked = sorted(
        volume_ranked,
        key=lambda s: (stage1_scores[s]["volume_score"] + stage1_scores[s]["mention_score"]),
        reverse=True,
    )
    shortlist = ranked[:shortlist_size]
    logger.info("Stage 1 shortlist (%d symbols): %s", len(shortlist), shortlist)
    return shortlist, stage1_scores


def pick_top_stocks(num_stocks: int = None) -> list[dict]:
    """
    Returns a list of dicts (best first), each:
      {symbol, final_score, volume_score, mention_score, ai_score, ai_summary}
    """
    num_stocks = num_stocks or config.NUM_STOCKS

    shortlist, stage1_scores = _stage1_shortlist(
        config.CANDIDATE_POOL_SIZE, config.SHORTLIST_SIZE
    )

    profiles = get_profiles(shortlist)
    # Drop shortlist entries we couldn't get fundamentals for — can't
    # meaningfully research "value" or "CEO" without a profile.
    usable_symbols = [s for s in shortlist if s in profiles]
    dropped = set(shortlist) - set(usable_symbols)
    if dropped:
        logger.warning("Dropping from shortlist (no fundamentals data): %s", dropped)

    ai_results = research_companies({s: profiles[s] for s in usable_symbols})

    combined = []
    for sym in usable_symbols:
        s1 = stage1_scores[sym]
        ai = ai_results.get(sym, {"score": 0.5, "summary": ""})
        final_score = (
            config.WEIGHT_VOLUME * s1["volume_score"]
            + config.WEIGHT_REDDIT * s1["mention_score"]
            + config.WEIGHT_AI_RESEARCH * ai["score"]
        )
        combined.append({
            "symbol": sym,
            "final_score": final_score,
            "volume_score": s1["volume_score"],
            "mention_score": s1["mention_score"],
            "mention_count": s1["mention_count"],
            "ai_score": ai["score"],
            "ai_summary": ai["summary"],
        })

    combined.sort(key=lambda row: row["final_score"], reverse=True)
    top = combined[:num_stocks]

    logger.info("=== Final top %d picks ===", len(top))
    for row in top:
        logger.info(
            "  %s  final=%.3f  volume=%.2f  reddit=%.2f(%d)  ai=%.2f  — %s",
            row["symbol"], row["final_score"], row["volume_score"],
            row["mention_score"], row["mention_count"], row["ai_score"],
            row["ai_summary"][:120],
        )

    return top
