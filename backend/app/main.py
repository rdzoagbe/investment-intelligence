from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .data import ASSETS
from .engine import analyze_asset, scanner
from .market_data import live_quotes, market_data_status

app = FastAPI(title="Investment Intelligence API", version="0.4.0")

cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True, allow_methods=["GET"], allow_headers=["*"])


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "investment-intelligence-api", "version": app.version}


@app.get("/api/assets")
def assets() -> list[dict[str, str]]:
    return [{"symbol": a.symbol, "name": a.name, "market": a.market, "currency": a.currency} for a in ASSETS]


@app.get("/api/market-data")
def market_data() -> dict[str, object]:
    return {"quotes": live_quotes(), "status": market_data_status()}


@app.get("/api/scanner")
def investment_scanner(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    market: str | None = Query(default=None),
    verdict: str | None = Query(default=None),
    min_score: float = Query(default=0, ge=0, le=100),
) -> dict[str, object]:
    ranked = scanner(100)
    if market:
        ranked = [item for item in ranked if str(item["market"]).lower() == market.strip().lower()]
    if verdict:
        ranked = [item for item in ranked if str(item["verdict"]).upper() == verdict.strip().upper()]
    ranked = [item for item in ranked if float(item["score"]) >= min_score]
    page = ranked[offset:offset + limit]
    return {"items": page, "total": len(ranked), "offset": offset, "limit": limit}


@app.get("/api/assets/{symbol}/analysis")
def asset_analysis(symbol: str) -> dict[str, object]:
    result = analyze_asset(symbol)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Asset {symbol.upper()} not found")
    return result


@app.get("/api/dashboard")
def dashboard() -> dict[str, object]:
    ranked = scanner(5)
    top = ranked[0]
    quotes = live_quotes()
    live_by_symbol = {q["symbol"]: q for q in quotes if q["status"] == "LIVE"}
    markets = [
        {"name": "S&P 500", "value": 5842, "change_pct": 0.72},
        {"name": "NASDAQ", "value": 18771, "change_pct": 0.91},
        {"name": "DAX", "value": 23456, "change_pct": 0.48},
        {"name": "EUR/USD", "value": 1.102, "change_pct": 0.18},
        {"name": "Gold", "value": 2534, "change_pct": 0.36},
    ]
    return {
        "portfolio": {"value": 12450, "total_return_pct": 12.4, "benchmark_return_pct": 9.8, "risk_level": "Moderate", "volatility_pct": 14.8, "cash_pct": 17.0, "cash_value": 2117},
        "markets": markets,
        "scanner": ranked,
        "market_quotes": quotes,
        "scanner_meta": {"universe_size": len(ASSETS), "live_price_coverage": len(live_by_symbol)},
        "committee": {"symbol": top["symbol"], "verdict": top["verdict"], "score": top["score"], "question": "What does the market already know that this score may be missing?"},
        "insights": [
            {"type": "MACRO", "text": "Central-bank expectations remain a key driver for long-duration growth assets."},
            {"type": "SECTOR", "text": "AI infrastructure demand continues to influence semiconductor and cloud valuations."},
            {"type": "RISK", "text": "The scanner separates deterministic scoring from narrative analysis so assumptions remain inspectable."},
        ],
        "data_status": "LIVE_MARKET_DATA" if live_by_symbol else "DEMO_DATASET",
    }
