"""
Uses the Claude API (with web search) to research each shortlisted company:
recent news, CEO track record/reputation, and forward-looking prospects —
combined with the fundamentals pulled from fundamentals.py — and asks for a
single 0-1 suitability score plus a short written rationale.

This is a heuristic research assistant, not investment advice. Its scores
are opinions synthesized from public web content, not guarantees.
"""

import json
import logging
import re

import anthropic
import config

logger = logging.getLogger("stock_bot.ai_research")

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


PROMPT_TEMPLATE = """You are helping evaluate a stock for a small, automated \
daily $1 purchase (part of a diversified basket of 10 stocks, not a large bet).

Company: {name} ({symbol})
Sector / industry: {sector} / {industry}
Market cap: {market_cap}
P/E ratio: {pe_ratio}
Business description: {description}

Please research using web search:
1. The current CEO's track record and reputation (tenure, past results, any \
recent controversies).
2. The company's near-to-medium-term prospects (recent earnings trends, \
guidance, major news in the last 1-3 months, competitive position).
3. Whether the current valuation looks reasonable, stretched, or cheap \
relative to the sector, given what you find.

Then respond with ONLY a JSON object (no other text, no markdown fences):
{{
  "score": <float 0.0 to 1.0, where 1.0 = strong CEO + strong prospects + \
reasonable valuation, 0.0 = significant red flags on any of those fronts>,
  "summary": "<2-3 sentence plain-English rationale citing what you found>"
}}
"""


def research_company(profile: dict) -> dict:
    """
    Runs one company through Claude + web search. Returns
    {"symbol": ..., "score": float, "summary": str}. On failure, returns a
    neutral score of 0.5 with an explanatory summary rather than crashing
    the whole daily run over one bad lookup.
    """
    symbol = profile["symbol"]
    prompt = PROMPT_TEMPLATE.format(
        name=profile.get("name") or symbol,
        symbol=symbol,
        sector=profile.get("sector") or "unknown",
        industry=profile.get("industry") or "unknown",
        market_cap=profile.get("market_cap") or "unknown",
        pe_ratio=profile.get("pe_ratio") or "unknown",
        description=(profile.get("description") or "")[:600],
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1024,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )

        text_parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        full_text = "\n".join(text_parts).strip()

        # Model may wrap JSON in fences despite instructions; strip if present.
        cleaned = re.sub(r"^```json|```$", "", full_text.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(cleaned)

        score = float(parsed.get("score", 0.5))
        score = max(0.0, min(1.0, score))  # clamp
        summary = str(parsed.get("summary", "")).strip()

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
