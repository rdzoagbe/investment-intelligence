from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def signup(email: str) -> dict[str, str]:
    r = client.post("/api/auth/register", json={"name": "User", "email": email, "password": "long-enough-1", "accept_terms": True})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.parametrize("method,path", [("get", "/api/me/portfolio"), ("get", "/api/me/journal"), ("get", "/api/me/paper"), ("post", "/api/me/paper/orders")])
def test_user_endpoints_require_login(method, path):
    assert getattr(client, method)(path).status_code == 401


def test_holdings_are_private_per_user():
    a, b = signup("a@example.com"), signup("b@example.com")
    assert client.post("/api/me/holdings", json={"symbol": "msft", "quantity": 3, "average_cost": 300}, headers=a).status_code == 200
    assert client.post("/api/me/holdings", json={"symbol": "MSFT", "quantity": 5, "average_cost": 310}, headers=a).status_code == 200  # update
    pa = client.get("/api/me/portfolio", headers=a).json()
    assert [(h["symbol"], h["quantity"]) for h in pa["holdings"]] == [("MSFT", 5)]
    assert pa["holdings"][0]["price_status"] == "DEMO"
    assert "USD" in pa["totals_by_currency"]
    assert client.get("/api/me/portfolio", headers=b).json()["holdings"] == []
    assert client.post("/api/me/holdings", json={"symbol": "NOPE", "quantity": 1, "average_cost": 1}, headers=a).status_code == 400
    client.delete("/api/me/holdings/MSFT", headers=a)
    assert client.get("/api/me/portfolio", headers=a).json()["holdings"] == []


def test_journal_captures_evidence_and_outcomes():
    a, b = signup("j@example.com"), signup("k@example.com")
    r = client.post("/api/me/journal", json={"symbol": "NVDA", "decision": "watch", "thesis": "Data-centre demand vs valuation risk.", "review_on": "2027-03-01"}, headers=a)
    assert r.status_code == 200, r.text
    entry = r.json()
    assert entry["decision"] == "WATCH" and entry["outcome"] == "OPEN"
    assert entry["evidence"]["price_status"] == "DEMO" and "score" in entry["evidence"]
    assert client.patch(f"/api/me/journal/{entry['id']}", json={"outcome": "thesis_broken"}, headers=b).status_code == 400  # not theirs
    assert client.patch(f"/api/me/journal/{entry['id']}", json={"outcome": "thesis_broken"}, headers=a).json()["outcome"] == "THESIS_BROKEN"
    assert client.post("/api/me/journal", json={"symbol": "NVDA", "decision": "YOLO", "thesis": "long enough text"}, headers=a).status_code == 400
    assert client.post("/api/me/journal", json={"symbol": "NVDA", "decision": "BUY", "thesis": "long enough text", "review_on": "soon"}, headers=a).status_code == 400
    assert len(client.get("/api/me/journal", headers=b).json()["entries"]) == 0


def test_paper_orders_fill_at_server_price_and_persist():
    a = signup("p@example.com")
    r = client.post("/api/me/paper/orders", json={"symbol": "MSFT", "side": "BUY", "quantity": 10, "price": 0.01}, headers=a)
    assert r.status_code == 200, r.text
    assert r.json()["fill_price"] == 415.2  # demo quote, client price ignored
    acct = client.get("/api/me/paper", headers=a).json()
    assert acct["cash"] == round(100000 - 4152, 2)
    assert acct["positions"][0]["quantity"] == 10
    assert client.post("/api/me/paper/orders", json={"symbol": "MSFT", "side": "SELL", "quantity": 11}, headers=a).status_code == 400
    assert client.post("/api/me/paper/orders", json={"symbol": "MSFT", "side": "BUY", "quantity": 1000}, headers=a).status_code == 400
    assert client.post("/api/me/paper/orders", json={"symbol": "MSFT", "side": "SELL", "quantity": 10}, headers=a).status_code == 200
    acct = client.get("/api/me/paper", headers=a).json()
    assert acct["positions"] == [] and acct["cash"] == 100000 and len(acct["orders"]) == 2


def test_history_and_backtest_endpoints_refuse_to_invent_data():
    assert client.get("/api/assets/MSFT/history").status_code == 503
    assert client.get("/api/assets/MSFT/backtest").status_code == 503
    assert client.get("/api/assets/NOPE/history").status_code == 404
