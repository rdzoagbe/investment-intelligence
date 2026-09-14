# Investment Intelligence

A local-first investment research and portfolio intelligence platform.

## Product vision

**Research. Challenge. Quantify. Decide.**

The product is designed as an investment research desk rather than a blind trading bot. It combines market data, fundamentals, quantitative signals, valuation, portfolio risk, news/macro context, and competing investment theses into one decision workflow.

## Current stage — V1 working engine

The first working vertical slice is now in place:

- React/Vite command center connected to FastAPI.
- Deterministic investment scanner with transparent factor scoring.
- Asset analysis endpoint with bull thesis, bear thesis, risks, and invalidation conditions.
- Ghana Stock Exchange, US equities, and European equities represented in the initial dataset.
- Searchable opportunity table and clickable Investment Committee analysis panel.
- GitHub Actions CI for frontend build and backend compilation.

**Important:** current values are a deterministic demo dataset. No live market feed, broker credential, or order execution is connected.

## Architecture

```text
React + Vite
    |
    v
FastAPI API
    |
    +--> Asset / market adapters
    +--> Quant & scoring engine
    +--> Valuation engine
    +--> Risk / portfolio engine
    +--> News / macro intelligence
    +--> AI research agents
    |
    v
SQLite / persistent portfolio data
```

## Investment workflow

```text
SCAN
  -> SCORE
  -> FUNDAMENTAL REVIEW
  -> BULL vs BEAR CHALLENGE
  -> VALUATION
  -> RISK CHECK
  -> INVESTMENT COMMITTEE
  -> HUMAN DECISION
```

The architecture deliberately keeps deterministic calculations in code and reserves AI for synthesis, research, debate, explanations, and unstructured information.

## API

Run the backend from `backend/`:

```bash
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Useful endpoints:

- `GET /api/health` — service health.
- `GET /api/assets` — supported demo assets.
- `GET /api/scanner` — ranked opportunities.
- `GET /api/assets/{symbol}/analysis` — investment committee analysis.
- `GET /api/dashboard` — command-center payload.

## Frontend

Run the frontend from `frontend/`:

```bash
npm install
npm run dev
```

By default the frontend calls `http://localhost:8000`. Set `VITE_API_BASE_URL` when the API is hosted elsewhere.

## Planned markets

Ghana Stock Exchange (GSE), US equities, European equities, ETFs/funds, indices, FX, commodities, and additional African exchanges through adapters.

## Security principles

- Never commit API keys, broker credentials, or personal portfolio secrets.
- Keep secrets server-side.
- Use least-privilege credentials for CI and integrations.
- Validate market data before it reaches scoring or portfolio logic.
- Paper trading and backtesting precede any future broker integration.
