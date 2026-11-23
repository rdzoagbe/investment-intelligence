"""G1: true previous close, provider error handling, symbol mapping, FX rates, adjusted history."""
from __future__ import annotations

import http.client
from datetime import date, timedelta
from urllib.error import URLError

import pytest

from app import history, market_data
from app.backtest import trend_backtest
from app.data import get_asset
from app.history import PriceHistory, parse_chart, statistics

# Mon 2023-11-13 .. Fri 2023-11-17, daily bars stamped at the 09:30 ET open (14:30 UTC).
NY_OFFSET = -18000
STAMPS = [1_699_885_800 + i * 86400 for i in range(5)]
CLOSES = [400.0, 402.0, 405.0, 408.0, 410.0]


def yahoo_5d(price: float, closes: list[float | None], stamps: list[int], market_time: int | None, currency: str = "USD", **meta_extra) -> dict:
    """Realistic Yahoo v8 chart payload for range=5d&interval=1d: chartPreviousClose is the
    close BEFORE the window and meta has no previousClose."""
    meta = {"currency": currency, "symbol": "MSFT", "exchangeName": "NMS", "instrumentType": "EQUITY", "gmtoffset": NY_OFFSET,
            "timezone": "EST", "exchangeTimezoneName": "America/New_York", "regularMarketPrice": price, "chartPreviousClose": 395.0,
            "priceHint": 2, "dataGranularity": "1d", "range": "5d", "validRanges": ["1d", "5d", "1mo"],
            "currentTradingPeriod": {"pre": {"start": STAMPS[-1] - 19800, "end": STAMPS[-1], "gmtoffset": NY_OFFSET},
                                     "regular": {"start": STAMPS[-1], "end": STAMPS[-1] + 23400, "gmtoffset": NY_OFFSET},
                                     "post": {"start": STAMPS[-1] + 23400, "end": STAMPS[-1] + 37800, "gmtoffset": NY_OFFSET}}}
    if market_time is not None:
        meta["regularMarketTime"] = market_time
    meta.update(meta_extra)
    return {"chart": {"result": [{"meta": meta, "timestamp": stamps,
                                  "indicators": {"quote": [{"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1] * len(closes)}],
                                                 "adjclose": [{"adjclose": closes}]}}], "error": None}}


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "live")
    market_data._FX_CACHE.clear()
    yield
    market_data._FX_CACHE.clear()


def _serve(monkeypatch, payload):
    calls: list[str] = []

    def fake(url, timeout=5.0):
        calls.append(url)
        return payload(url) if callable(payload) else payload
    monkeypatch.setattr(market_data, "_fetch_json", fake)
    return calls


def test_closed_session_uses_prior_bar_not_chart_previous_close(live, monkeypatch):
    _serve(monkeypatch, yahoo_5d(410.0, CLOSES, STAMPS, STAMPS[-1] + 23400))  # 16:00 ET Friday
    q = market_data.yahoo_quote("MSFT")
    assert q is not None and q.status == "LIVE"
    assert q.previous_close == 408.0
    assert q.change_pct == pytest.approx((410 / 408 - 1) * 100, abs=0.001)  # ~ +0.49%, not +3.8% vs 395


def test_in_progress_session_bar(live, monkeypatch):
    closes = CLOSES[:-1] + [411.5]
    _serve(monkeypatch, yahoo_5d(411.5, closes, STAMPS, STAMPS[-1] + 3600))  # 10:30 ET, session running
    q = market_data.yahoo_quote("MSFT")
    assert q.previous_close == 408.0
    assert q.change_pct == pytest.approx((411.5 / 408 - 1) * 100, abs=0.001)


def test_premarket_today_bar_without_close(live, monkeypatch):
    # Monday pre-market: Yahoo has added Monday's bar with a null close, last trade was Friday 16:00 ET.
    stamps = STAMPS + [STAMPS[-1] + 3 * 86400]
    closes: list[float | None] = CLOSES + [None]
    _serve(monkeypatch, yahoo_5d(410.0, closes, stamps, STAMPS[-1] + 23400))
    q = market_data.yahoo_quote("MSFT")
    assert q.previous_close == 408.0  # Friday's move, Thursday's close as base


def test_previous_close_unknown_is_none_not_seed(live, monkeypatch):
    payload = {"chart": {"result": [{"meta": {"regularMarketPrice": 410.0, "chartPreviousClose": 395.0, "currency": "USD", "regularMarketTime": STAMPS[-1]}}]}}
    _serve(monkeypatch, payload)
    q = market_data.yahoo_quote("MSFT")
    assert q is not None and q.status == "LIVE" and q.price == 410.0
    assert q.previous_close is None and q.change_pct is None


def test_single_bar_cannot_determine_previous(live, monkeypatch):
    _serve(monkeypatch, yahoo_5d(410.0, [410.0], [STAMPS[-1]], STAMPS[-1] + 23400))
    q = market_data.yahoo_quote("MSFT")
    assert q.previous_close is None and q.change_pct is None


def test_meta_previous_close_used_only_without_bars(live, monkeypatch):
    payload = {"chart": {"result": [{"meta": {"regularMarketPrice": 150.0, "previousClose": 148.0, "chartPreviousClose": 120.0, "currency": "USD"}}]}}
    _serve(monkeypatch, payload)
    q = market_data.yahoo_quote("MSFT")
    assert q.previous_close == 148.0


@pytest.mark.parametrize("exc", [http.client.RemoteDisconnected("closed"), http.client.IncompleteRead(b"x", 10), ConnectionResetError(),
                                 OSError("ssl"), ValueError("bad json")])
def test_transport_errors_never_escape(live, monkeypatch, exc):
    def boom(url, timeout=5.0):
        raise exc
    monkeypatch.setattr(market_data, "_fetch_json", boom)
    assert market_data.yahoo_quote("MSFT") is None
    q = market_data.quote_for_asset(get_asset("MSFT"))
    assert q.status == "DEMO"
    assert history.price_history("MSFT", "1y") is None
    assert market_data.fx_rate("EUR", "USD")["status"] == "UNAVAILABLE"
    assert all(item["status"] == "UNAVAILABLE" for item in market_data.index_quotes())


def test_fetch_json_wraps_unwrapped_transport_errors(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            raise http.client.IncompleteRead(b"partial", 100)
    monkeypatch.setattr(market_data, "urlopen", lambda *a, **k: Resp())
    with pytest.raises(URLError):
        market_data._fetch_json("https://example.invalid/x")
    monkeypatch.setattr(market_data, "urlopen", lambda *a, **k: (_ for _ in ()).throw(http.client.RemoteDisconnected("x")))
    with pytest.raises(URLError):
        market_data._fetch_json("https://example.invalid/x")


def test_failure_is_cached(live, monkeypatch):
    calls = []

    def boom(url, timeout=5.0):
        calls.append(url)
        raise http.client.RemoteDisconnected("x")
    monkeypatch.setattr(market_data, "_fetch_json", boom)
    market_data.yahoo_quote("MSFT")
    market_data.yahoo_quote("MSFT")
    assert len(calls) == 1


def test_symbol_mapping_and_provider_currency(live, monkeypatch):
    assert market_data._provider_symbol("ASML") == "ASML.AS"
    assert market_data._provider_symbol("SAP") == "SAP.DE"
    assert market_data._provider_symbol("VISA") == "V"
    assert market_data._provider_symbol("ACCESS") is None
    calls = _serve(monkeypatch, yahoo_5d(700.0, CLOSES, STAMPS, STAMPS[-1] + 23400, currency="EUR"))
    q = market_data.quote_for_asset(get_asset("ASML"))
    assert "/ASML.AS?" in calls[0] and q.currency == "EUR" and q.status == "LIVE"


def test_fx_identity_and_demo(monkeypatch):
    assert market_data.fx_rate("USD", "USD") == {"rate": 1.0, "status": "IDENTITY", "source": None, "timestamp": None}
    monkeypatch.setattr(market_data, "_fetch_json", lambda *a, **k: pytest.fail("demo mode must not fetch"))
    r = market_data.fx_rate("EUR", "USD")  # conftest sets demo mode
    assert r["status"] == "UNAVAILABLE" and r["rate"] is None


def test_fx_live_and_cached(live, monkeypatch):
    calls = _serve(monkeypatch, {"chart": {"result": [{"meta": {"currency": "USD", "symbol": "EURUSD=X", "regularMarketPrice": 1.0842, "regularMarketTime": 1_700_000_000}}]}})
    r1 = market_data.fx_rate("EUR", "USD")
    r2 = market_data.fx_rate("eur", "usd")
    assert r1 == r2 == {"rate": 1.0842, "status": "LIVE", "source": "Yahoo Finance chart API (EURUSD=X)", "timestamp": 1_700_000_000}
    assert len(calls) == 1 and "/EURUSD%3DX?" in calls[0]


def test_fx_never_invents_a_rate(live, monkeypatch):
    _serve(monkeypatch, {"chart": {"result": [], "error": {"code": "Not Found"}}})
    assert market_data.fx_rate("GHS", "USD") == {"rate": None, "status": "UNAVAILABLE", "source": None, "timestamp": None}
    assert market_data.fx_rate("", "USD")["status"] == "UNAVAILABLE"
    assert market_data.fx_rate("US D", "USD")["status"] == "UNAVAILABLE"


def test_fx_minor_units(live, monkeypatch):
    _serve(monkeypatch, {"chart": {"result": [{"meta": {"regularMarketPrice": 1.25, "regularMarketTime": 1}}]}})
    assert market_data.fx_rate("GBp", "USD")["rate"] == pytest.approx(0.0125)
    assert market_data.fx_rate("GBp", "GBP")["rate"] == pytest.approx(0.01)


# --- history --------------------------------------------------------------------------

def _weekday_dates(end: date, days: int) -> list[date]:
    out, d = [], end - timedelta(days=days)
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_parse_chart_flags_unadjusted_fallback():
    payload = {"chart": {"result": [{"meta": {"currency": "USD"}, "timestamp": STAMPS, "indicators": {"quote": [{"close": CLOSES}]}}]}}
    h = parse_chart("NVDA", payload)
    assert h is not None and h.adjusted is False
    assert "adjusted close" not in h.provider and "dividends not included" in h.provider
    assert h.as_dict()["adjusted"] is False
    bt_closes = [100 + i for i in range(260)]
    bt = trend_backtest(PriceHistory("X", [str(i) for i in range(260)], bt_closes, "USD"), window=50)
    assert bt["adjusted"] is False and not any(c.startswith("Uses adjusted closes") for c in bt["caveats"])


def test_parse_chart_flags_adjusted():
    payload = yahoo_5d(410.0, CLOSES, STAMPS, STAMPS[-1])
    h = parse_chart("MSFT", payload)
    assert h.adjusted is True and h.provider == history.PROVIDER and h.as_dict()["adjusted"] is True
    bt_closes = [100 + i for i in range(260)]
    bt = trend_backtest(PriceHistory("X", [str(i) for i in range(260)], bt_closes, "USD", adjusted=True), window=50)
    assert bt["adjusted"] is True and bt["caveats"][1].startswith("Uses adjusted closes")


def test_statistics_on_one_year_range_has_return_and_momentum():
    # What a Yahoo range=1y returns: ~251 bars (weekdays minus exchange holidays), first bar after the start date.
    days = [d for i, d in enumerate(_weekday_dates(date(2026, 11, 20), 364)) if i % 25 != 7]
    assert len(days) < 253
    closes = [100 * (1.001 ** i) for i in range(len(days))]
    stats = statistics(PriceHistory("X", [d.isoformat() for d in days], closes, "USD", adjusted=True))
    assert stats["return_1y_pct"] == pytest.approx((closes[-1] / closes[0] - 1) * 100, abs=0.01)
    month_ago = max(i for i, d in enumerate(days) if d <= days[-1] - timedelta(days=30))
    assert stats["momentum_12_1_pct"] == pytest.approx((closes[month_ago] / closes[0] - 1) * 100, abs=0.01)
    assert stats["volatility_1y_pct"] is not None and stats["observations"] == len(days)


def test_statistics_uses_calendar_year_on_longer_history():
    days = _weekday_dates(date(2026, 11, 20), 730)
    closes = [50.0 + i for i in range(len(days))]
    stats = statistics(PriceHistory("X", [d.isoformat() for d in days], closes, "USD"))
    base = max(i for i, d in enumerate(days) if d <= date(2025, 11, 20))
    assert stats["return_1y_pct"] == pytest.approx((closes[-1] / closes[base] - 1) * 100, abs=0.01)


def test_statistics_short_history_has_no_one_year_values():
    days = _weekday_dates(date(2026, 11, 20), 180)
    stats = statistics(PriceHistory("X", [d.isoformat() for d in days], [100.0 + i for i in range(len(days))], "USD"))
    assert stats["return_1y_pct"] is None and stats["momentum_12_1_pct"] is None
