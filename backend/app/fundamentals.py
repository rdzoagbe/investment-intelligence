from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .data import AssetSnapshot, get_asset


@dataclass(frozen=True)
class FundamentalSnapshot:
    symbol: str
    fiscal_year: int | None
    revenue: float | None
    operating_income: float | None
    free_cash_flow: float | None
    diluted_eps: float | None
    total_debt: float | None
    cash: float | None
    revenue_growth_pct: float | None
    operating_margin_pct: float | None
    free_cash_flow_margin_pct: float | None
    net_debt: float | None
    source: str
    status: str


_SEC_CIK = {
    "MSFT": "0000789019", "AAPL": "0000320193", "GOOGL": "0001652044", "META": "0001326801",
    "NVDA": "0001045810", "AVGO": "0001730168", "TSM": "0001046179", "ORCL": "0001341439",
    "CRM": "0001108524", "JPM": "0000019617", "BRK-B": "0001067983", "LLY": "0000059478",
    "JNJ": "0000200406", "KO": "0000021344", "AMZN": "0001018724", "TSLA": "0001318605",
}

_TAGS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "operating_income": ("OperatingIncomeLoss",),
    "cfo": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "eps": ("EarningsPerShareDiluted",),
    "debt_current": ("LongTermDebtCurrent",),
    "debt_noncurrent": ("LongTermDebtNoncurrent",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
}


def sec_user_agent() -> str | None:
    """SEC fair-access policy asks automated clients to declare a real name and contact email.

    We never send a placeholder identity: without SEC_USER_AGENT the SEC adapter stays off.
    """
    value = os.getenv("SEC_USER_AGENT", "").strip()
    return value if "@" in value and "localhost" not in value else None


def _fetch_json(url: str) -> dict[str, object]:
    request = Request(url, headers={"User-Agent": sec_user_agent() or "", "Accept": "application/json"})
    with urlopen(request, timeout=float(os.getenv("FUNDAMENTALS_TIMEOUT", "8"))) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _days(start: str, end: str) -> int | None:
    try:
        from datetime import date
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except (TypeError, ValueError):
        return None


def _annual_values(facts: dict[str, object], tags: tuple[str, ...]) -> list[dict[str, object]]:
    """Fiscal-year values from 10-K filings, one per period end, newest first.

    A 10-K repeats prior years as comparatives under the same `fy`, so values are
    keyed by the period they describe (`end`), not by the filing year. Flow items
    (revenue, cash flow, EPS) must cover roughly a full year; balances have no start.
    """
    units = facts.get("facts", {}).get("us-gaap", {})
    best: list[dict[str, object]] = []
    # Issuers change tags over time; use whichever candidate tag has the most recent period.
    for tag in tags:
        node = units.get(tag)
        if not node:
            continue
        unit_map = node.get("units", {})
        values = unit_map.get("USD") or unit_map.get("USD/shares")
        if not values:
            continue
        by_end: dict[str, dict[str, object]] = {}
        for v in values:
            if v.get("form") not in {"10-K", "10-K/A"} or not isinstance(v.get("val"), (int, float)) or not v.get("end"):
                continue
            if v.get("start"):
                span = _days(str(v["start"]), str(v["end"]))
                if span is None or not 350 <= span <= 380:
                    continue
            end = str(v["end"])
            if end not in by_end or str(v.get("filed", "")) > str(by_end[end].get("filed", "")):
                by_end[end] = v
        ordered = sorted(by_end.values(), key=lambda v: str(v["end"]), reverse=True)
        if ordered and (not best or str(ordered[0]["end"]) > str(best[0]["end"])):
            best = ordered
    return best


def _latest_annual(facts: dict[str, object], tags: tuple[str, ...]) -> tuple[float | None, int | None]:
    values = _annual_values(facts, tags)
    if not values:
        return None, None
    latest = values[0]
    return float(latest["val"]), int(str(latest["end"])[:4])


_SEC_CACHE: dict[str, tuple[float, "FundamentalSnapshot | None"]] = {}


def sec_fundamentals(symbol: str) -> FundamentalSnapshot | None:
    """Annual filings change rarely; cache for 12 hours (failures for 10 minutes)."""
    key = symbol.upper()
    hit = _SEC_CACHE.get(key)
    if hit and time.time() - hit[0] < (43200 if hit[1] else 600):
        return hit[1]
    result = _sec_fundamentals_uncached(key)
    _SEC_CACHE[key] = (time.time(), result)
    return result


def _sec_fundamentals_uncached(symbol: str) -> FundamentalSnapshot | None:
    cik = _SEC_CIK.get(symbol.upper())
    if not cik or not sec_user_agent():
        return None
    try:
        facts = _fetch_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        revenue_values = _annual_values(facts, _TAGS["revenue"])
        revenue = float(revenue_values[0]["val"]) if revenue_values else None
        fy = int(str(revenue_values[0]["end"])[:4]) if revenue_values else None
        prior_revenue = float(revenue_values[1]["val"]) if len(revenue_values) > 1 else None
        operating, _ = _latest_annual(facts, _TAGS["operating_income"])
        cfo, _ = _latest_annual(facts, _TAGS["cfo"])
        capex, _ = _latest_annual(facts, _TAGS["capex"])
        eps, _ = _latest_annual(facts, _TAGS["eps"])
        debt_current, _ = _latest_annual(facts, _TAGS["debt_current"])
        debt_noncurrent, _ = _latest_annual(facts, _TAGS["debt_noncurrent"])
        cash, _ = _latest_annual(facts, _TAGS["cash"])
        fcf = cfo - abs(capex) if cfo is not None and capex is not None else None
        debt = (debt_current or 0) + (debt_noncurrent or 0) if debt_current is not None or debt_noncurrent is not None else None
        growth = ((revenue / prior_revenue) - 1) * 100 if revenue is not None and prior_revenue and prior_revenue > 0 else None
        operating_margin = operating / revenue * 100 if operating is not None and revenue and revenue > 0 else None
        fcf_margin = fcf / revenue * 100 if fcf is not None and revenue and revenue > 0 else None
        net_debt = debt - cash if debt is not None and cash is not None else None
        if revenue is None and operating is None:
            return None
        return FundamentalSnapshot(symbol.upper(), fy, revenue, operating, fcf, eps, debt, cash, growth, operating_margin, fcf_margin, net_debt, "SEC Company Facts", "LIVE")
    except (HTTPError, URLError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def fundamentals_for_asset(asset: AssetSnapshot) -> FundamentalSnapshot:
    mode = os.getenv("FUNDAMENTALS_MODE", "live").strip().lower()
    if mode != "demo":
        live = sec_fundamentals(asset.symbol)
        if live:
            return live
    revenue = asset.price * 1000 / max(asset.pe_ratio, 1)
    operating = asset.operating_margin_pct / 100 * revenue
    fcf = asset.free_cash_flow_margin_pct / 100 * revenue
    debt = max(asset.net_debt_to_ebitda, 0) * asset.price * 100
    cash = asset.price * 100
    return FundamentalSnapshot(asset.symbol, None, revenue, operating, fcf, asset.price / max(asset.pe_ratio, 1), debt, cash, asset.revenue_growth_pct, asset.operating_margin_pct, asset.free_cash_flow_margin_pct, debt - cash, "Internal deterministic dataset", "DEMO")


def fundamentals_for_symbol(symbol: str) -> FundamentalSnapshot | None:
    asset = get_asset(symbol)
    return fundamentals_for_asset(asset) if asset else None
