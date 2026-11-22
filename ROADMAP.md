# Investment Intelligence Delivery Roadmap

The build is executed in dependency order. Deterministic calculations remain in Python; AI is reserved for research synthesis and debate. Live order execution stays disabled by default and is approval-gated.

Status reviewed in November 2026. "Scaffolded" means the code path exists and is tested, but it does not yet run on real, complete data.

| # | Milestone | Status | Notes |
|---|---|---|---|
| 1 | Real market data | PARTIAL | Yahoo Finance quote adapter (unofficial; personal research use only) with labelled demo fallback and caching. No historical prices. GSE has no feed. |
| 2 | Opportunity scanner | SCAFFOLDED | 25-asset seed universe. P/E, momentum and sentiment are static seed values, not live. |
| 3 | Fundamental engine | PARTIAL | SEC Company Facts adapter for 16 US issuers; enabled only when `SEC_USER_AGENT` declares a real contact. Others use seed values. |
| 4 | Bull-vs-bear analysis | PARTIAL | Rule-based by default; optional model synthesis when an API key is configured. |
| 5 | Investment Committee | SCAFFOLDED | Decision packet with human-approval state. "Confidence" is a heuristic distance from neutral, not a probability. |
| 6 | Portfolio analytics | SCAFFOLDED | Maths is implemented and tested; the UI shows a labelled sample portfolio until per-user holdings are stored. |
| 7 | News + macro | PARTIAL | RSS headlines are live when feeds respond; macro regime is a static rule-based label. |
| 8 | Backtesting | SCAFFOLDED | Engine works on supplied series; no historical data source connected, so nothing is shown in the UI. |
| 9 | Paper trading | SCAFFOLDED | In-memory simulated account (resets on restart); optional Alpaca paper adapter. |
| 10 | Broker integration | DISABLED BY DESIGN | Live execution is blocked. Paper-only, human approval on every order. Real-money execution would require a licensed broker partner and legal review. |

## Next steps

1. **Step 1 – honest data (done in this iteration):** removed fabricated UI content, wired the UI to the API, labelled every demo figure, fixed the GitHub Pages build and the login token bug.
2. **Step 2 – real data:** historical prices, persisted portfolios/journal/paper trades per user, live valuation inputs, licensed data provider before any commercial use.
3. **Step 3 – AI research assistant:** grounded Q&A over platform data with citations, scheduled scans and alerts, measured paper-trading track record.
4. **Before any public launch:** legal opinion on the operating model (research tool vs. advice), terms, risk disclosures, privacy policy.

## Runtime configuration

- `MARKET_DATA_MODE=live|demo`
- `FUNDAMENTALS_MODE=live|demo`
- `OPENAI_API_KEY` and optional `OPENAI_MODEL` for model-backed research synthesis
- `PAPER_BROKER_ENABLED=true` plus `ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_API_SECRET` for optional Alpaca paper execution
- `LIVE_TRADING_ENABLED=false` by default; the public build does not permit live execution
- Never commit credentials. Use deployment secrets/environment variables.

## Public safety boundary

The product is a research and decision-support system. It does not perform insider trading, market manipulation, deceptive solicitation, pump-and-dump activity, or autonomous live investment transactions.
