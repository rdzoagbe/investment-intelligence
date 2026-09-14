# Investment Intelligence Delivery Roadmap

The build is executed in dependency order. Deterministic calculations remain in Python; AI is reserved for research synthesis and debate. Live order execution stays disabled until explicit human approval is implemented and tested.

| # | Milestone | Status | Notes |
|---|---|---|---|
| 1 | Real market data | IN PROGRESS | Live quote adapter is implemented for supported US/EU symbols with deterministic fallback; GSE provider still needs a supported feed. |
| 2 | Opportunity scanner at meaningful scale | NEXT | Expand universe/provider coverage and ranking pipeline. |
| 3 | Fundamental engine | PARTIAL | Deterministic factor scoring exists; expand normalized financial statements and quality metrics. |
| 4 | Bull-vs-bear AI analysis | PARTIAL | Deterministic thesis scaffold exists; add model-backed evidence synthesis with source traceability. |
| 5 | Investment Committee | PARTIAL | Committee view exists; formalize decision packet, confidence and approval state. |
| 6 | Portfolio analytics | PARTIAL | Risk sizing exists; add holdings, allocation, P&L, exposure and concentration analytics. |
| 7 | News + macro intelligence | NOT STARTED | Add source ingestion, event normalization and market-impact summaries. |
| 8 | Backtesting | NOT STARTED | Historical data, signal replay, costs, drawdown and benchmark comparison. |
| 9 | Paper trading | NOT STARTED | Simulated orders, fills, positions and audit journal. |
| 10 | Broker integration | NOT STARTED | Adapter architecture only; live trading disabled by default and every live order requires explicit human approval. |

## Current implementation note

Milestone 1 introduces `backend/app/market_data.py` and `GET /api/market-data`. The provider boundary is deliberately isolated from the scoring engine so a licensed provider can replace the current quote source without changing investment logic.
