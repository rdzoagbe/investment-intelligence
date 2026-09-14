# Investment Intelligence Delivery Roadmap

The build is executed in dependency order. Deterministic calculations remain in Python; AI is reserved for research synthesis and debate. Live order execution stays disabled by default and is approval-gated.

| # | Milestone | Status | Notes |
|---|---|---|---|
| 1 | Real market data | COMPLETE | Live Yahoo quote adapter with deterministic fallback; provider boundary isolated and GSE remains pluggable. |
| 2 | Opportunity scanner at meaningful scale | COMPLETE | 25-asset seed universe, ranked scanner, pagination and market/verdict/score filters. |
| 3 | Fundamental engine | COMPLETE | SEC Company Facts adapter plus normalized revenue, margins, FCF, EPS, debt, cash and deterministic fallback. |
| 4 | Bull-vs-bear AI analysis | COMPLETE | Evidence-based bull/bear boundary with optional OpenAI Responses API synthesis; deterministic fallback when no key is configured. |
| 5 | Investment Committee | COMPLETE | Formal decision packet with score, confidence, valuation, risk, approval state and decision challenge. |
| 6 | Portfolio analytics | COMPLETE | Holdings, allocation, P&L, cash, alpha, concentration flags, volatility, Sharpe and drawdown endpoints. |
| 7 | News + macro intelligence | COMPLETE | RSS normalization, SEC/news feed ingestion and macro regime/driver layer with source traceability. |
| 8 | Backtesting | COMPLETE | Deterministic signal replay with position sizing, transaction costs, equity curve, return and drawdown. |
| 9 | Paper trading | COMPLETE | Simulated account, fills, positions and audit journal; optional Alpaca paper broker adapter. |
| 10 | Broker integration | COMPLETE-SAFETY-GATED | Alpaca paper adapter is implemented. Live execution remains disabled in the public build and every broker order requires explicit human approval. |

## Runtime configuration

- `MARKET_DATA_MODE=live|demo`
- `FUNDAMENTALS_MODE=live|demo`
- `OPENAI_API_KEY` and optional `OPENAI_MODEL` for model-backed research synthesis
- `PAPER_BROKER_ENABLED=true` plus `ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_API_SECRET` for optional Alpaca paper execution
- `LIVE_TRADING_ENABLED=false` by default; the public build does not permit live execution
- Never commit credentials. Use deployment secrets/environment variables.

## Public safety boundary

The product is a research and decision-support system. It does not perform insider trading, market manipulation, deceptive solicitation, pump-and-dump activity, or autonomous live investment transactions.
