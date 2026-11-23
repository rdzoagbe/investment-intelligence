from __future__ import annotations

import io
from urllib.error import HTTPError

from fastapi.testclient import TestClient

from app import history, market_data
from app.data import get_asset
from app.main import app


def test_rate_limit_is_recorded_shown_and_backed_off(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "live")
    calls = []
    def refuse(request, timeout=5.0):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO(b"Edge: Too Many Requests"))
    monkeypatch.setattr(market_data, "urlopen", refuse)
    q = market_data.quote_for_asset(get_asset("MSFT"))
    assert q.status == "DEMO" and len(calls) == 1
    health = market_data.provider_health()
    assert health["last_error"] == "HTTP 429 Too Many Requests" and health["paused_until"] != "not paused"
    market_data._CACHE.clear()
    assert market_data.quote_for_asset(get_asset("NVDA")).status == "DEMO"
    assert history.price_history("NVDA", "1y") is None
    assert len(calls) == 1  # paused: no further requests while backing off
    status = TestClient(app).get("/api/status").json()["market_data"]
    assert status["last_error"] == "HTTP 429 Too Many Requests" and status["consecutive_failures"] >= 1


def test_success_is_recorded(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "live")
    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(market_data, "urlopen", lambda request, timeout=5.0: Resp(b'{"chart":{"result":[{"meta":{"regularMarketPrice":10,"currency":"USD"}}]}}'))
    assert market_data.quote_for_asset(get_asset("MSFT")).status == "LIVE"
    assert market_data.provider_health()["last_success"] != "never"
