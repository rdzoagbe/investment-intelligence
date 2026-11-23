from __future__ import annotations

from datetime import date

from app import fundamentals
from app.engine import live_pe


def fact(val, start, end, fy, filed, form="10-K"):
    d = {"val": val, "end": end, "fy": fy, "fp": "FY", "form": form, "filed": filed}
    if start:
        d["start"] = start
    return d


FACTS = {"facts": {"us-gaap": {
    # The FY2024 10-K repeats FY2023 and FY2022 as comparatives, all tagged fy=2024.
    "Revenues": {"units": {"USD": [
        fact(100, "2021-07-01", "2022-06-30", 2022, "2022-08-01"),
        fact(110, "2022-07-01", "2023-06-30", 2023, "2023-08-01"),
        fact(100, "2021-07-01", "2022-06-30", 2024, "2024-08-01"),
        fact(110, "2022-07-01", "2023-06-30", 2024, "2024-08-01"),
        fact(132, "2023-07-01", "2024-06-30", 2024, "2024-08-01"),
        fact(40, "2024-01-01", "2024-03-31", 2024, "2024-05-01", form="10-Q"),
        fact(70, "2023-10-01", "2024-06-30", 2024, "2024-08-01"),  # 9-month span: not annual
    ]}},
    # An older tag the issuer stopped using must not win.
    "SalesRevenueNet": {"units": {"USD": [fact(50, "2010-01-01", "2010-12-31", 2010, "2011-02-01")]}},
    "EarningsPerShareDiluted": {"units": {"USD/shares": [fact(4.0, "2023-07-01", "2024-06-30", 2024, "2024-08-01")]}},
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [fact(20, None, "2024-06-30", 2024, "2024-08-01"), fact(15, None, "2023-06-30", 2024, "2024-08-01")]}},
}}}


def test_annual_values_use_period_end_not_filing_year():
    rows = fundamentals._annual_values(FACTS, ("SalesRevenueNet", "Revenues"))
    assert [r["val"] for r in rows] == [132, 110, 100]


def test_eps_is_read_from_per_share_units_and_balances_from_instants():
    assert fundamentals._latest_annual(FACTS, ("EarningsPerShareDiluted",)) == (4.0, 2024)
    assert fundamentals._latest_annual(FACTS, ("CashAndCashEquivalentsAtCarryingValue",)) == (20.0, 2024)


def test_sec_snapshot_growth_from_consecutive_years(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Jane Doe jane@example.com")
    monkeypatch.setattr(fundamentals, "_fetch_json", lambda url: FACTS)
    fundamentals._SEC_CACHE.clear()
    snap = fundamentals.sec_fundamentals("MSFT")
    assert snap is not None and snap.status == "LIVE"
    assert snap.revenue == 132 and snap.fiscal_year == 2024
    assert round(snap.revenue_growth_pct, 2) == 20.0
    assert snap.diluted_eps == 4.0


def test_live_pe_requires_live_price_live_eps_and_usd():
    live = fundamentals.FundamentalSnapshot("X", 2024, 1, 1, 1, 4.0, 0, 0, 1, 1, 1, 0, "SEC Company Facts", "LIVE",
                                            eps_period_end="2024-06-30", diluted_shares=100.0, shares_outstanding=101.0, shares_outstanding_date="2024-10-01")
    demo = fundamentals.FundamentalSnapshot("X", None, 1, 1, 1, 4.0, 0, 0, 1, 1, 1, 0, "Internal", "DEMO")
    today = date(2024, 11, 1)
    assert live_pe(100, True, "USD", live, today) == 25.0
    assert live_pe(100, False, "USD", live, today) is None
    assert live_pe(100, True, "EUR", live, today) is None
    assert live_pe(100, True, "USD", demo, today) is None
