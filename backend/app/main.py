from __future__ import annotations

import os
import time
from fastapi import Depends, FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .auth import authenticate, create_user, issue_token, user_from_token
import hmac

from . import assistant, llm, monitoring, userdata
from .backtest import BacktestConfig, run_backtest, trend_backtest
from .history import price_history, statistics
from .broker import gateway
from .committee import build_committee
from .data import ASSETS, get_asset
from .engine import analyze_asset, scanner
from .fundamentals import fundamentals_for_symbol, sec_user_agent
from .intelligence import bull_bear, macro_snapshot, market_intelligence
from .market_data import index_quotes, live_quotes, market_data_status
from .portfolio import Holding, portfolio_snapshot, risk_metrics

app = FastAPI(title="Investment Intelligence API", version="1.2.0")
cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"])

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
    symbol: str = Field(min_length=1, max_length=20); side: str; quantity: float = Field(gt=0, le=1_000_000)
class HoldingIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=20); quantity: float = Field(gt=0, le=1e9); average_cost: float = Field(gt=0, le=1e9)
class JournalIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=20); decision: str; thesis: str = Field(min_length=10, max_length=4000); review_on: str | None = None
class OutcomeIn(BaseModel):
    outcome: str
class QuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
class AlertRuleIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=20); kind: str; threshold: float = Field(gt=0, le=1e9)
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

def current_user(authorization: str | None = Header(default=None)) -> dict[str, object]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required.")
    user = user_from_token(authorization.split(" ", 1)[1].strip())
    if not user: raise HTTPException(401, "Session expired or invalid.")
    return user


@app.get("/api/auth/me")
def me(user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
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
@app.post("/api/broker/preview")
def broker_preview(request: BrokerPreview) -> dict[str, object]: return gateway.preview(request.symbol, request.side, request.quantity, request.order_type).__dict__
@app.post("/api/broker/execute")
def broker_execute(request: BrokerApproval) -> dict[str, object]:
    order = gateway.preview(request.symbol, request.side, request.quantity, request.order_type)
    return gateway.execute(order, request.human_approved).__dict__

# ---------- Price history and backtests (real data only) ----------
def _history_or_error(symbol: str, range_: str):
    if get_asset(symbol) is None: raise HTTPException(404, f"Asset {symbol.upper()} not found")
    try: history = price_history(symbol.upper(), range_)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    if history is None: raise HTTPException(503, "Price history is unavailable (provider unreachable, unsupported market, or demo mode). No history is substituted.")
    return history


@app.get("/api/assets/{symbol}/history")
def asset_history(symbol: str, range: str = Query("1y")) -> dict[str, object]:  # noqa: A002 - public query name
    history = _history_or_error(symbol, range)
    return {**history.as_dict(), "statistics": statistics(history)}


@app.get("/api/assets/{symbol}/backtest")
def asset_backtest(symbol: str, range: str = Query("5y"), window: int = Query(200, ge=20, le=300), cost_bps: float = Query(10, ge=0, le=200)) -> dict[str, object]:  # noqa: A002
    history = _history_or_error(symbol, range)
    try: return trend_backtest(history, window, cost_bps)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


# ---------- Per-user data ----------
def _user_call(fn, *args):
    try: return fn(*args)
    except userdata.UserDataError as exc: raise HTTPException(400, str(exc)) from exc


@app.get("/api/me/portfolio")
def my_portfolio(user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    return _user_call(userdata.portfolio, int(user["id"]))
@app.post("/api/me/holdings")
def my_holding_upsert(body: HoldingIn, user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    return _user_call(userdata.upsert_holding, int(user["id"]), body.symbol, body.quantity, body.average_cost)
@app.delete("/api/me/holdings/{symbol}")
def my_holding_delete(symbol: str, user: dict[str, object] = Depends(current_user)) -> dict[str, str]:
    userdata.delete_holding(int(user["id"]), symbol)
    return {"status": "deleted"}
@app.get("/api/me/journal")
def my_journal(user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    return {"entries": userdata.list_journal(int(user["id"])), "decisions": sorted(userdata.JOURNAL_DECISIONS), "outcomes": sorted(userdata.JOURNAL_OUTCOMES)}
@app.post("/api/me/journal")
def my_journal_add(body: JournalIn, user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    return _user_call(userdata.add_journal, int(user["id"]), body.symbol, body.decision, body.thesis, body.review_on)
@app.patch("/api/me/journal/{entry_id}")
def my_journal_outcome(entry_id: int, body: OutcomeIn, user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    return _user_call(userdata.set_outcome, int(user["id"]), entry_id, body.outcome)
@app.get("/api/me/paper")
def my_paper(user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    return _user_call(userdata.paper_account, int(user["id"]))
@app.post("/api/me/paper/orders")
def my_paper_order(body: PaperOrder, user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    return _user_call(userdata.paper_order, int(user["id"]), body.symbol, body.side, body.quantity)


# ---------- Research assistant, alerts and track record ----------
@app.post("/api/assistant/ask")
def assistant_ask(body: QuestionIn, user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    try: return assistant.ask(body.question, int(user["id"]))
    except assistant.AssistantError as exc: raise HTTPException(400, str(exc)) from exc
@app.get("/api/me/assistant/history")
def assistant_history(user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    return {"items": assistant.history(int(user["id"]))}
@app.get("/api/me/alerts")
def my_alerts(user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    uid = int(user["id"])
    monitoring.evaluate_user(uid)
    return {"rules": monitoring.list_rules(uid), "events": monitoring.events(uid), "kinds": monitoring.ALERT_KINDS}
@app.post("/api/me/alerts/rules")
def my_alert_add(body: AlertRuleIn, user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    try: return monitoring.add_rule(int(user["id"]), body.symbol, body.kind, body.threshold)
    except monitoring.MonitoringError as exc: raise HTTPException(400, str(exc)) from exc
@app.delete("/api/me/alerts/rules/{rule_id}")
def my_alert_delete(rule_id: int, user: dict[str, object] = Depends(current_user)) -> dict[str, str]:
    monitoring.delete_rule(int(user["id"]), rule_id)
    return {"status": "deleted"}
@app.post("/api/me/alerts/read")
def my_alerts_read(user: dict[str, object] = Depends(current_user)) -> dict[str, str]:
    monitoring.mark_read(int(user["id"]))
    return {"status": "ok"}
@app.get("/api/me/track-record")
def my_track_record(user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    return monitoring.user_track_record(int(user["id"]))
@app.get("/api/track-record/signals")
def signal_track_record() -> dict[str, object]:
    return monitoring.signal_track_record()
@app.post("/api/jobs/daily-scan")
def daily_scan(x_job_token: str | None = Header(default=None)) -> dict[str, object]:
    expected = os.getenv("JOB_TOKEN", "")
    if len(expected) < 24:
        raise HTTPException(503, "Daily job is disabled: set JOB_TOKEN (at least 24 characters) on the server.")
    if not x_job_token or not hmac.compare_digest(x_job_token, expected):
        raise HTTPException(401, "Invalid job token.")
    return monitoring.run_daily_job()


@app.get("/api/status")
def status() -> dict[str, object]:
    return {
        "market_data": {"mode": os.getenv("MARKET_DATA_MODE", "live"), "provider": "Yahoo Finance chart API (unofficial; personal research use)"},
        "fundamentals": {"mode": os.getenv("FUNDAMENTALS_MODE", "live"), "sec_enabled": sec_user_agent() is not None, "note": "Set SEC_USER_AGENT to 'Name email@domain' to enable SEC EDGAR fundamentals."},
        "ai_synthesis": {"enabled": bool(os.getenv("OPENAI_API_KEY"))},
        "assistant": {"provider": llm.provider(), "daily_limit": int(os.getenv("ASSISTANT_DAILY_LIMIT", "20")), "note": "Set ANTHROPIC_API_KEY (or OPENAI_API_KEY) to enable generated answers; without one the assistant lists evidence only."},
        "daily_job": {"enabled": len(os.getenv("JOB_TOKEN", "")) >= 24},
        "paper_broker": {"enabled": gateway.paper_enabled},
        "live_trading": {"enabled": False, "note": "Live execution is blocked in this build."},
        "portfolio": {"source": "Per-user holdings (signed in); /api/portfolio remains a labelled sample"},
        "price_history": {"provider": "Yahoo Finance chart API (unofficial; personal research use)", "demo_mode": os.getenv("MARKET_DATA_MODE", "live") == "demo"},
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
