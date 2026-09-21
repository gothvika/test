# Stock Bot — project reference

Automated daily stock-picking bot. Blends cheap signals (volume, X mentions,
momentum) with deeper research (fundamentals, ROE, AI-driven news research)
to pick ~10 stocks and buy $DOLLARS_PER_STOCK of each via Alpaca. Runs in
paper trading by default. This file is the standing reference for anyone
(human or Claude) picking this project back up — read it before making
changes, and update it when a decision here changes.

## Honest bottom line, read this first

The **app** is solid: well-tested, iteratively debugged against real live
APIs, sensible safety defaults. The **strategy** is unproven. A momentum-only
backtest (the one signal component that's actually testable historically)
showed a positive edge on a small, self-selected universe of prior picks,
but that edge reversed to *negative* on a broader, neutral universe of the
same size — see "Backtest results" below. Treat this as a paper-trading and
engineering project, not a validated way to make money, until real forward
performance (via `review_history.py`) says otherwise.

## Architecture

Two-stage scoring pipeline, in `scorer.py`:

- **Stage 1 (cheap, broad)**: pull Alpaca's most-actives screener AND
  today's top gainers (movers) — the movers screener exists because
  most-actives structurally can't surface a stock that's moving without
  already being high-volume. Filter to price in
  `[MIN_STOCK_PRICE, MAX_STOCK_PRICE)`. Rank by a blend of inverted volume,
  X mentions, and momentum. Keep the top `SHORTLIST_SIZE`.
- **Stage 2 (deep, narrow)**: pull fundamentals + recent news for the
  shortlist. Hard-exclude (not just down-weight): ETFs/funds/inactive
  listings, negative ROE, crypto-linked businesses (keyword regex + a
  hand-maintained known-symbol list). Run AI research (Claude + web search,
  grounded in real fetched news) on survivors. Hard-veto anything scoring
  below `MIN_AI_SCORE_THRESHOLD`. Blend the rest by configured weights, sort,
  return top `NUM_STOCKS` **and** the full scored shortlist (for later
  ranking-value analysis).

### File map

| File | Responsibility |
|---|---|
| `config.py` | All settings, read from `.env` via `python-dotenv` (`override=True`) |
| `data_sources.py` | Alpaca most-actives/movers screeners, latest prices, momentum, X mentions |
| `fundamentals.py` | FMP company profile; ROE computed manually from income+balance statements (ratios-ttm needs a paid plan) |
| `news_sources.py` | FMP news per symbol, filters out auto-generated 13F-filing boilerplate |
| `ai_research.py` | Claude + web search research, grounded in fetched news, tool-use for structured score+summary+sources |
| `scorer.py` | The pipeline above; owns all hard exclusions |
| `trader.py` | Alpaca order placement (polls for fill price), stop-loss/take-profit, positions, account |
| `main.py` | Non-interactive entrypoint (cron-friendly): picks, buys, no confirmation step |
| `app.py` + `templates/` | Interactive web UI — see below |
| `history.py` | Local JSON log, one file per day, of every report + execution |
| `review_history.py` | CLI retrospective: ranking-value check, slippage, win rate |
| `analyze_portfolio.py` | CLI live portfolio snapshot (positions, P/L, sector concentration) |
| `backtest.py` | Standalone historical backtest of the momentum signal only |
| `tests/` | pytest suite, 45 tests as of this writing, all mocked (no live network) |

### Web app (`app.py`)

Three deliberate steps, nothing automatic:
1. `/` — landing page, shows mode (PAPER/LIVE) and market status.
2. `/report` (POST) — runs the full pipeline (costs real API money: Anthropic,
   FMP, X), shows the report, logs it to `history/`.
3. `/execute` (POST) — buys the *exact* picks shown, never a re-run. The
   report's `run_id` is single-use. Refuses if market's closed or already
   ran today.

Plus `/portfolio` (live Alpaca positions + sector concentration, with a
Refresh button) and `/history` + `/history/<date>` (browse past reports,
including a live "bought vs. skipped" comparison per day).

Runs on `127.0.0.1` only, never `0.0.0.0` — it holds trading credentials and
can place real orders. A Desktop shortcut (`start_app.command`, symlinked
from `~/Desktop`) launches it and opens the browser automatically.

## Key decisions and why (avoid re-litigating these)

- **Alpaca for both data and execution.** Trading212 was evaluated as an
  alternate executor and abandoned: its API can only place orders in the
  account's primary currency, and there's no way around that for a
  GBP-primary account buying USD stocks.
- **Haiku 4.5 by default** (`ANTHROPIC_MODEL`), for cost. It doesn't support
  `output_config.effort` or the `web_search_20260209` dynamic-filtering tool
  (confirmed live: 400 "does not support programmatic tool calling") — falls
  back to `web_search_20250305` and skips `effort` when the model name
  contains "haiku".
- **X (Twitter) replaced Reddit** for social mentions — Reddit closed
  self-serve API access.
- **Crypto exclusion uses `crypto(?!graph)`**, not a plain substring match —
  a naive `"crypto" in text` check false-positives on "cryptography". A
  small hand-maintained symbol list (`KNOWN_CRYPTO_SYMBOLS` in `scorer.py`)
  catches names like MSTR/COIN/MARA whose FMP profile text doesn't
  self-describe as crypto-related.
- **`MIN_STOCK_PRICE` (default $2.00) added after live testing** — the
  movers screener's real "top gainers" were mostly sub-$1 penny
  stocks/warrants with huge but illiquid-noise swings (a warrant at $0.007
  "up 2967%"). Was not previously filtered.
- **News source is FMP, not Yahoo Finance** — Yahoo has no official public
  API; the unofficial scraping libraries are fragile and ToS-questionable.
  FMP was already integrated. Its feed turned out to be ~80% auto-generated
  13F-filing blurbs ("Fund X bought $Y of shares"), filtered out by
  `news_sources._is_institutional_filing_boilerplate`.
- **Stop-loss defaults to -20%, always active; take-profit defaults to
  disabled (0)** — the bot originally had no sell logic at all. Take-profit
  is opt-in so it doesn't impose a "sell winners early" philosophy nobody
  asked for.
- **`DOLLARS_PER_STOCK` is $2.00**, bumped from the original $1.00.
- **`pick_top_stocks()` returns `(top, full_shortlist)`**, not just `top` —
  needed so the full pre-truncation shortlist can be logged and later
  compared against what actually got bought (see "Evaluation" below). This
  is a breaking signature change from earlier in the project's history; all
  callers (`main.py`, `app.py`) and tests are updated.
- **Order fills are polled** (`trader._wait_for_fill`, up to 3x, 1s apart) —
  the initial `POST /v2/orders` response often lacks `filled_avg_price`, and
  that price is needed to measure real slippage against what the pipeline
  scored on.

## Backtest results (2026-09-21)

`backtest.py` replays *only* the momentum signal (rank by trailing N-day
return, buy top-K, hold, measure) against real historical Alpaca bars — the
one component that's honestly reproducible without look-ahead bias. It
cannot and does not test the AI research score (largest weight, 0.35),
volume/movers sourcing (Alpaca's screener is a live snapshot, not
time-travelable), X mentions (no archive), or ROE (would need point-in-time
fundamentals).

- **First run**, symbols drawn from a prior live picks list (already
  selection-biased toward recent movers): +3.93% edge vs. equal-weight
  benchmark, 57% win rate over 23 cycles — but ~half of that edge came from
  one outlier cycle (+64.94% on KEEL/PLUG/CDE).
- **Second run**, a fresh, sector-diverse, non-cherry-picked universe of 31
  symbols, same period/parameters: **-1.15% edge, 48% win rate** — the edge
  reversed. Not dominated by a single outlier.
- **Conclusion**: the first result was very likely selection bias (testing
  "does momentum predict returns" on stocks already selected for having
  moved recently is close to circular). On a neutral universe, momentum
  alone showed no edge, arguably a small negative one. This is real evidence
  against the momentum component specifically, and a reason for general
  skepticism about the whole pipeline, not a verdict on it (the AI research
  weight — the largest one — remains untested).

Don't re-run the backtest with tweaked parameters chasing a positive result
— that's p-hacking, not validation. If revisiting, the honest next step is
point-in-time ROE data or a longer/different neutral universe, not
parameter search.

## Current evaluation: the 2-week trial

Plan (started 2026-09-21): generate a report via the web app most weekdays
during market hours, optionally execute, let `history.py` log everything
automatically. At the end (or anytime), run `review_history.py` for:

- Average AI score, most-picked symbols, stop-loss/take-profit actions.
- **Ranking-value check**: hypothetical return of top-N (bought) vs. rest of
  that day's shortlist (skipped) — the direct answer to "did the AI ranking
  do anything," using `full_shortlist` data.
- **Execution slippage**: filled price vs. the price the pipeline scored on.
- Real win rate / avg return on whatever was actually bought, via live
  current prices from Alpaca (not the unvalidated backtest).

`analyze_portfolio.py` (or `/portfolio` in the web app) gives a live
account-truth snapshot anytime, independent of the log-based review —
useful because it correctly aggregates multiple buys of the same symbol via
Alpaca's own qty/avg_entry_price, which reconstructing from logs would not
handle as cleanly.

## Known gaps / things not yet done

- No diversification or position-sizing logic beyond the sector-concentration
  *warning* on `/portfolio` — it flags, doesn't prevent.
- No retry/backoff on transient API failures (single 15s timeout per call).
- Bid-ask spread on illiquid, low-price names is now measurable (slippage
  tracking) but not yet analyzed with real data.
- ROE-aware backtesting would need point-in-time fundamentals to avoid
  look-ahead bias; not implemented.
- Several live integrations were implemented to documented API schemas but
  needed live correction once actually run (FMP `/stable/` migration, ROE
  computed manually since `ratios-ttm` needs a paid plan, Alpaca `feed=iex`
  for data). When adding a new external endpoint, assume the same will
  happen and say so explicitly rather than presenting it as verified.

## Running things

```bash
# one-time
pip3 install -r requirements.txt        # add requirements-dev.txt for pytest

# daily use
python3 app.py                          # web UI at http://127.0.0.1:5000
python3 main.py                         # non-interactive (cron), no confirm step
python3 preview_picks.py                # picks only, no orders, no market-hours check
                                         # (not committed to the repo — a local-only script
                                         #  the user keeps on their machine; recreate if needed:
                                         #  calls scorer.pick_top_stocks() directly)

# review
python3 review_history.py               # retrospective over everything in history/
python3 analyze_portfolio.py            # live account snapshot

# one-off live verification of an external API (pattern to follow for new ones)
python3 test_fmp_news.py AAPL
python3 test_alpaca_movers.py
python3 test_alpaca_positions.py

# backtest (momentum only — read the caveats in backtest.py's docstring)
python3 backtest.py --symbols A,B,C --start YYYY-MM-DD --end YYYY-MM-DD

# tests
python3 -m pytest tests/ -v
```

`ALPACA_PAPER=true` in `.env` keeps everything on paper trading (default).
Never flip to `false` without the user explicitly, deliberately choosing to.

## Working conventions on this project

- **Verify live integrations before trusting them.** This codebase has a
  established pattern: write a small standalone `test_<service>_<thing>.py`
  script that prints the raw response, ask the user to run it locally
  (most external APIs are network-blocked from the sandbox this was
  developed in), then fix parsing against the real response shape. Don't
  assume a documented schema is correct.
- **Hard exclusions over down-weighting** for anything that makes a pick
  categorically wrong (ETF, negative ROE, crypto-linked, AI red flag) —
  blending only makes sense for ordinary quality tradeoffs.
- **Don't add features speculatively.** Every addition in this project so
  far was in direct response to a specific, named gap or a live bug — keep
  it that way.
- **Never claim something works without evidence.** This file's "honest
  bottom line" section exists because the user explicitly asked for and
  acted on unflinching critique multiple times over this project's life —
  keep giving it.
