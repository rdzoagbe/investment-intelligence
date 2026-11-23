from __future__ import annotations

import time
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import db, market_data, monitoring
from app.main import app

client = TestClient(app)


def login(email="m@example.com"):
    r = client.post("/api/auth/register", json={"name": "Member", "email": email, "password": "long-enough-1", "accept_terms": True})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_demo_prices_never_trigger_price_alerts_but_scores_do():
    h = login()
    assert client.post("/api/me/alerts/rules", json={"symbol": "MSFT", "kind": "PRICE_ABOVE", "threshold": 1}, headers=h).status_code == 200
    assert client.post("/api/me/alerts/rules", json={"symbol": "MSFT", "kind": "SCORE_ABOVE", "threshold": 10}, headers=h).status_code == 200
    events = client.get("/api/me/alerts", headers=h).json()["events"]
    assert len(events) == 1 and "model score" in events[0]["message"]
    assert len(client.get("/api/me/alerts", headers=h).json()["events"]) == 1  # cooldown: no duplicate


def test_live_price_alert_fires(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "live")
    monkeypatch.setattr(market_data, "_fetch_json", lambda url, timeout=5.0: {"chart": {"result": [{"meta": {"regularMarketPrice": 500.0, "previousClose": 450.0, "currency": "USD"}}]}} if "range=5d" in url else {"chart": {"result": []}})
    h = login("live@example.com")
    client.post("/api/me/alerts/rules", json={"symbol": "MSFT", "kind": "PRICE_ABOVE", "threshold": 480}, headers=h)
    client.post("/api/me/alerts/rules", json={"symbol": "MSFT", "kind": "DAILY_MOVE", "threshold": 5}, headers=h)
    msgs = [e["message"] for e in client.get("/api/me/alerts", headers=h).json()["events"]]
    assert any("above your 480.00" in m for m in msgs) and any("+11.11%" in m for m in msgs)


def test_rule_validation_and_isolation():
    a, b = login("a1@example.com"), login("b1@example.com")
    assert client.post("/api/me/alerts/rules", json={"symbol": "NOPE", "kind": "PRICE_ABOVE", "threshold": 1}, headers=a).status_code == 400
    assert client.post("/api/me/alerts/rules", json={"symbol": "MSFT", "kind": "MOON", "threshold": 1}, headers=a).status_code == 400
    assert client.post("/api/me/alerts/rules", json={"symbol": "MSFT", "kind": "SCORE_ABOVE", "threshold": 150}, headers=a).status_code == 400
    rid = client.post("/api/me/alerts/rules", json={"symbol": "MSFT", "kind": "SCORE_BELOW", "threshold": 5}, headers=a).json()["id"]
    client.delete(f"/api/me/alerts/rules/{rid}", headers=b)  # not theirs: no effect
    assert len(client.get("/api/me/alerts", headers=a).json()["rules"]) == 1


def test_due_journal_review_creates_one_event():
    h = login("j1@example.com")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    client.post("/api/me/journal", json={"symbol": "NVDA", "decision": "WATCH", "thesis": "Check after earnings.", "review_on": yesterday}, headers=h)
    client.get("/api/me/alerts", headers=h)
    events = client.get("/api/me/alerts", headers=h).json()["events"]
    assert len(events) == 1 and "Journal review due" in events[0]["message"]


def test_daily_job_requires_token_and_snapshots_once(monkeypatch):
    assert client.post("/api/jobs/daily-scan").status_code == 503
    monkeypatch.setenv("JOB_TOKEN", "t" * 32)
    assert client.post("/api/jobs/daily-scan", headers={"X-Job-Token": "wrong"}).status_code == 401
    r = client.post("/api/jobs/daily-scan", headers={"X-Job-Token": "t" * 32}).json()
    assert r["snapshots_stored"] == 25
    assert client.post("/api/jobs/daily-scan", headers={"X-Job-Token": "t" * 32}).json()["snapshots_stored"] == 0


def test_signal_track_record_uses_live_pairs_only():
    assert client.get("/api/track-record/signals").json()["sufficient"] is False
    now = int(time.time())
    def snap(day, sym, score, price, status="LIVE"):
        db.insert("INSERT INTO scan_snapshots(snapshot_date,symbol,score,price,price_status,currency,created_at) VALUES(?,?,?,?,?,?,?)", (day, sym, score, price, status, "USD", now))
    snap("2026-01-01", "AAA", 90, 100); snap("2026-01-20", "AAA", 90, 110)
    snap("2026-01-01", "BBB", 50, 100); snap("2026-01-20", "BBB", 50, 95)
    snap("2026-01-01", "CCC", 90, 100, "DEMO"); snap("2026-01-20", "CCC", 90, 500, "DEMO")
    snap("2026-01-18", "AAA", 90, 108)  # only 2 days before latest: excluded
    r = client.get("/api/track-record/signals").json()
    bands = {b["band"]: b for b in r["bands"]}
    assert bands["High score"]["average_forward_return_pct"] == 10.0 and bands["High score"]["observations"] == 1
    assert bands["Low score"]["average_forward_return_pct"] == -5.0
    assert r["sufficient"] is False


def test_user_track_record_realized_pnl_and_hit_rate():
    h = login("tr@example.com")
    uid = client.get("/api/auth/me", headers=h).json()["id"]
    now = int(time.time())
    for side, qty, px in [("BUY", 10, 100), ("SELL", 5, 120), ("SELL", 5, 90)]:
        db.insert("INSERT INTO paper_orders(user_id,symbol,side,quantity,fill_price,price_status,created_at) VALUES(?,?,?,?,?,?,?)", (uid, "MSFT", side, qty, px, "LIVE", now))
    e = client.post("/api/me/journal", json={"symbol": "MSFT", "decision": "BUY", "thesis": "Cloud growth continues."}, headers=h).json()
    client.patch(f"/api/me/journal/{e['id']}", json={"outcome": "THESIS_CONFIRMED"}, headers=h)
    r = client.get("/api/me/track-record", headers=h).json()
    assert r["paper"]["realized_pnl"] == 50.0 and r["paper"]["closed_trades"] == 2 and r["paper"]["win_rate_pct"] == 50.0
    assert r["journal"]["thesis_hit_rate_pct"] == 100.0
