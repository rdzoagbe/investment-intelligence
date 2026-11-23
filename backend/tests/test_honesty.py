"""Guards against fabricated or unlabelled data reaching the UI."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import fundamentals
from app.main import app
from app.market_data import index_quotes

client = TestClient(app)


def test_index_quotes_never_invent_values_in_demo_mode(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "demo")
    for row in index_quotes():
        assert row["status"] == "UNAVAILABLE"
        assert row["value"] is None


def test_sec_adapter_requires_real_contact(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert fundamentals.sec_user_agent() is None
    monkeypatch.setenv("SEC_USER_AGENT", "Research contact@localhost")
    assert fundamentals.sec_user_agent() is None
    monkeypatch.setenv("SEC_USER_AGENT", "Jane Doe jane@example.com")
    assert fundamentals.sec_user_agent() == "Jane Doe jane@example.com"


def test_dashboard_has_no_hardcoded_portfolio(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "demo")
    monkeypatch.setenv("FUNDAMENTALS_MODE", "demo")
    body = client.get("/api/dashboard").json()
    assert "portfolio" not in body
    assert "insights" not in body
    assert body["data_status"] == "DEMO_DATASET"
    assert all(m["value"] is None for m in body["markets"])


def _rank(statuses: dict[str, str]):
    return [{"symbol": sym, "price_status": st} for sym, st in statuses.items()]


def test_dashboard_status_is_live_only_when_every_supported_quote_is_live():
    from app.main import data_status_for
    # ACCESS is a GSE listing with no provider symbol: it does not block LIVE.
    assert data_status_for(_rank({"MSFT": "LIVE", "VISA": "LIVE", "ACCESS": "DEMO"}))[0] == "LIVE_MARKET_DATA"
    assert data_status_for(_rank({"MSFT": "LIVE", "VISA": "DEMO", "ACCESS": "DEMO"}))[0] == "PARTIAL_LIVE"
    assert data_status_for(_rank({"MSFT": "DEMO", "VISA": "DEMO"}))[0] == "DEMO_DATASET"


def test_dashboard_with_one_live_quote_is_not_reported_live(monkeypatch):
    from app import main
    real_scanner = main.scanner

    def mixed(limit):
        rows = real_scanner(limit)
        rows[0] = {**rows[0], "price_status": "LIVE"}
        return rows
    monkeypatch.setattr(main, "scanner", mixed)
    body = client.get("/api/dashboard").json()
    assert body["data_status"] == "PARTIAL_LIVE"
    assert body["committee"]["price_status"] == "LIVE"
    assert body["scanner_meta"]["live_price_coverage"] == 1


def test_status_has_no_legacy_ai_synthesis_and_no_secret_values(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-very-secret")
    body = client.get("/api/status").json()
    assert "ai_synthesis" not in body
    assert body["config"]["anthropic_api_key"] == "set"
    assert body["config"]["job_token"] == "missing"
    assert body["database"] == {"ok": True, "engine": "sqlite"}
    assert "sk-test-very-secret" not in str(body)


def test_demo_portfolio_and_risk_are_labelled():
    assert client.get("/api/portfolio").json()["source"] == "DEMO_HOLDINGS"
    assert client.get("/api/risk").json()["source"] == "ILLUSTRATIVE_RETURNS"


def test_risk_sizing_is_labelled_illustrative(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "demo")
    monkeypatch.setenv("FUNDAMENTALS_MODE", "demo")
    risk = client.get("/api/assets/MSFT/analysis").json()["risk"]
    assert "Not a recommendation" in risk["note"]
