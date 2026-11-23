"""G2: scoring provenance, live P/E guards, SEC parsing and analytics regressions."""
from __future__ import annotations

import threading
import time
from datetime import date

import pytest

from app import engine, fundamentals
from app.data import get_asset
from app.fundamentals import FundamentalSnapshot
from app.portfolio import risk_metrics
from app.valuation import scenario_values


def fact(val, start, end, filed, form="10-K", **extra):
    d = {"val": val, "end": end, "form": form, "filed": filed, **extra}
    if start:
        d["start"] = start
    return d


def live_snapshot(**overrides):
    base = dict(symbol="X", fiscal_year=2024, revenue=100.0, operating_income=30.0, free_cash_flow=20.0, diluted_eps=4.0,
                total_debt=10.0, cash=5.0, revenue_growth_pct=12.0, operating_margin_pct=30.0, free_cash_flow_margin_pct=20.0,
                net_debt=5.0, source="SEC Company Facts", status="LIVE", eps_period_end="2024-06-30", diluted_shares=100.0,
                shares_outstanding=99.0, shares_outstanding_date="2024-10-01")
    base.update(overrides)
    return FundamentalSnapshot(**base)


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(engine, "price_history", lambda symbol, range_="2y": None)


# --- C3: neutral bands, never BUY/HOLD/AVOID --------------------------------------------

def test_verdict_is_neutral_band(monkeypatch, no_network):
    monkeypatch.setenv("FUNDAMENTALS_MODE", "demo")
    for symbol in ("MSFT", "NVDA", "ACCESS", "JNJ"):
        scored = engine.score_asset(get_asset(symbol))
        assert scored["band"] == engine.band_label(scored["score"])
        assert scored["verdict"] in {"HIGH_SCORE", "WATCH", "NEUTRAL", "LOW_SCORE"}
        assert scored["verdict"] == scored["band"].upper().replace(" ", "_")


def test_committee_carries_band_not_trade_instruction():
    from app.committee import build_committee
    out = build_committee({"symbol": "X", "score": 90.0, "verdict": "HIGH_SCORE", "band": "High score"}, {})
    assert out["verdict"] == "HIGH_SCORE" and out["band"] == "High score"


# --- C3: currency from the live quote ---------------------------------------------------

def test_currency_comes_from_live_quote(monkeypatch, no_network):
    monkeypatch.setenv("FUNDAMENTALS_MODE", "demo")
    asml = get_asset("ASML")
    live = engine.score_asset(asml, {"price": 700.0, "change_pct": 0.5, "currency": "USD", "status": "LIVE", "provider": "Yahoo"})
    assert live["currency"] == "USD" and live["listing_currency"] == "EUR"
    eur = engine.score_asset(asml, {"price": 650.0, "change_pct": 0.5, "currency": "EUR", "status": "LIVE", "provider": "Yahoo"})
    assert eur["currency"] == "EUR" and "listing_currency" not in eur
    assert engine.score_asset(asml)["currency"] == "EUR"


# --- #27: no seed day change next to a live price ---------------------------------------

def test_live_quote_without_change_keeps_none(monkeypatch, no_network):
    monkeypatch.setenv("FUNDAMENTALS_MODE", "demo")
    msft = get_asset("MSFT")
    scored = engine.score_asset(msft, {"price": 500.0, "change_pct": None, "currency": "USD", "status": "LIVE", "provider": "Yahoo"})
    assert scored["change_pct"] is None and scored["price_status"] == "LIVE"
    assert engine.score_asset(msft)["change_pct"] == msft.change_pct


# --- #2: per-field provenance -------------------------------------------------------------

def test_partial_sec_fundamentals_are_labelled_partial(monkeypatch, no_network):
    snap = live_snapshot(operating_margin_pct=None, free_cash_flow_margin_pct=None)
    monkeypatch.setattr(engine, "fundamentals_for_asset", lambda asset: snap)
    fi = engine.score_asset(get_asset("JPM"))["fundamental_inputs"]
    assert fi["status"] == "PARTIAL"
    assert fi["field_sources"]["revenue_growth_pct"].startswith("SEC Company Facts")
    assert fi["field_sources"]["operating_margin_pct"] == "Seed value (not live)"
    assert fi["field_sources"]["free_cash_flow_margin_pct"] == "Seed value (not live)"
    assert "operating_margin_pct" in fi["source"]


def test_full_sec_fundamentals_are_live_and_demo_is_demo(monkeypatch, no_network):
    monkeypatch.setattr(engine, "fundamentals_for_asset", lambda asset: live_snapshot())
    assert engine.score_asset(get_asset("MSFT"))["fundamental_inputs"]["status"] == "LIVE"
    monkeypatch.setenv("FUNDAMENTALS_MODE", "demo")
    monkeypatch.setattr(engine, "fundamentals_for_asset", fundamentals.fundamentals_for_asset)
    fi = engine.score_asset(get_asset("MSFT"))["fundamental_inputs"]
    assert fi["status"] == "DEMO" and set(fi["field_sources"].values()) == {"Seed value (not live)"}


def test_thesis_names_field_sources(monkeypatch, no_network):
    monkeypatch.setenv("FUNDAMENTALS_MODE", "demo")
    monkeypatch.setenv("MARKET_DATA_MODE", "demo")
    analysis = engine.analyze_asset("MSFT")
    assert "tracked fundamental source" not in " ".join(analysis["thesis"]["bull"])
    assert "Seed value (not live)" in analysis["thesis"]["bull"][0]


# --- #17: balance-sheet input is labelled ---------------------------------------------------

def test_balance_sheet_source_is_labelled_seed(monkeypatch, no_network):
    monkeypatch.setenv("FUNDAMENTALS_MODE", "demo")
    mi = engine.score_asset(get_asset("ORCL"))["market_inputs"]
    assert mi["balance_sheet_source"] == "Seed value (not live)"
    assert mi["net_debt_to_ebitda"] == get_asset("ORCL").net_debt_to_ebitda


# --- #26: live P/E guards ---------------------------------------------------------------------

def test_live_pe_withheld_after_split():
    # NVDA-like: pre-split 10-K EPS, 10x more shares on the latest cover page.
    snap = live_snapshot(diluted_eps=11.93, diluted_shares=2.494e9, shares_outstanding=24.5e9, eps_period_end="2024-01-28")
    pe, reason = engine.live_pe_assessment(120.0, True, "USD", snap, today=date(2024, 9, 1))
    assert pe is None and "split" in reason


def test_live_pe_withheld_when_eps_is_stale_or_shares_unknown():
    stale = live_snapshot(eps_period_end="2023-01-31")
    assert engine.live_pe(100, True, "USD", stale, today=date(2024, 9, 1)) is None
    unknown = live_snapshot(shares_outstanding=None)
    assert engine.live_pe(100, True, "USD", unknown, today=date(2024, 9, 1)) is None
    ok = live_snapshot()
    assert engine.live_pe(100, True, "USD", ok, today=date(2024, 9, 1)) == 25.0


def test_withheld_pe_is_labelled_seed_with_reason(monkeypatch, no_network):
    snap = live_snapshot(diluted_shares=1e9, shares_outstanding=10e9, eps_period_end=date.today().isoformat())
    monkeypatch.setattr(engine, "fundamentals_for_asset", lambda asset: snap)
    mi = engine.score_asset(get_asset("NVDA"), {"price": 120.0, "change_pct": 1.0, "currency": "USD", "status": "LIVE", "provider": "Yahoo"})["market_inputs"]
    assert mi["pe_source"] == "Seed value (not live)" and mi["pe_ratio"] == get_asset("NVDA").pe_ratio
    assert "split" in mi["pe_note"]


# --- #15: valuation ordering -------------------------------------------------------------------

@pytest.mark.parametrize("args", [(18.2, 18, 6.5), (100, -5, 20), (50, 3, 4), (415.2, 14, 35), (10, -95, 9)])
def test_bear_never_exceeds_base(args):
    by = {s["label"]: s for s in scenario_values(*args)}
    assert by["Bear"]["fair_value"] <= by["Base"]["fair_value"] <= by["Bull"]["fair_value"]
    assert by["Bear"]["multiple"] <= by["Base"]["multiple"] and by["Bear"]["growth_pct"] <= by["Base"]["growth_pct"]


# --- #5: Sharpe annualisation --------------------------------------------------------------------

def test_sharpe_matches_hand_computation():
    returns = [0.004, -0.002, 0.006, 0.003, -0.004, 0.005, 0.002, -0.001]
    mean = sum(returns) / len(returns)
    sd = (sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
    expected = round(mean * 252 / (sd * 252 ** 0.5), 2)
    result = risk_metrics(returns)
    assert result["sharpe"] == expected
    assert 7.0 < result["sharpe"] < 7.4


# --- #28 / #16: SEC parsing --------------------------------------------------------------------

def _facts():
    return {"facts": {
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
                fact(30, "2023-01-01", "2023-12-31", "2024-02-15"), fact(25, "2022-01-01", "2022-12-31", "2023-02-15")]}},
            "Revenues": {"units": {"USD": [
                fact(170, "2023-01-01", "2023-12-31", "2024-02-15"), fact(150, "2022-01-01", "2022-12-31", "2023-02-15")]}},
            "OperatingIncomeLoss": {"units": {"USD": [fact(40, "2023-01-01", "2023-12-31", "2024-02-15")]}},
            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [fact(60, "2023-01-01", "2023-12-31", "2024-02-15")]}},
            # Capex tag abandoned years ago: must not be combined with current CFO.
            "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [fact(5, "2017-01-01", "2017-12-31", "2018-02-15")]}},
            "LongTermDebtCurrent": {"units": {"USD": [fact(99, None, "2017-12-31", "2018-02-15")]}},
            "LongTermDebtNoncurrent": {"units": {"USD": [fact(50, None, "2023-12-31", "2024-02-15")]}},
            "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [fact(20, None, "2023-12-31", "2024-02-15")]}},
            "EarningsPerShareDiluted": {"units": {"USD/shares": [fact(5.0, "2023-01-01", "2023-12-31", "2024-02-15")]}},
            "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [fact(1000, "2023-01-01", "2023-12-31", "2024-02-15")]}},
        },
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            fact(600, None, "2024-04-20", "2024-05-01", form="10-Q", accn="a2", frame="A"),
            fact(390, None, "2024-04-20", "2024-05-01", form="10-Q", accn="a2", frame="B"),
            fact(980, None, "2024-01-20", "2024-02-15", accn="a1"),
        ]}}},
    }}


def test_revenue_prefers_total_tag_over_asc606_subset():
    rows = fundamentals._annual_values(_facts(), fundamentals._TAGS["revenue"], prefer_larger_on_tie=True)
    assert rows[0]["val"] == 170 and rows[1]["val"] == 150
    # Even if the subset tag is listed first, the larger total wins the tie.
    rows = fundamentals._annual_values(_facts(), ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"), prefer_larger_on_tie=True)
    assert rows[0]["val"] == 170


def test_metrics_from_other_fiscal_years_are_not_mixed_in():
    snap = fundamentals._snapshot_from_facts("JPM", _facts())
    assert snap.revenue == 170 and snap.fiscal_year == 2023
    assert snap.operating_margin_pct == pytest.approx(40 / 170 * 100)
    assert snap.free_cash_flow is None and snap.free_cash_flow_margin_pct is None  # capex is from 2017
    assert snap.total_debt == 50  # 2017 current debt is ignored
    assert snap.net_debt == 30
    assert snap.eps_period_end == "2023-12-31" and snap.diluted_shares == 1000
    assert snap.shares_outstanding == 990 and snap.shares_outstanding_date == "2024-04-20"


# --- #29 / #48: single-flight and structural-miss caching -------------------------------

def test_sec_fetch_is_single_flight(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Jane Doe jane@example.com")
    fundamentals._SEC_CACHE.clear()
    calls = []

    def slow_fetch(url):
        calls.append(url)
        time.sleep(0.2)
        return _facts()

    monkeypatch.setattr(fundamentals, "_fetch_json", slow_fetch)
    results = []
    threads = [threading.Thread(target=lambda: results.append(fundamentals.sec_fundamentals("MSFT"))) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert len(results) == 6 and all(r is not None and r.revenue == 170 for r in results)
    fundamentals._SEC_CACHE.clear()


def test_structural_miss_is_cached_long_and_network_errors_short(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Jane Doe jane@example.com")
    fundamentals._SEC_CACHE.clear()
    monkeypatch.setattr(fundamentals, "_fetch_json", lambda url: {"facts": {"ifrs-full": {"Revenue": {}}}})
    assert fundamentals.sec_fundamentals("MSFT") is None
    assert fundamentals._SEC_CACHE["MSFT"][2] >= 86400

    def boom(url):
        raise OSError("connection reset")

    monkeypatch.setattr(fundamentals, "_fetch_json", boom)
    assert fundamentals.sec_fundamentals("AAPL") is None
    assert fundamentals._SEC_CACHE["AAPL"][2] == 600
    fundamentals._SEC_CACHE.clear()


def test_tsm_is_not_fetched_from_sec():
    assert "TSM" not in fundamentals._SEC_CIK
