"""Regression tests for the second (diff) review round."""
from __future__ import annotations

import threading
import time
import types

import pytest
from fastapi.testclient import TestClient

from app import assistant, db, engine, fundamentals, llm, market_data, monitoring, ratelimit, userdata
from app.main import app

client = TestClient(app)


def _req(xff: str | None, host: str = "10.0.0.1"):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return types.SimpleNamespace(headers=headers, client=types.SimpleNamespace(host=host))


def test_client_ip_uses_rightmost_hop_behind_render(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    assert ratelimit.client_ip(_req("1.2.3.4, 203.0.113.9")) == "203.0.113.9"  # spoofed left entry ignored
    assert ratelimit.client_ip(_req("evil")) == "evil"  # single hop added by the proxy
    monkeypatch.delenv("RENDER")
    assert ratelimit.client_ip(_req("1.2.3.4")) == "10.0.0.1"  # header not trusted off Render


def test_prune_keeps_live_long_window_counters():
    ratelimit.reset()
    now = 1000.0
    for _ in range(3):
        assert ratelimit.hit("long", 3, 86400, now) is None
    assert ratelimit.hit("long", 3, 86400, now) is not None
    ratelimit._prune(now + 120)  # a short-window caller pruning must not drop the 24h counter
    assert ratelimit.hit("long", 3, 86400, now + 120) is not None


def test_failed_logins_from_one_ip_do_not_lock_out_the_owner():
    ratelimit.reset()
    client.post("/api/auth/register", json={"name": "Owner", "email": "owner@example.com", "password": "long-enough-1", "accept_terms": True})
    for _ in range(12):
        client.post("/api/auth/login", json={"email": "owner@example.com", "password": "wrong-password"}, headers={"x-forwarded-for": "198.51.100.7"})
    # The attacker's IP is limited, but the account-wide limit no longer exists: in tests all requests
    # share the testclient IP, so verify that the account-wide key is never created.
    assert not any(k.startswith("login:email:") for k in ratelimit._hits)


def test_broker_operator_is_matched_by_account_id(monkeypatch):
    from app import main
    monkeypatch.setattr(main.gateway, "paper_enabled", True)
    monkeypatch.setenv("BROKER_OPERATOR_USER_IDS", "7")
    with pytest.raises(Exception):
        main._broker_operator({"id": 8, "email": "listed@example.com"})
    main._broker_operator({"id": 7, "email": "anything@example.com"})


def test_legacy_asml_cost_in_usd_is_converted_not_mixed(monkeypatch):
    h = client.post("/api/auth/register", json={"name": "Legacy", "email": "legacy@example.com", "password": "long-enough-1", "accept_terms": True}).json()
    uid = h["user"]["id"]
    db.execute("INSERT INTO holdings(user_id,symbol,quantity,average_cost,created_at) VALUES(?,?,?,?,?)", (uid, "ASML", 2, 700.0, int(time.time())))
    monkeypatch.setattr(userdata, "fx_rate", lambda b, q: {"rate": 0.9, "status": "LIVE", "source": "test"} if (b, q) == ("USD", "EUR") else {"rate": 1.1, "status": "LIVE", "source": "test"})
    row = next(r for r in userdata.portfolio(uid)["holdings"] if r["symbol"] == "ASML")
    assert row["cost_currency"] == "USD" and row["currency"] == "EUR"
    assert row["cost_conversion"]["rate"] == 0.9 and "converted" in row["currency_note"]
    monkeypatch.setattr(userdata, "fx_rate", lambda b, q: {"rate": None, "status": "UNAVAILABLE", "source": None})
    p = userdata.portfolio(uid)
    row = next(r for r in p["holdings"] if r["symbol"] == "ASML")
    assert row["pnl"] is None and "ASML" in " ".join(p["notes"])


def test_split_factor_ratios_are_excluded():
    assert monitoring._looks_like_split(0.5) and monitoring._looks_like_split(0.667) and monitoring._looks_like_split(2.0)
    assert not monitoring._looks_like_split(0.92) and not monitoring._looks_like_split(1.12)


def test_snapshot_pairs_never_cross_currencies():
    now = int(time.time())
    def snap(day, price, ccy):
        db.insert("INSERT INTO scan_snapshots(snapshot_date,symbol,score,price,price_status,currency,created_at) VALUES(?,?,?,?,?,?,?)", (day, "ASML", 90, price, "LIVE", ccy, now))
    snap("2026-01-01", 700.0, "USD"); snap("2026-02-01", 640.0, "EUR")
    r = monitoring.signal_track_record()
    assert r["observations"] == 0  # USD 700 -> EUR 640 is a listing change, not a -8.6% return


def test_live_pe_withheld_after_split_since_eps_period():
    f = fundamentals.FundamentalSnapshot("X", 2025, 1, 1, 1, 4.0, 0, 0, 1, 1, 1, 0, "SEC Company Facts", "LIVE",
                                         eps_period_end="2025-12-31", diluted_shares=100.0, shares_outstanding=100.0)
    from datetime import date
    pe, reason = engine.live_pe_assessment(100, True, "USD", f, today=date(2026, 3, 1), split_dates=["2026-02-10"])
    assert pe is None and "split" in reason
    pe, reason = engine.live_pe_assessment(100, True, "USD", f, today=date(2026, 3, 1), split_dates=["2025-06-01"])
    assert pe == 25.0


def test_parse_splits_from_chart_events():
    from app.history import parse_splits
    node = {"events": {"splits": {"1": {"date": 1_717_977_600, "numerator": 10, "denominator": 1}, "bad": {"date": "x"}}}}
    assert parse_splits(node) == (("2024-06-10", 10.0),)


def test_assistant_reservation_is_serialised(monkeypatch):
    h = client.post("/api/auth/register", json={"name": "Racer", "email": "racer@example.com", "password": "long-enough-1", "accept_terms": True}).json()
    uid = h["user"]["id"]
    results = []
    def go():
        results.append(assistant._reserve(uid, "q", "anthropic", 3))
    threads = [threading.Thread(target=go) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sum(1 for r in results if r is not None) == 3


def test_writes_after_account_deletion_are_refused():
    r = client.post("/api/auth/register", json={"name": "Gone", "email": "gone@example.com", "password": "long-enough-1", "accept_terms": True}).json()
    uid = r["user"]["id"]
    userdata.delete_user_data(uid, delete_account=True)
    for call in (lambda: userdata.upsert_holding(uid, "MSFT", 1, 100), lambda: userdata.paper_order(uid, "MSFT", "BUY", 1),
                 lambda: monitoring.add_rule(uid, "MSFT", "SCORE_ABOVE", 10), lambda: userdata.add_journal(uid, "MSFT", "WATCH", "long enough thesis", None)):
        with pytest.raises(userdata.AccountDeleted):
            call()
    for table in ("holdings", "paper_orders", "alert_rules", "journal_entries"):
        assert db.fetch_one(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=?", (uid,))["n"] == 0


def test_track_record_survives_positions_without_pnl(monkeypatch):
    r = client.post("/api/auth/register", json={"name": "Track", "email": "track@example.com", "password": "long-enough-1", "accept_terms": True}).json()
    uid, h = r["user"]["id"], {"Authorization": f"Bearer {r['access_token']}"}
    db.insert("INSERT INTO paper_orders(user_id,symbol,side,quantity,fill_price,price_status,created_at) VALUES(?,?,?,?,?,?,?)", (uid, "ASML", "BUY", 1, 700.0, "LIVE", int(time.time())))
    monkeypatch.setattr(userdata, "fx_rate", lambda b, q: {"rate": None, "status": "UNAVAILABLE", "source": None})
    body = client.get("/api/me/track-record", headers=h)
    assert body.status_code == 200 and body.json()["paper"]["positions_without_pnl"] == 1
