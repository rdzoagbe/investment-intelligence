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


def test_demo_portfolio_and_risk_are_labelled():
    assert client.get("/api/portfolio").json()["source"] == "DEMO_HOLDINGS"
    assert client.get("/api/risk").json()["source"] == "ILLUSTRATIVE_RETURNS"


def test_risk_sizing_is_labelled_illustrative(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "demo")
    monkeypatch.setenv("FUNDAMENTALS_MODE", "demo")
    risk = client.get("/api/assets/MSFT/analysis").json()["risk"]
    assert "Not a recommendation" in risk["note"]
