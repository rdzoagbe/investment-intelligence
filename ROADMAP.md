# Investment Intelligence Delivery Roadmap

The build is executed in dependency order. Deterministic calculations remain in Python; AI is reserved for research synthesis and debate. Live order execution stays disabled by default and is approval-gated.

Status reviewed in November 2026. "Scaffolded" means the code path exists and is tested, but it does not yet run on real, complete data.

| # | Milestone | Status | Notes |
|---|---|---|---|
| 1 | Real market data | PARTIAL | Quotes and daily adjusted-close history (1y–10y) from the Yahoo Finance chart API (unofficial; personal research use only), cached, with labelled demo fallback. No history is ever synthesised. GSE has no feed. |
| 2 | Opportunity scanner | PARTIAL | 25-asset universe. Momentum comes from live history (12-1 month momentum + 200-day trend) when available; P/E is live price / SEC diluted EPS for US issuers when both are live; sentiment is still a seed value. Each input reports its source. |
| 3 | Fundamental engine | PARTIAL | SEC Company Facts adapter for 16 US issuers, enabled only when `SEC_USER_AGENT` declares a real contact. Fixed: values are keyed by reporting period (10-K comparatives no longer mixed up), EPS is read from per-share units, and the freshest revenue tag wins. Non-US issuers use seed values. |
| 4 | Bull-vs-bear analysis | PARTIAL | Rule-based by default; optional model synthesis when an API key is configured. |
| 5 | Investment Committee | SCAFFOLDED | Decision packet with human-approval state. "Confidence" is a heuristic distance from neutral, not a probability. |
| 6 | Portfolio analytics | PARTIAL | Signed-in users store their own holdings, valued at current quotes with per-holding volatility/return from live history. Totals are per currency (no FX conversion yet). |
| 7 | News + macro | PARTIAL | RSS headlines are live when feeds respond; macro regime is a static rule-based label. |
| 8 | Backtesting | PARTIAL | Price-only trend rule vs buy-and-hold on real history, with costs, CAGR and drawdown; tested for no look-ahead. The composite score is deliberately not backtested (its fundamentals are not point-in-time). |
| 9 | Paper trading | PARTIAL | Per-user simulated account persisted in the database; fills always use the server's quote and record LIVE/DEMO. Single cash balance, no FX. |
| 11 | Investment journal | PARTIAL | Per-user decisions with thesis, review date, outcome and an evidence snapshot (price, score, sources) captured at decision time. |
| 12 | Research assistant | PARTIAL | Answers only from platform evidence (quotes, scores, history, the user's own holdings and journal) with [E#] citations that are validated; invented citations are removed and uncited answers flagged. Claude (`ANTHROPIC_API_KEY`) or OpenAI; without a key it lists the evidence only. Daily per-user limit. Never gives buy/sell instructions. |
| 13 | Alerts | PARTIAL | Price, score and daily-move rules plus due journal reviews; price alerts fire only on LIVE quotes; 20-hour cooldown; in-app notifications (no email yet). |
| 14 | Track record | PARTIAL | Daily score snapshots (via the token-protected daily job) measure forward returns by score band, reported as insufficient until enough data exists; per-user paper P&L, win rate and journal hit rate. |
| 10 | Broker integration | DISABLED BY DESIGN | Live execution is blocked. Paper-only, human approval on every order. Real-money execution would require a licensed broker partner and legal review. |

## Next steps

1. **Step 1 – honest data (done in this iteration):** removed fabricated UI content, wired the UI to the API, labelled every demo figure, fixed the GitHub Pages build and the login token bug.
2. **Step 2 – real data (done in this iteration):** historical prices, live momentum and P/E inputs, SEC parsing fixes, persisted per-user holdings, journal and paper trades, real-history backtests.
   Still open: FX conversion, a licensed market-data provider before any commercial use (the Yahoo endpoint is unofficial), a sentiment source, GSE data, point-in-time fundamentals.
3. **Step 3 – AI research assistant (done in this iteration):** grounded Q&A with validated citations, alerts, daily snapshots and track records.
   Still open: email/push notifications, news/filings as assistant evidence (needs prompt-injection handling for third-party text), several months of snapshots before the signal track record means anything.
4. **Before any public launch:** legal opinion on the operating model (research tool vs. advice), terms, risk disclosures, privacy policy.

## Runtime configuration

- `MARKET_DATA_MODE=live|demo`
- `FUNDAMENTALS_MODE=live|demo`
- `ANTHROPIC_API_KEY` (optional `ANTHROPIC_MODEL`, default `claude-opus-5-5`; `ASSISTANT_EFFORT`, default `high`) or `OPENAI_API_KEY` (optional `OPENAI_MODEL`) for the research assistant; `ASSISTANT_PROVIDER=anthropic|openai|none` to force one; `ASSISTANT_DAILY_LIMIT` (default 20)
- `JOB_TOKEN` (24+ characters) enables `POST /api/jobs/daily-scan`; the `daily-scan` GitHub workflow calls it when the `SCAN_URL` and `JOB_TOKEN` repository secrets are set
- `PAPER_BROKER_ENABLED=true` plus `ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_API_SECRET` for optional Alpaca paper execution
- `LIVE_TRADING_ENABLED=false` by default; the public build does not permit live execution
- Never commit credentials. Use deployment secrets/environment variables.

## Public safety boundary

The product is a research and decision-support system. It does not perform insider trading, market manipulation, deceptive solicitation, pump-and-dump activity, or autonomous live investment transactions.
