from __future__ import annotations

import time

import pytest

from app import history, market_data
from app.backtest import trend_backtest
from app.history import PriceHistory, momentum_score, parse_chart, statistics


def chart_payload(closes: list[float | None], adj: list[float | None] | None = None, currency: str = "USD") -> dict:
    start = 1_700_000_000
    stamps = [start + i * 86400 for i in range(len(closes))]
    indicators: dict = {"quote": [{"close": closes}]}
    if adj is not None:
        indicators["adjclose"] = [{"adjclose": adj}]
    return {"chart": {"result": [{"meta": {"currency": currency}, "timestamp": stamps, "indicators": indicators}], "error": None}}


def test_parse_chart_prefers_adjusted_and_skips_nulls():
    h = parse_chart("MSFT", chart_payload([10, None, 12], adj=[9, None, 11]))
    assert h is not None
    assert h.closes == [9.0, 11.0]
    assert len(h.dates) == 2 and h.currency == "USD"


def test_parse_chart_rejects_empty():
    assert parse_chart("X", {"chart": {"result": []}}) is None


def test_history_is_never_synthesised_in_demo_mode():
    assert history.price_history("MSFT", "1y") is None


def test_history_fetch_uses_provider_and_caches(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "live")
    calls = []
    def fake(url, timeout=5.0):
        calls.append(url)
        return chart_payload([100 + i for i in range(300)])
    monkeypatch.setattr(market_data, "_fetch_json", fake)
    h1 = history.price_history("MSFT", "2y")
    h2 = history.price_history("MSFT", "2y")
    assert h1 is not None and h1 is h2 and len(calls) == 1
    assert "range=2y" in calls[0] and "/MSFT?" in calls[0]


def test_unsupported_market_has_no_history(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "live")
    monkeypatch.setattr(market_data, "_fetch_json", lambda *a, **k: pytest.fail("GSE must not be fetched"))
    assert history.price_history("ACCESS", "1y") is None


def test_statistics_and_momentum_on_known_series():
    closes = [100 * (1.001 ** i) for i in range(300)]  # steady uptrend
    stats = statistics(PriceHistory("X", [str(i) for i in range(300)], closes, "USD"))
    assert stats["momentum_12_1_pct"] == pytest.approx((1.001 ** 231 - 1) * 100, abs=0.01)
    assert stats["vs_200d_average_pct"] > 0
    assert stats["max_drawdown_1y_pct"] == 0
    assert momentum_score(stats) == pytest.approx(min(100, 50 + stats["momentum_12_1_pct"] + 10), abs=0.1)
    short = statistics(PriceHistory("X", ["a", "b", "c"], [1, 2, 3], "USD"))
    assert short["momentum_12_1_pct"] is None and momentum_score(short) is None


def test_trend_backtest_exits_a_falling_market_and_reports_benchmark():
    closes = [100 + i for i in range(250)] + [349 - 2 * i for i in range(150)]  # rise then fall
    h = PriceHistory("X", [f"d{i}" for i in range(len(closes))], closes, "USD")
    r = trend_backtest(h, window=50, transaction_cost_bps=0)
    assert r["strategy"]["trade_count"] == 2  # one entry, one exit
    assert r["strategy"]["max_drawdown_pct"] > r["buy_and_hold"]["max_drawdown_pct"]
    assert len(r["dates"]) == len(r["strategy"]["equity_curve"]) == len(r["buy_and_hold"]["equity_curve"])


def test_trend_backtest_has_no_lookahead():
    # Changing a future price must not change any earlier equity value.
    closes = [100 + (i % 7) - (i % 3) + i * 0.2 for i in range(400)]
    h1 = PriceHistory("X", [str(i) for i in range(400)], closes, "USD")
    altered = closes[:-1] + [closes[-1] * 3]
    h2 = PriceHistory("X", [str(i) for i in range(400)], altered, "USD")
    c1 = trend_backtest(h1, 50)["strategy"]["equity_curve"]
    c2 = trend_backtest(h2, 50)["strategy"]["equity_curve"]
    assert c1[:-1] == c2[:-1]


def test_trend_backtest_needs_enough_history():
    with pytest.raises(ValueError):
        trend_backtest(PriceHistory("X", ["a"] * 10, [1.0] * 10, "USD"), 200)


def test_live_history_feeds_scanner_momentum_and_backtest(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("MARKET_DATA_MODE", "live")
    def fake(url, timeout=5.0):
        if "range=5d" in url:  # quote request
            # Real range=5d shape: chartPreviousClose (close before the window), no previousClose, daily bars.
            stamps = [1_699_885_800 + i * 86400 for i in range(5)]  # 14:30 UTC session opens
            return {"chart": {"result": [{"meta": {"regularMarketPrice": 150.0, "chartPreviousClose": 140.0, "currency": "USD", "gmtoffset": -18000,
                                                   "regularMarketTime": stamps[-1] + 6 * 3600 + 1800},
                                          "timestamp": stamps, "indicators": {"quote": [{"close": [141.0, 143.0, 146.0, 148.0, 150.0]}]}}]}}
        return chart_payload([100 * (1.002 ** i) for i in range(600)])
    monkeypatch.setattr(market_data, "_fetch_json", fake)
    client = TestClient(app)
    item = next(x for x in client.get("/api/scanner?limit=100").json()["items"] if x["symbol"] == "MSFT")
    assert item["price_status"] == "LIVE"
    assert item["change_pct"] == pytest.approx((150 / 148 - 1) * 100, abs=0.01)  # not the 5-day move vs 140
    assert item["market_inputs"]["momentum_source"].startswith("12-1 month")
    assert item["market_inputs"]["sentiment_source"] == "Seed value (not live)"
    gse = next(x for x in client.get("/api/scanner?limit=100").json()["items"] if x["symbol"] == "ACCESS")
    assert gse["market_inputs"]["momentum_source"] == "Seed value (not live)"
    bt = client.get("/api/assets/MSFT/backtest?range=5y&window=200").json()
    assert bt["status"] == "LIVE" and bt["strategy"]["trade_count"] == 1
    h = client.get("/api/assets/MSFT/history?range=2y").json()
    assert h["statistics"]["observations"] == 600
