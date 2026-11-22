from __future__ import annotations

import os
import time
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .auth import authenticate, create_user, issue_token, user_from_token
from .backtest import BacktestConfig, run_backtest
from .broker import gateway
from .committee import build_committee
from .data import ASSETS, get_asset
from .engine import analyze_asset, scanner
from .fundamentals import fundamentals_for_symbol, sec_user_agent
from .intelligence import bull_bear, macro_snapshot, market_intelligence
from .market_data import index_quotes, live_quotes, market_data_status
from .paper_trading import paper_account
from .portfolio import Holding, portfolio_snapshot, risk_metrics

app = FastAPI(title="Investment Intelligence API", version="1.2.0")
cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["*"])

class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
class BacktestRequest(BaseModel):
    prices: list[float] = Field(min_length=2); scores: list[float] = Field(min_length=2)
    initial_cash: float = Field(default=10000, gt=0); position_pct: float = Field(default=0.20, gt=0, le=1)
    buy_threshold: float = Field(default=85, ge=0, le=100); sell_threshold: float = Field(default=60, ge=0, le=100); transaction_cost_bps: float = Field(default=10, ge=0, le=1000)
class PaperOrder(BaseModel):
    symbol: str; side: str; quantity: float = Field(gt=0); price: float = Field(gt=0)
class BrokerPreview(BaseModel):
    symbol: str; side: str; quantity: float = Field(gt=0); order_type: str = "MARKET"
class BrokerApproval(BrokerPreview):
    human_approved: bool = False

@app.get("/api/health")
def health() -> dict[str, str]: return {"status": "ok", "service": "investment-intelligence-api", "version": app.version}

@app.post("/api/auth/register")
def register(request: RegisterRequest) -> dict[str, object]:
    user, error = create_user(request.name, request.email, request.password)
    if error: raise HTTPException(409, error)
    assert user is not None
    return {"access_token": issue_token(int(user["id"])), "token_type": "bearer", "user": user}

@app.post("/api/auth/login")
def login(request: LoginRequest) -> dict[str, object]:
    user = authenticate(request.email, request.password)
    if not user: raise HTTPException(401, "Invalid email or password.")
    return {"access_token": issue_token(int(user["id"])), "token_type": "bearer", "user": user}

@app.get("/api/auth/me")
def me(authorization: str | None = Header(default=None)) -> dict[str, object]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required.")
    user = user_from_token(authorization.split(" ", 1)[1].strip())
    if not user: raise HTTPException(401, "Session expired or invalid.")
    return user

@app.get("/api/assets")
def assets() -> list[dict[str, str]]: return [{"symbol": a.symbol, "name": a.name, "market": a.market, "currency": a.currency} for a in ASSETS]
@app.get("/api/market-data")
def market_data() -> dict[str, object]: return {"quotes": live_quotes(), "status": market_data_status()}

@app.get("/api/scanner")
def investment_scanner(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), market: str | None = None, verdict: str | None = None, min_score: float = Query(0, ge=0, le=100)) -> dict[str, object]:
    ranked = scanner(100)
    if market: ranked = [x for x in ranked if str(x["market"]).lower() == market.strip().lower()]
    if verdict: ranked = [x for x in ranked if str(x["verdict"]).upper() == verdict.strip().upper()]
    ranked = [x for x in ranked if float(x["score"]) >= min_score]
    return {"items": ranked[offset:offset + limit], "total": len(ranked), "offset": offset, "limit": limit, "universe_size": len(ASSETS)}

@app.get("/api/assets/{symbol}/analysis")
def asset_analysis(symbol: str) -> dict[str, object]:
    result = analyze_asset(symbol)
    if result is None: raise HTTPException(404, f"Asset {symbol.upper()} not found")
    return result
@app.get("/api/assets/{symbol}/bull-bear")
def asset_bull_bear(symbol: str) -> dict[str, object]:
    asset, analysis = get_asset(symbol), analyze_asset(symbol)
    if asset is None or analysis is None: raise HTTPException(404, f"Asset {symbol.upper()} not found")
    return bull_bear(asset.symbol, float(analysis["score"]), asset.catalysts, asset.risks)
@app.get("/api/assets/{symbol}/committee")
def asset_committee(symbol: str) -> dict[str, object]:
    asset, analysis = get_asset(symbol), analyze_asset(symbol)
    if asset is None or analysis is None: raise HTTPException(404, f"Asset {symbol.upper()} not found")
    return build_committee(analysis, bull_bear(asset.symbol, float(analysis["score"]), asset.catalysts, asset.risks))
@app.get("/api/assets/{symbol}/fundamentals")
def asset_fundamentals(symbol: str) -> dict[str, object]:
    result = fundamentals_for_symbol(symbol)
    if result is None: raise HTTPException(404, f"Asset {symbol.upper()} not found")
    return result.__dict__

@app.get("/api/intelligence/news")
def news() -> dict[str, object]: return market_intelligence()
@app.get("/api/intelligence/macro")
def macro() -> dict[str, object]: return macro_snapshot()
# Demo holdings: clearly labelled sample data until user portfolios are stored per account.
DEMO_HOLDINGS = [Holding("MSFT", 10, 350, 415.2, "USD"), Holding("ASML", 5, 600, 672.4, "EUR"), Holding("VISA", 8, 250, 277.3, "USD")]
DEMO_NOTICE = "Sample holdings for demonstration only. Not a real account and not live prices."


@app.get("/api/portfolio")
def portfolio() -> dict[str, object]:
    return {**portfolio_snapshot(DEMO_HOLDINGS, cash=2117, benchmark_return_pct=9.8), "source": "DEMO_HOLDINGS", "notice": DEMO_NOTICE}
@app.get("/api/risk")
def risk() -> dict[str, object]:
    return {**risk_metrics([0.004, -0.002, 0.006, 0.003, -0.004, 0.005, 0.002, -0.001]), "source": "ILLUSTRATIVE_RETURNS", "notice": "Calculated on an illustrative return series until real portfolio history is stored."}

@app.post("/api/backtest")
def backtest(request: BacktestRequest) -> dict[str, object]:
    return run_backtest(request.prices, request.scores, BacktestConfig(request.initial_cash, request.position_pct, request.buy_threshold, request.sell_threshold, request.transaction_cost_bps))
@app.get("/api/paper-trading")
def paper_snapshot() -> dict[str, object]:
    prices = {str(q["symbol"]): float(q["price"]) for q in live_quotes() if isinstance(q.get("price"), (int, float))}
    return {"mode": "PAPER", "live_trading_enabled": False, **paper_account.snapshot(prices)}
@app.post("/api/paper-trading/orders")
def paper_order(request: PaperOrder) -> dict[str, object]:
    if not get_asset(request.symbol): raise HTTPException(404, "Unknown symbol")
    try: return paper_account.submit(request.symbol, request.side, request.quantity, request.price)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
@app.post("/api/broker/preview")
def broker_preview(request: BrokerPreview) -> dict[str, object]: return gateway.preview(request.symbol, request.side, request.quantity, request.order_type).__dict__
@app.post("/api/broker/execute")
def broker_execute(request: BrokerApproval) -> dict[str, object]:
    order = gateway.preview(request.symbol, request.side, request.quantity, request.order_type)
    return gateway.execute(order, request.human_approved).__dict__

@app.get("/api/status")
def status() -> dict[str, object]:
    return {
        "market_data": {"mode": os.getenv("MARKET_DATA_MODE", "live"), "provider": "Yahoo Finance chart API (unofficial; personal research use)"},
        "fundamentals": {"mode": os.getenv("FUNDAMENTALS_MODE", "live"), "sec_enabled": sec_user_agent() is not None, "note": "Set SEC_USER_AGENT to 'Name email@domain' to enable SEC EDGAR fundamentals."},
        "ai_synthesis": {"enabled": bool(os.getenv("OPENAI_API_KEY"))},
        "paper_broker": {"enabled": gateway.paper_enabled},
        "live_trading": {"enabled": False, "note": "Live execution is blocked in this build."},
        "portfolio": {"source": "DEMO_HOLDINGS"},
    }


@app.get("/api/dashboard")
def dashboard() -> dict[str, object]:
    ranked = scanner(100)
    live_count = sum(1 for x in ranked if x["price_status"] == "LIVE")
    top = ranked[0]
    return {
        "generated_at": int(time.time()),
        "scanner": ranked[:5],
        "scanner_meta": {"universe_size": len(ASSETS), "live_price_coverage": live_count},
        "markets": index_quotes(),
        "macro": macro_snapshot(),
        "committee": {"symbol": top["symbol"], "verdict": top["verdict"], "score": top["score"], "approval_state": "HUMAN_DECISION_REQUIRED", "question": "What does the market already know that this score may be missing?"},
        "data_status": "LIVE_MARKET_DATA" if live_count else "DEMO_DATASET",
    }
