from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .data import ASSETS
from .engine import analyze_asset, scanner

app = FastAPI(title="Investment Intelligence API", version="0.2.0")

cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "investment-intelligence-api", "version": app.version}


@app.get("/api/assets")
def assets() -> list[dict[str, str]]:
    return [
        {
            "symbol": asset.symbol,
            "name": asset.name,
            "market": asset.market,
            "currency": asset.currency,
        }
        for asset in ASSETS
    ]


@app.get("/api/scanner")
def investment_scanner(limit: int = Query(default=5, ge=1, le=20)) -> list[dict[str, object]]:
    return scanner(limit)


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
    return {
        "portfolio": {
            "value": 12450,
            "total_return_pct": 12.4,
            "benchmark_return_pct": 9.8,
            "risk_level": "Moderate",
            "volatility_pct": 14.8,
            "cash_pct": 17.0,
            "cash_value": 2117,
        },
        "markets": [
            {"name": "S&P 500", "value": 5842, "change_pct": 0.72},
            {"name": "NASDAQ", "value": 18771, "change_pct": 0.91},
            {"name": "DAX", "value": 23456, "change_pct": 0.48},
            {"name": "EUR/USD", "value": 1.102, "change_pct": 0.18},
            {"name": "Gold", "value": 2534, "change_pct": 0.36},
        ],
        "scanner": ranked,
        "committee": {
            "symbol": top["symbol"],
            "verdict": top["verdict"],
            "score": top["score"],
            "question": "What does the market already know that this score may be missing?",
        },
        "insights": [
            {"type": "MACRO", "text": "Central-bank expectations remain a key driver for long-duration growth assets."},
            {"type": "SECTOR", "text": "AI infrastructure demand continues to influence semiconductor and cloud valuations."},
            {"type": "RISK", "text": "The scanner separates deterministic scoring from narrative analysis so assumptions remain inspectable."},
        ],
        "data_status": "DEMO_DATASET",
    }
