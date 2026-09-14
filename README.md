# Investment Intelligence

A local-first investment research and portfolio intelligence platform.

## Product vision

Research. Challenge. Quantify. Decide.

The application is designed to combine market data, fundamentals, news, macro context, quantitative signals, valuation, portfolio risk, and competing investment theses into a structured research workflow.

## Current stage

V1 foundation: application structure, market abstraction, AI research workflow, and portfolio domain model. No live trading or automated order execution is included.

## Planned markets

- Ghana Stock Exchange (GSE)
- US equities
- European equities
- ETFs / funds
- Indices
- FX
- Commodities
- Additional African exchanges through adapters

## Architecture

```text
Frontend (React + Vite)
        |
        v
Backend/API (Python + FastAPI)
        |
        +--> Market data adapters
        +--> Fundamentals
        +--> News / macro
        +--> Quantitative analytics
        +--> Valuation engine
        +--> Risk / portfolio engine
        +--> AI research agents
        |
        v
Local database (SQLite)
```

## Principles

1. Deterministic calculations stay in code.
2. AI is used for synthesis, research, debate, explanations, and unstructured information.
3. Every investment thesis must include opposing evidence and explicit invalidation conditions.
4. No secrets or API keys are committed to Git.
5. Live trading is out of scope for the initial releases; paper trading comes first.

## Getting started

The initial scaffold will be added in the first implementation commit.
