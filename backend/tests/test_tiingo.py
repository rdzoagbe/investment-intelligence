from __future__ import annotations

import io
import json
from datetime import date, timedelta
from urllib.error import HTTPError

from fastapi.testclient import TestClient

from app import history, market_data, tiingo
from app.data import get_asset
from app.main import app

KEY = "test-key-0123456789"


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def snapshot_payload():
    # Shape follows tiingo.com/documentation/equity-realtime-stock-data (2.5.2).
    return [
        {"ticker": "msft", "timestamp": "2026-11-23T20:59:59.123+00:00", "tngoLast": 420.5, "lqRefPrice": 420.5, "prevClose": 410.0, "prevDate": "2026-11-20", "open": 411.0, "high": 421.0, "low": 409.0, "volume": 1000},
        {"ticker": "V", "timestamp": "2026-11-23T20:59:59+00:00", "tngoLast": 300.0, "prevClose": 300.0, "prevDate": "2026-11-20"},
        {"ticker": "NVDA", "timestamp": "2026-11-23T20:59:59+00:00", "tngoLast": None, "prevClose": 150.0},  # no price -> skipped
        {"ticker": "ZZZZ", "timestamp": "2026-11-23T20:59:59+00:00", "tngoLast": 5.0, "prevClose": 5.0},  # not ours
    ]


def daily_payload(years=10, split_on=None):
    # Shape follows tiingo.com/documentation/end-of-day.
    rows, day, price = [], date(2026, 11, 20) - timedelta(days=365 * years), 50.0
    while day <= date(2026, 11, 20):
        if day.weekday() < 5:
            price *= 1.0004
            rows.append({"date": f"{day.isoformat()}T00:00:00.000Z", "close": price * 2, "adjClose": price, "volume": 1, "divCash": 0.0,
                         "splitFactor": 10.0 if day.isoformat() == split_on else 1.0})
        day += timedelta(days=1)
    return rows


def enable(monkeypatch, owners="1"):
    monkeypatch.setenv("MARKET_DATA_MODE", "live")
    monkeypatch.setenv("TIINGO_API_KEY", KEY)
    if owners:
        monkeypatch.setenv("OWNER_USER_IDS", owners)


def fake_tiingo(monkeypatch, calls, daily=None):
    def opener(request, timeout=15.0):
        calls.append(request)
        url = request.full_url
        if url.startswith("https://api.tiingo.com/tiingo/equity/intraday"):
            return Resp(json.dumps(snapshot_payload()).encode())
        if url.startswith("https://api.tiingo.com/tiingo/daily/"):
            return Resp(json.dumps(daily if daily is not None else daily_payload()).encode())
        raise AssertionError(url)
    monkeypatch.setattr(tiingo, "urlopen", opener)
    monkeypatch.setattr(market_data, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Yahoo must not be called for covered US stocks")))


def test_licence_gate(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "live")
    assert not tiingo.enabled() and "not set" in tiingo.disabled_reason()


def test_personal_licence_requires_private_site(monkeypatch):
    enable(monkeypatch, owners="")
    assert not tiingo.enabled() and "personal use only" in tiingo.disabled_reason()
    monkeypatch.setenv("TIINGO_LICENSE", "commercial")
    assert tiingo.enabled()
    monkeypatch.delenv("TIINGO_LICENSE")
    monkeypatch.setenv("OWNER_USER_IDS", "7")
    assert tiingo.enabled()
    monkeypatch.setenv("MARKET_DATA_MODE", "demo")
    assert not tiingo.enabled()


def test_coverage_is_us_usd_only():
    assert tiingo.ticker_for("VISA") == "V" and tiingo.ticker_for("BRK-B") == "BRK-B" and tiingo.ticker_for("NVDA") == "NVDA"
    for symbol in ("ASML", "SAP", "NESN.SW", "MC.PA", "ACCESS"):
        assert tiingo.ticker_for(symbol) is None


def test_quotes_come_from_one_request_with_token_header(monkeypatch):
    enable(monkeypatch)
    calls = []
    fake_tiingo(monkeypatch, calls)
    q = market_data.quote_for_asset(get_asset("MSFT"))
    assert (q.status, q.price, q.previous_close, q.currency, q.provider) == ("LIVE", 420.5, 410.0, "USD", tiingo.QUOTE_PROVIDER)
    assert q.change_pct == round((420.5 / 410.0 - 1) * 100, 3) and q.timestamp is not None
    assert market_data.quote_for_asset(get_asset("VISA")).price == 300.0
    assert len(calls) == 1
    request = calls[0]
    assert request.get_header("Authorization") == f"Token {KEY}" and KEY not in request.full_url


def test_missing_tiingo_price_is_not_invented(monkeypatch):
    enable(monkeypatch)
    calls = []
    fake_tiingo(monkeypatch, calls)
    monkeypatch.setattr(market_data, "yahoo_quote", lambda *a, **k: None)
    q = market_data.quote_for_asset(get_asset("NVDA"))
    assert q.status == "DEMO"


def test_history_one_request_per_ticker_sliced_per_range(monkeypatch):
    enable(monkeypatch)
    calls = []
    fake_tiingo(monkeypatch, calls, daily=daily_payload(split_on="2024-06-10"))
    one = history.price_history("NVDA", "1y")
    ten = history.price_history("NVDA", "10y")
    assert one and ten and len(calls) == 1
    assert one.adjusted and one.provider == tiingo.HISTORY_PROVIDER and one.currency == "USD"
    assert 245 <= len(one.closes) <= 265 and len(ten.closes) > 2500
    assert one.dates[-1] == "2026-11-20" and one.dates == sorted(one.dates)
    assert ("2024-06-10", 10.0) in ten.splits and not one.splits
    stats = history.statistics(one)
    assert stats["return_1y_pct"] is not None
    assert "/tiingo/daily/nvda/prices?startDate=" in calls[0].full_url


def test_history_survives_restart_via_database(monkeypatch):
    enable(monkeypatch)
    calls = []
    fake_tiingo(monkeypatch, calls)
    assert history.price_history("AAPL", "2y")
    tiingo._HISTORY.clear(); history._CACHE.clear()  # simulate a process restart
    assert history.price_history("AAPL", "5y")
    assert len(calls) == 1


def test_refusal_backs_off_and_is_shown_without_secret(monkeypatch):
    enable(monkeypatch)
    calls = []
    def refuse(request, timeout=15.0):
        calls.append(request)
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO(b""))
    monkeypatch.setattr(tiingo, "urlopen", refuse)
    monkeypatch.setattr(market_data, "yahoo_quote", lambda *a, **k: None)
    assert market_data.quote_for_asset(get_asset("MSFT")).status == "DEMO"
    monkeypatch.setattr(market_data, "_fetch_json", lambda *a, **k: (_ for _ in ()).throw(market_data.URLError("off")))
    assert history.price_history("MSFT", "1y") is None
    assert len(calls) == 1  # paused after the 429
    h = tiingo.health()
    assert h["last_error"] == "HTTP 429 Too Many Requests" and h["paused_until"] != "not paused"
    assert KEY not in json.dumps(h)


def test_local_budget_caps_requests(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setenv("TIINGO_MAX_REQUESTS_PER_HOUR", "2")
    calls = []
    fake_tiingo(monkeypatch, calls)
    monkeypatch.setattr(market_data, "_fetch_json", lambda *a, **k: (_ for _ in ()).throw(market_data.URLError("off")))
    for symbol in ("AAPL", "MSFT", "NVDA", "AMZN"):
        history.price_history(symbol, "1y")
    assert len(calls) == 2
    assert tiingo.health()["requests_last_hour"] == "2 of 2"


def _register(client, email):
    r = client.post("/api/auth/register", json={"name": "Owner", "email": email, "password": "long-enough-1", "accept_terms": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_private_mode_serves_data_to_owner_only(monkeypatch):
    client = TestClient(app)
    owner = _register(client, "owner@example.com")
    other = _register(client, "other@example.com")
    monkeypatch.setenv("OWNER_USER_IDS", str(owner["user"]["id"]))
    auth = lambda s: {"Authorization": f"Bearer {s['access_token']}"}  # noqa: E731
    assert client.get("/api/scanner").status_code == 401
    assert client.get("/api/scanner", headers=auth(other)).status_code == 403
    assert client.get("/api/scanner", headers=auth(owner)).status_code == 200
    assert client.get("/api/assets/NVDA/history", headers=auth(other)).status_code == 403
    assert client.get("/api/health").status_code in (200, 503)
    status = client.get("/api/status").json()
    assert status["access"]["private_mode"] is True and "tiingo" in status
    assert client.get("/api/auth/me", headers=auth(other)).status_code == 200
    r = client.post("/api/auth/register", json={"name": "New", "email": "new@example.com", "password": "long-enough-1", "accept_terms": True})
    assert r.status_code == 403
    monkeypatch.delenv("OWNER_USER_IDS")
    assert client.get("/api/scanner").status_code == 200


def test_daily_job_only_evaluates_owners_in_private_mode(monkeypatch):
    from app import monitoring
    from app import db as dbm
    monkeypatch.setattr(monitoring, "take_snapshot", lambda *a, **k: 0)
    seen = []
    monkeypatch.setattr(monitoring, "evaluate_user", lambda uid: seen.append(uid) or 0)
    for uid in (1, 2):
        dbm.execute("INSERT INTO alert_rules (user_id, symbol, kind, threshold, active, created_at) VALUES (?, 'AAPL', 'PRICE_ABOVE', 1, 1, 0)", (uid,))
    monkeypatch.setenv("OWNER_USER_IDS", "2")
    assert monitoring.run_daily_job()["users_checked"] == 1 and seen == [2]
    monkeypatch.delenv("OWNER_USER_IDS")
    seen.clear()
    monitoring.run_daily_job()
    assert sorted(seen) == [1, 2]


def test_database_rows_keep_their_fetch_time(monkeypatch):
    enable(monkeypatch)
    calls = []
    fake_tiingo(monkeypatch, calls)
    assert tiingo.daily_history("AAPL")
    from app import db as dbm
    dbm.execute("UPDATE provider_cache SET fetched_at = fetched_at - 43000")
    tiingo._HISTORY.clear()
    assert tiingo.daily_history("AAPL") and len(calls) == 1  # still within 12 h: served from the database
    assert tiingo._HISTORY["AAPL"][0] < __import__("time").time() - 42000  # expires on the original schedule


def test_bad_cache_setting_falls_back_to_default(monkeypatch):
    enable(monkeypatch)
    monkeypatch.setenv("TIINGO_QUOTE_CACHE_SECONDS", "10m")
    monkeypatch.setenv("TIINGO_HISTORY_CACHE_SECONDS", "abc")
    calls = []
    fake_tiingo(monkeypatch, calls)
    assert market_data.quote_for_asset(get_asset("MSFT")).status == "LIVE"
    assert history.price_history("MSFT", "1y")


def test_outage_pauses_retries(monkeypatch):
    enable(monkeypatch)
    calls = []
    def down(request, timeout=15.0):
        calls.append(request)
        raise HTTPError(request.full_url, 503, "Service Unavailable", {}, io.BytesIO(b""))
    monkeypatch.setattr(tiingo, "urlopen", down)
    monkeypatch.setattr(market_data, "_fetch_json", lambda *a, **k: (_ for _ in ()).throw(market_data.URLError("off")))
    for symbol in ("AAPL", "MSFT", "NVDA"):
        history.price_history(symbol, "1y")
    assert len(calls) == 1 and tiingo.health()["paused_until"] != "not paused"
