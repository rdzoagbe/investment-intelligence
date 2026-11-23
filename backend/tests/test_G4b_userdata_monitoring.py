from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from app import db, monitoring, userdata
from app.history import PriceHistory


def run_threads(fn, n):
    errors, results = [], []
    barrier = threading.Barrier(n)

    def worker():
        barrier.wait()
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


# ---------- userdata ----------
def test_upsert_holding_is_atomic_under_concurrency():
    results, errors = run_threads(lambda: userdata.upsert_holding(1, "AAPL", 2, 150), 8)
    assert errors == [] and len(results) == 8
    rows = userdata.list_holdings(1)
    assert len(rows) == 1 and rows[0]["quantity"] == 2
    userdata.upsert_holding(1, "aapl", 5, 160)
    rows = userdata.list_holdings(1)
    assert [(r["symbol"], r["quantity"], r["average_cost"]) for r in rows] == [("AAPL", 5, 160)]


def test_concurrent_paper_buys_cannot_overdraw_cash():
    price = 415.2  # MSFT demo quote
    results, errors = run_threads(lambda: userdata.paper_order(7, "MSFT", "BUY", 40), 12)
    assert all(isinstance(e, userdata.UserDataError) for e in errors)
    assert len(results) == int(100_000 // (40 * price))  # 6
    acct = userdata.paper_account(7)
    assert acct["cash"] >= 0


def test_concurrent_paper_sells_cannot_go_short():
    userdata.paper_order(8, "MSFT", "BUY", 10)
    results, errors = run_threads(lambda: userdata.paper_order(8, "MSFT", "SELL", 10), 6)
    assert len(results) == 1 and len(errors) == 5
    assert userdata.paper_account(8)["positions"] == []


def test_paper_order_and_journal_caps(monkeypatch):
    monkeypatch.setattr(userdata, "MAX_PAPER_ORDERS", 2)
    userdata.paper_order(9, "MSFT", "BUY", 1)
    userdata.paper_order(9, "MSFT", "BUY", 1)
    with pytest.raises(userdata.UserDataError, match="2 orders"):
        userdata.paper_order(9, "MSFT", "BUY", 1)
    monkeypatch.setattr(userdata, "MAX_JOURNAL_ENTRIES", 1)
    userdata.add_journal(9, "MSFT", "WATCH", "First thesis text here.", None)
    with pytest.raises(userdata.UserDataError, match="up to 1 journal"):
        userdata.add_journal(9, "MSFT", "WATCH", "Second thesis text here.", None)


def test_journal_and_paper_order_lists_are_paginated():
    now = int(time.time())
    for i in range(5):
        db.insert("INSERT INTO journal_entries(user_id,symbol,decision,thesis,evidence,review_on,outcome,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (3, "MSFT", "WATCH", f"thesis {i} long text", "{}", None, "OPEN", now + i))
        db.insert("INSERT INTO paper_orders(user_id,symbol,side,quantity,fill_price,price_status,created_at) VALUES(?,?,?,?,?,?,?)",
                  (3, "MSFT", "BUY", 1, 10, "LIVE", now))
    assert len(userdata.list_journal(3)) == 5
    page = userdata.list_journal(3, limit=2, offset=1)
    assert [e["thesis"] for e in page] == ["thesis 3 long text", "thesis 2 long text"]
    assert len(userdata.list_journal(3, limit=0)) == 1  # clamped to >= 1
    assert userdata._page(5000, None) == (userdata.MAX_PAGE, 0)
    assert userdata._page(None, None) == (200, 0)
    acct = userdata.paper_account(3, order_limit=2)
    assert len(acct["orders"]) == 2 and acct["order_count"] == 5


def test_paper_account_flags_demo_priced_positions():
    userdata.paper_order(4, "MSFT", "BUY", 1)
    acct = userdata.paper_account(4)
    assert acct["demo_priced_positions"] == 1
    assert any("DEMO fallback prices" in n for n in acct["notes"])
    tr = monitoring.user_track_record(4)
    assert tr["paper"]["positions_valued_on_demo_prices"] == 1
    assert any("not live" in n for n in tr["notes"])


def test_portfolio_converted_usd_only_and_flags_demo():
    userdata.upsert_holding(5, "MSFT", 2, 400)
    p = userdata.portfolio(5)
    conv = p["converted"]
    assert conv is not None and conv["currency"] == "USD" and conv["complete"] is False  # DEMO prices
    assert conv["rates"]["USD"]["status"] == "IDENTITY" and conv["rates"]["USD"]["rate"] == 1.0
    assert conv["value"] == p["totals_by_currency"]["USD"]["value"]
    assert p["totals_by_currency"]["USD"]["demo_priced_holdings"] == 1


def test_portfolio_converted_is_null_when_rate_unavailable(monkeypatch):
    monkeypatch.setattr(userdata, "fx_rate", lambda b, q: {"rate": 1.0, "status": "IDENTITY", "source": None, "timestamp": None} if b == q
                        else {"rate": None, "status": "UNAVAILABLE", "source": None, "timestamp": None})
    userdata.upsert_holding(6, "MSFT", 1, 400)
    userdata.upsert_holding(6, "SAP", 1, 100)
    p = userdata.portfolio(6)
    assert len(p["totals_by_currency"]) == 2
    assert p["converted"] is None
    assert any("no rate is assumed" in n for n in p["notes"])


def test_portfolio_converted_uses_live_rate(monkeypatch):
    monkeypatch.setattr(userdata, "fx_rate", lambda b, q: {"rate": 1.0, "status": "IDENTITY", "source": None, "timestamp": None} if b == q
                        else {"rate": 1.1, "status": "LIVE", "source": f"Yahoo Finance chart API ({b}{q}=X)", "timestamp": 1})
    userdata.upsert_holding(10, "MSFT", 1, 400)
    userdata.upsert_holding(10, "SAP", 1, 100)
    p = userdata.portfolio(10)
    t = p["totals_by_currency"]
    other = next(c for c in t if c != "USD")
    conv = p["converted"]
    assert conv["value"] == round(t["USD"]["value"] + t[other]["value"] * 1.1, 2)
    assert conv["rates"][other] == {"rate": 1.1, "status": "LIVE", "source": f"Yahoo Finance chart API ({other}USD=X)"}


def test_export_and_delete_user_data():
    now = int(time.time())
    userdata.upsert_holding(11, "MSFT", 1, 400)
    userdata.add_journal(11, "MSFT", "WATCH", "Exportable thesis text.", None)
    userdata.paper_order(11, "MSFT", "BUY", 1)
    monitoring.add_rule(11, "MSFT", "SCORE_ABOVE", 10)
    db.insert("INSERT INTO assistant_queries(user_id,question,response,provider,created_at) VALUES(?,?,?,?,?)", (11, "q?", "{}", "rule", now))
    userdata.upsert_holding(12, "AAPL", 1, 100)  # other user untouched
    monitoring.evaluate_user(11)
    data = userdata.export_user_data(11)
    json.dumps(data)
    assert {k: len(v) for k, v in data.items()} == {"holdings": 1, "journal": 1, "paper_orders": 1, "alert_rules": 1, "alert_events": 1, "assistant_history": 1}
    assert isinstance(data["journal"][0]["evidence"], dict)
    userdata.delete_user_data(11)
    assert all(len(v) == 0 for v in userdata.export_user_data(11).values())
    assert len(userdata.list_holdings(12)) == 1


# ---------- monitoring ----------
def test_score_alert_message_marks_demo_inputs():
    monitoring.add_rule(20, "MSFT", "SCORE_ABOVE", 1)
    monitoring.evaluate_user(20)
    msg = monitoring.events(20)[0]["message"]
    assert "model score" in msg and "demo/seed data, not live" in msg
    assert monitoring._score_data_note({"price_status": "LIVE", "fundamental_inputs": {"status": "LIVE"}}) == ""
    assert "Some fundamentals" in monitoring._score_data_note({"price_status": "LIVE", "fundamental_inputs": {"status": "PARTIAL"}})


def test_concurrent_alert_evaluation_creates_one_event_per_rule_and_review():
    monitoring.add_rule(21, "MSFT", "SCORE_ABOVE", 1)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    userdata.add_journal(21, "NVDA", "WATCH", "Check after earnings.", yesterday)
    results, errors = run_threads(lambda: monitoring.evaluate_user(21), 6)
    assert errors == []
    assert sum(results) == 2
    assert len(monitoring.events(21)) == 2


def test_take_snapshot_overlapping_runs_do_not_fail():
    results, errors = run_threads(lambda: monitoring.take_snapshot("2026-03-02"), 3)
    assert errors == [] and sum(results) == 25
    assert monitoring.take_snapshot("2026-03-02") == 0


def test_maybe_run_daily_snapshot_schedule_and_idempotence(monkeypatch):
    sat = datetime(2026, 3, 7, 22, 0, tzinfo=timezone.utc)
    early = datetime(2026, 3, 9, 21, 0, tzinfo=timezone.utc)
    ok = datetime(2026, 3, 9, 21, 45, tzinfo=timezone.utc)
    assert monitoring.maybe_run_daily_snapshot(sat) is None
    assert monitoring.maybe_run_daily_snapshot(early) is None
    r = monitoring.maybe_run_daily_snapshot(ok)
    assert r is not None and r["snapshot_date"] == "2026-03-09" and r["snapshots_stored"] == 25
    assert monitoring.maybe_run_daily_snapshot(ok) is None
    # Existing snapshot for the date (e.g. from the cron job): skipped.
    monitoring.take_snapshot("2026-03-10")
    assert monitoring.maybe_run_daily_snapshot(datetime(2026, 3, 10, 23, 0)) is None  # naive = UTC
    # Concurrent callers run it once.
    calls = []
    real = monitoring.take_snapshot
    monkeypatch.setattr(monitoring, "take_snapshot", lambda day=None: (calls.append(day), time.sleep(0.2), real(day))[2])
    results, errors = run_threads(lambda: monitoring.maybe_run_daily_snapshot(datetime(2026, 3, 11, 22, 0, tzinfo=timezone.utc)), 5)
    assert errors == [] and calls == ["2026-03-11"] and sum(1 for r in results if r) == 1


def test_maybe_run_daily_snapshot_never_raises(monkeypatch):
    def boom(day=None):
        raise RuntimeError("provider down")
    monkeypatch.setattr(monitoring, "take_snapshot", boom)
    assert monitoring.maybe_run_daily_snapshot(datetime(2026, 3, 12, 22, 0, tzinfo=timezone.utc)) is None


def _snap(day, sym, score, price, status="LIVE"):
    db.insert("INSERT INTO scan_snapshots(snapshot_date,symbol,score,price,price_status,currency,created_at) VALUES(?,?,?,?,?,?,?)",
              (day, sym, score, price, status, "USD", int(time.time())))


def test_track_record_excludes_likely_splits_without_history():
    _snap("2026-01-01", "AAA", 90, 1200); _snap("2026-01-20", "AAA", 90, 125)  # 10-for-1 split
    _snap("2026-01-01", "BBB", 90, 100); _snap("2026-01-20", "BBB", 90, 110)
    _snap("2026-01-01", "CCC", 90, 100); _snap("2026-01-20", "CCC", 90, 50, "DEMO")  # end not LIVE: never paired with DEMO
    r = monitoring.signal_track_record()
    bands = {b["band"]: b for b in r["bands"]}
    assert bands["High score"]["observations"] == 1 and bands["High score"]["average_forward_return_pct"] == 10.0
    assert r["excluded_suspected_splits"] == 1
    assert any("likely stock splits" in n for n in r["notes"])


def test_track_record_prefers_adjusted_history(monkeypatch):
    _snap("2026-01-01", "NVDA", 90, 1200); _snap("2026-01-20", "NVDA", 90, 125)
    hist = PriceHistory("NVDA", ["2025-12-31", "2026-01-02", "2026-01-20"], [118.0, 120.0, 125.0], "USD", adjusted=True)
    monkeypatch.setattr(monitoring, "price_history", lambda sym, range_="2y": hist if sym == "NVDA" else None)
    r = monitoring.signal_track_record()
    bands = {b["band"]: b for b in r["bands"]}
    # 2026-01-01 uses the close on or before that date (118.0): 125/118 - 1
    assert bands["High score"]["average_forward_return_pct"] == round((125 / 118 - 1) * 100, 2)
    assert r["returns_from_adjusted_history"] == 1 and r["excluded_suspected_splits"] == 0
