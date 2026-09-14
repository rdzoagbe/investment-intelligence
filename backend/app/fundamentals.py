from __future__ import annotations

import json
import os
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
    source: str
    status: str


# SEC CIK identifiers for the US seed universe. SEC company facts are public;
# no brokerage credential or market-data key is stored in the application.
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


def _fetch_json(url: str) -> dict[str, object]:
    request = Request(url, headers={
        "User-Agent": os.getenv("SEC_USER_AGENT", "Investment Intelligence research contact@localhost"),
        "Accept": "application/json",
    })
    with urlopen(request, timeout=float(os.getenv("FUNDAMENTALS_TIMEOUT", "8"))) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _latest_annual(facts: dict[str, object], tags: tuple[str, ...]) -> tuple[float | None, int | None]:
    units = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        node = units.get(tag)
        if not node:
            continue
        values = node.get("units", {}).get("USD") or node.get("units", {}).get("USD/shares") or node.get("units", {}).get("shares")
        if not values:
            continue
        annual = [v for v in values if v.get("form") in {"10-K", "10-K/A"} and v.get("fp") == "FY" and isinstance(v.get("val"), (int, float))]
        if not annual:
            continue
        latest = max(annual, key=lambda v: (str(v.get("fy", "")), str(v.get("filed", ""))))
        return float(latest["val"]), int(latest["fy"]) if str(latest.get("fy", "")).isdigit() else None
    return None, None


def sec_fundamentals(symbol: str) -> FundamentalSnapshot | None:
    cik = _SEC_CIK.get(symbol.upper())
    if not cik:
        return None
    try:
        payload = _fetch_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        facts = payload.get("facts", {})
        revenue, fy = _latest_annual(facts, _TAGS["revenue"])
        operating, _ = _latest_annual(facts, _TAGS["operating_income"])
        cfo, _ = _latest_annual(facts, _TAGS["cfo"])
        capex, _ = _latest_annual(facts, _TAGS["capex"])
        eps, _ = _latest_annual(facts, _TAGS["eps"])
        debt_current, _ = _latest_annual(facts, _TAGS["debt_current"])
        debt_noncurrent, _ = _latest_annual(facts, _TAGS["debt_noncurrent"])
        cash, _ = _latest_annual(facts, _TAGS["cash"])
        fcf = cfo - abs(capex) if cfo is not None and capex is not None else None
        debt = (debt_current or 0) + (debt_noncurrent or 0) if debt_current is not None or debt_noncurrent is not None else None
        if revenue is None and operating is None:
            return None
        return FundamentalSnapshot(symbol.upper(), fy, revenue, operating, fcf, eps, debt, cash, "SEC Company Facts", "LIVE")
    except (HTTPError, URLError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def fundamentals_for_asset(asset: AssetSnapshot) -> FundamentalSnapshot:
    mode = os.getenv("FUNDAMENTALS_MODE", "live").strip().lower()
    if mode != "demo":
        live = sec_fundamentals(asset.symbol)
        if live:
            return live
    return FundamentalSnapshot(
        asset.symbol, None,
        asset.price * 1000 / max(asset.pe_ratio, 1),
        asset.operating_margin_pct / 100 * asset.price * 1000,
        asset.free_cash_flow_margin_pct / 100 * asset.price * 1000,
        asset.price / max(asset.pe_ratio, 1),
        max(asset.net_debt_to_ebitda, 0) * asset.price * 100,
        asset.price * 100,
        "Internal deterministic dataset", "DEMO",
    )


def fundamentals_for_symbol(symbol: str) -> FundamentalSnapshot | None:
    asset = get_asset(symbol)
    return fundamentals_for_asset(asset) if asset else None
