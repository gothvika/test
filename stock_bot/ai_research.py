"""
Uses the Claude API (with web search) to research each shortlisted company:
recent news, CEO track record/reputation, and forward-looking prospects —
combined with the fundamentals pulled from fundamentals.py — and asks for a
single 0-1 suitability score plus a short written rationale.

This is a heuristic research assistant, not investment advice. Its scores
are opinions synthesized from public web content, not guarantees.
"""

import logging

import anthropic
import config

logger = logging.getLogger("stock_bot.ai_research")

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


# Claude sometimes doesn't fully close out a plain-text "respond with only
# JSON" answer after a web-search turn (observed live: valid schema, no
# max_tokens cutoff, just an incomplete trailing string). Using tool-use for
# the final answer instead has the API enforce the schema, which avoids
# that failure mode entirely.
SUBMIT_RESULT_TOOL = {
    "name": "submit_research_result",
    "description": "Submit your final suitability assessment for this stock, once you've finished researching.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {
                "type": "number",
                "description": (
                    "0.0 to 1.0, where 1.0 = strong CEO + strong prospects + "
                    "reasonable valuation, 0.0 = significant red flags on any of those fronts."
                ),
            },
            "summary": {
                "type": "string",
                "description": "2-3 sentence plain-English rationale citing what you found.",
            },
        },
        "required": ["score", "summary"],
    },
}

PROMPT_TEMPLATE = """You are helping evaluate a stock for a small, automated \
daily $1 purchase (part of a diversified basket of 10 stocks, not a large bet). \
This bot specifically targets lower-priced, lower-volume stocks with strong \
return on equity and positive price momentum.

Company: {name} ({symbol})
Sector / industry: {sector} / {industry}
Market cap: {market_cap}
Current price: {price}
P/E ratio: {pe_ratio}
Return on equity (TTM): {roe}
Trailing price momentum ({momentum_days}-day): {momentum_pct}
Business description: {description}

Please research using web search:
1. The current CEO's track record and reputation (tenure, past results, any \
recent controversies).
2. The company's near-to-medium-term prospects (recent earnings trends, \
guidance, major news in the last 1-3 months, competitive position).
3. Whether the current valuation looks reasonable, stretched, or cheap \
relative to the sector, given what you find.

When you're done researching, call submit_research_result with your final \
score and summary — don't just write the answer out as text.
"""


def research_company(profile: dict) -> dict:
    """
    Runs one company through Claude + web search. Returns
    {"symbol": ..., "score": float, "summary": str}. On failure, returns a
    neutral score of 0.5 with an explanatory summary rather than crashing
    the whole daily run over one bad lookup.
    """
    symbol = profile["symbol"]
    roe = profile.get("roe")
    momentum_pct = profile.get("momentum_pct")
    prompt = PROMPT_TEMPLATE.format(
        name=profile.get("name") or symbol,
        symbol=symbol,
        sector=profile.get("sector") or "unknown",
        industry=profile.get("industry") or "unknown",
        market_cap=profile.get("market_cap") or "unknown",
        price=profile.get("price") or "unknown",
        pe_ratio=profile.get("pe_ratio") or "unknown",
        roe=f"{roe:.1%}" if roe is not None else "unknown",
        momentum_days=config.MOMENTUM_LOOKBACK_DAYS,
        momentum_pct=f"{momentum_pct:+.1%}" if momentum_pct is not None else "unknown",
        description=(profile.get("description") or "")[:600],
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2048,
            # effort="medium" cuts cost ~15-30% on research/knowledge-shaped
            # tasks like this one, per Anthropic's published effort-sweep
            # results, without a measurable accuracy hit.
            output_config={"effort": "medium"},
            tools=[
                # _20260209 has built-in dynamic filtering, which strips
                # boilerplate from search results before they enter context —
                # directly targets this call's dominant cost (~22k input
                # tokens/call observed, almost all from search results).
                # max_uses caps runaway search chains on any one call.
                {"type": "web_search_20260209", "name": "web_search", "max_uses": 3},
                SUBMIT_RESULT_TOOL,
            ],
            messages=[{"role": "user", "content": prompt}],
        )

        result_block = next(
            (
                b for b in response.content
                if getattr(b, "type", None) == "tool_use" and b.name == "submit_research_result"
            ),
            None,
        )
        if result_block is None:
            raise ValueError(
                f"Model never called submit_research_result (stop_reason={response.stop_reason})"
            )

        score = float(result_block.input.get("score", 0.5))
        score = max(0.0, min(1.0, score))  # clamp
        summary = str(result_block.input.get("summary", "")).strip()

        logger.info("AI research for %s: score=%.2f — %s", symbol, score, summary)
        return {"symbol": symbol, "score": score, "summary": summary}

    except Exception as exc:
        logger.warning("AI research failed for %s: %s. Using neutral score.", symbol, exc)
        return {"symbol": symbol, "score": 0.5, "summary": f"Research unavailable: {exc}"}


def research_companies(profiles: dict[str, dict]) -> dict[str, dict]:
    """Runs research_company for each profile. Sequential — simple and easy to rate-limit."""
    results = {}
    for symbol, profile in profiles.items():
        results[symbol] = research_company(profile)
    return results
