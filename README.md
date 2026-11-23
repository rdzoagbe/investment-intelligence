# Investment Intelligence

A local-first investment research and portfolio intelligence platform.

## Product vision

**Research. Challenge. Quantify. Decide.**

The product is designed as an investment research desk rather than a blind trading bot. It combines market data, fundamentals, quantitative signals, valuation, portfolio risk, news/macro context, and competing investment theses into one decision workflow.

## Data honesty rules

- Every figure in the UI shows whether it is **LIVE** or **DEMO** and where it came from.
- No values are invented when a provider fails: benchmarks show "Unavailable", and the static site shows a labelled demo dataset.
- Scores are shown as neutral bands (High score / Watch / Neutral / Low score), not buy/sell instructions.
- This is a research and education tool, not investment advice and not a broker.

## Deployments

- **GitHub Pages** (`deploy-pages.yml`): static frontend only. It has no API, so it shows the bundled demo dataset (`frontend/src/demo-snapshot.json`, regenerated with `python backend/scripts/export_demo_snapshot.py`) and skips sign-in.
- **Render** (`render.yaml`): API + frontend + PostgreSQL, with accounts. Free instances sleep and can take about a minute to wake.

## Signed-in features (API deployment)

- **Portfolio:** your own holdings, valued at current quotes, with volatility and 1-year return from daily history.
- **Investment journal:** record a decision with your thesis and a review date; the price, score and data sources at that moment are saved with it.
- **Paper trading:** a simulated 100,000 account per user, stored in the database. Fills use the server's quote, never a price sent by the browser.
- **Backtesting:** a price-only trend rule versus buy-and-hold on real history. No history means no backtest; nothing is invented.
- **AI assistant:** asks are answered only from evidence the platform gathers, with citations you can click and check. Set `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) to enable generated answers; without a key it shows the evidence only.
- **Alerts and track record:** price/score/move alerts and journal review reminders; a daily job stores score snapshots so the platform can measure whether higher scores were followed by better returns.

## Operating notes (Render)

- **Free PostgreSQL expires.** Render's free database plan is time-limited; when it expires, accounts, holdings, journals and practice trades are lost. Check the expiry date on the database page in Render and upgrade the database plan (paid) before relying on the data. Settings → "Service status" in the app shows whether the database is reachable.
- **Settings check.** The Settings page shows whether `ANTHROPIC_API_KEY`, `SEC_USER_AGENT` and `JOB_TOKEN` are set (never their values).
- **Daily snapshots** are taken automatically on the first dashboard visit after 21:30 UTC on weekdays (`DASHBOARD_DAILY_SNAPSHOT=true` by default); the GitHub `daily-scan` workflow is optional.
- **Accounts:** sign-up requires accepting the Terms, Privacy notice and Risk disclosure. These texts are **drafts and must be reviewed by a qualified lawyer before a public launch**. Users can export their data and delete their account from Settings. Logging out revokes the session token. Email addresses are not verified (no email provider is configured).
- **Rate limits** apply to sign-in, sign-up and the assistant (per IP/email/user, in memory per server process).
- After any suspected exposure, rotate `AUTH_SECRET` (signs everyone out) and `JOB_TOKEN` in Render → Environment.

## Chart overlays

Price charts can show a log-linear trend line (with a ±2σ channel when the fit is meaningful), 50/200-day moving averages, and support/resistance levels found from clustered swing highs/lows on closing prices. Each level shows its strength (number of touches) and distance from the last close. These describe past prices only; they are not forecasts or trading signals.

## Current stage — V1 + live market-data adapter

The working vertical slice includes:

- React/Vite command center connected to FastAPI, with a public demo fallback.
- Deterministic investment scanner with transparent factor scoring.
- Asset analysis endpoint with bull thesis, bear thesis, valuation scenarios, risk sizing and invalidation conditions.
- Ghana Stock Exchange, US equities, and European equities represented in the initial dataset.
- Optional live market-price adapter using the Yahoo Finance chart endpoint, with deterministic fallback when a provider is unavailable.
- Searchable opportunity table and clickable Investment Committee analysis panel.
- GitHub Actions CI for frontend build and backend compilation.

### Market data modes

The backend defaults to `MARKET_DATA_MODE=live`. It attempts to retrieve supported US/European quotes through the market-data adapter and falls back to the internal deterministic dataset if the provider is unavailable. Set `MARKET_DATA_MODE=demo` to force demo mode during development.

GSE symbols currently remain on the deterministic fallback because a supported GSE feed has not yet been configured. The adapter boundary is intentionally provider-neutral so a licensed GSE source can be added without changing scoring logic.

**Important:** a live quote is not the same as live fundamentals, news, or portfolio data. Those remain separate milestones. No broker credential or order execution is connected.

## Architecture

```text
React + Vite
    |
    v
FastAPI API
    |
    +--> Market-data adapters
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
- `GET /api/assets` — supported assets.
- `GET /api/market-data` — normalized market quotes and provider status.
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
- Live trading must remain disabled by default and require explicit human approval.
