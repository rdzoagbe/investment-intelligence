from __future__ import annotations

import http.client
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, fields
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import db
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
    # Provenance for the live P/E guard: the period the EPS describes, the weighted
    # diluted share count for that period, and the latest cover-page share count.
    eps_period_end: str | None = None
    diluted_shares: float | None = None
    shares_outstanding: float | None = None
    shares_outstanding_date: str | None = None


# TSM is deliberately absent: TSMC files 20-F reports in the ifrs-full taxonomy (TWD),
# which this us-gaap/10-K adapter cannot parse, so it always uses labelled seed values.
_SEC_CIK = {
    "MSFT": "0000789019", "AAPL": "0000320193", "GOOGL": "0001652044", "META": "0001326801",
    "NVDA": "0001045810", "AVGO": "0001730168", "ORCL": "0001341439",
    "CRM": "0001108524", "JPM": "0000019617", "BRK-B": "0001067983", "LLY": "0000059478",
    "JNJ": "0000200406", "KO": "0000021344", "AMZN": "0001018724", "TSLA": "0001318605",
}

_TAGS = {
    # Total-revenue tags first: banks and insurers report the ASC 606 tag only for in-scope fee income.
    "revenue": ("Revenues", "RevenuesNetOfInterestExpense", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"),
    "operating_income": ("OperatingIncomeLoss",),
    "cfo": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    "eps": ("EarningsPerShareDiluted",),
    "diluted_shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "debt_current": ("LongTermDebtCurrent", "DebtCurrent"),
    "debt_noncurrent": ("LongTermDebtNoncurrent",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
}


def sec_user_agent() -> str | None:
    """SEC fair-access policy asks automated clients to declare a real name and contact email.

    We never send a placeholder identity: without SEC_USER_AGENT the SEC adapter stays off.
    """
    value = os.getenv("SEC_USER_AGENT", "").strip()
    return value if "@" in value and "localhost" not in value else None


# SEC fair access: at most a few concurrent downloads and well under 10 requests per second.
_SEC_SEMAPHORE = threading.BoundedSemaphore(int(os.getenv("SEC_MAX_CONCURRENCY", "2")))
_SEC_PACE_LOCK = threading.Lock()
_SEC_MIN_INTERVAL = 0.2
_sec_last_request = 0.0


def _fetch_json(url: str) -> dict[str, object]:
    global _sec_last_request
    with _SEC_SEMAPHORE:
        with _SEC_PACE_LOCK:
            wait = _SEC_MIN_INTERVAL - (time.monotonic() - _sec_last_request)
            if wait > 0:
                time.sleep(wait)
            _sec_last_request = time.monotonic()
        request = Request(url, headers={"User-Agent": sec_user_agent() or "", "Accept": "application/json"})
        with urlopen(request, timeout=float(os.getenv("FUNDAMENTALS_TIMEOUT", "8"))) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))


def _days(start: str, end: str) -> int | None:
    try:
        from datetime import date
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except (TypeError, ValueError):
        return None


def _tag_annual_values(units: dict[str, object], tag: str) -> list[dict[str, object]]:
    node = units.get(tag)
    if not node:
        return []
    unit_map = node.get("units", {})
    values = unit_map.get("USD") or unit_map.get("USD/shares") or unit_map.get("shares")
    if not values:
        return []
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
    return sorted(by_end.values(), key=lambda v: str(v["end"]), reverse=True)


def _annual_values(facts: dict[str, object], tags: tuple[str, ...], prefer_larger_on_tie: bool = False) -> list[dict[str, object]]:
    """Fiscal-year values from 10-K filings, one per period end, newest first.

    A 10-K repeats prior years as comparatives under the same `fy`, so values are
    keyed by the period they describe (`end`), not by the filing year. Flow items
    (revenue, cash flow, EPS) must cover roughly a full year; balances have no start.
    """
    units = facts.get("facts", {}).get("us-gaap", {})
    best: list[dict[str, object]] = []
    # Issuers change tags over time; use whichever candidate tag has the most recent period.
    # On a tie, the earlier tag wins unless prefer_larger_on_tie picks the larger latest value
    # (revenue: a total tag always covers at least the ASC 606 subset).
    for tag in tags:
        ordered = _tag_annual_values(units, tag)
        if not ordered:
            continue
        if not best or str(ordered[0]["end"]) > str(best[0]["end"]):
            best = ordered
        elif prefer_larger_on_tie and str(ordered[0]["end"]) == str(best[0]["end"]) and float(ordered[0]["val"]) > float(best[0]["val"]):
            best = ordered
    return best


def _latest_annual(facts: dict[str, object], tags: tuple[str, ...]) -> tuple[float | None, int | None]:
    values = _annual_values(facts, tags)
    if not values:
        return None, None
    latest = values[0]
    return float(latest["val"]), int(str(latest["end"])[:4])


def _value_at(facts: dict[str, object], tags: tuple[str, ...], end: str | None, tolerance_days: int = 7) -> float | None:
    """The annual value for the period ending at `end` (within a few days), from any candidate tag.

    Values from other fiscal years are never mixed in: a tag the issuer stopped using
    years ago must not be combined with current revenue.
    """
    if not end:
        return None
    units = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        for v in _tag_annual_values(units, tag):
            gap = _days(str(v["end"]), end)
            if gap is not None and abs(gap) <= tolerance_days:
                return float(v["val"])
    return None


def _latest_shares_outstanding(facts: dict[str, object]) -> tuple[float | None, str | None]:
    """Latest cover-page share count (dei), summed across share classes reported in one filing."""
    node = facts.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding") or {}
    values = [v for v in (node.get("units", {}).get("shares") or []) if isinstance(v.get("val"), (int, float)) and v.get("end")]
    if not values:
        return None, None
    latest_end = max(str(v["end"]) for v in values)
    at_end = [v for v in values if str(v["end"]) == latest_end]
    latest_filed = max(str(v.get("filed", "")) for v in at_end)
    rows = {(str(v.get("accn", "")), v.get("frame"), float(v["val"])) for v in at_end if str(v.get("filed", "")) == latest_filed}
    return sum(r[2] for r in rows), latest_end


_SEC_CACHE: dict[str, tuple[float, "FundamentalSnapshot | None", float]] = {}
_SEC_CACHE_LOCK = threading.Lock()
_SEC_KEY_LOCKS: dict[str, threading.Lock] = {}
_SUCCESS_TTL = 43200.0          # 12 hours
_TRANSIENT_FAILURE_TTL = 600.0  # network errors: retry after 10 minutes
_STRUCTURAL_FAILURE_TTL = 7 * 86400.0  # fetched fine but nothing usable (e.g. a 20-F/IFRS filer)


class _StructuralMiss(Exception):
    """The filing data was retrieved but contains no usable us-gaap 10-K facts."""


def sec_fundamentals(symbol: str) -> FundamentalSnapshot | None:
    """Annual filings change rarely; cache for 12 hours.

    Single-flight per symbol: concurrent callers wait for one download instead of each
    fetching and parsing the multi-MB companyfacts document. Network failures are retried
    after 10 minutes; structural misses (no usable us-gaap data) are cached for a week.
    """
    key = symbol.upper()

    def cached() -> tuple[bool, FundamentalSnapshot | None]:
        with _SEC_CACHE_LOCK:
            hit = _SEC_CACHE.get(key)
        if hit and time.time() - hit[0] < hit[2]:
            return True, hit[1]
        return False, None

    found, value = cached()
    if found:
        return value
    with _SEC_CACHE_LOCK:
        key_lock = _SEC_KEY_LOCKS.setdefault(key, threading.Lock())
    with key_lock:
        found, value = cached()
        if found:
            return value
        stored = _db_load(key)
        if stored is not None:
            fetched_at, result, ttl = stored
            with _SEC_CACHE_LOCK:
                _SEC_CACHE[key] = (fetched_at, result, ttl)
            return result
        try:
            result = _sec_fundamentals_uncached(key)
            ttl = _SUCCESS_TTL if result else _TRANSIENT_FAILURE_TTL
            if result is not None:
                _db_store(key, result)
        except _StructuralMiss:
            result, ttl = None, _STRUCTURAL_FAILURE_TTL
            _db_store(key, None)
        with _SEC_CACHE_LOCK:
            _SEC_CACHE[key] = (time.time(), result, ttl)
        return result


# Parsed snapshots (a few hundred bytes, not the multi-MB filing) are also kept in the database so a
# restarted free server does not download every company's filings again before the first page loads.
_SNAPSHOT_FIELDS = {f.name for f in fields(FundamentalSnapshot)}


def _db_load(key: str) -> tuple[float, "FundamentalSnapshot | None", float] | None:
    try:
        row = db.fetch_one("SELECT fetched_at, payload FROM provider_cache WHERE cache_key=?", (f"sec:snapshot:{key}",))
    except Exception:  # noqa: BLE001 - optional cache; a database problem must not break fundamentals
        return None
    if not row:
        return None
    try:
        payload = json.loads(row["payload"])
        fetched_at = float(row["fetched_at"])
        snap = payload.get("snapshot")
        result = FundamentalSnapshot(**{k: v for k, v in snap.items() if k in _SNAPSHOT_FIELDS}) if isinstance(snap, dict) else None
    except (TypeError, ValueError, AttributeError):
        return None
    ttl = _SUCCESS_TTL if result is not None else _STRUCTURAL_FAILURE_TTL
    if time.time() - fetched_at >= ttl:
        return None
    return fetched_at, result, ttl


def _db_store(key: str, result: "FundamentalSnapshot | None") -> None:
    try:
        db.execute("INSERT INTO provider_cache (cache_key, fetched_at, payload) VALUES (?, ?, ?) "
                   "ON CONFLICT (cache_key) DO UPDATE SET fetched_at = excluded.fetched_at, payload = excluded.payload",
                   (f"sec:snapshot:{key}", int(time.time()), json.dumps({"snapshot": asdict(result) if result else None})))
    except Exception:  # noqa: BLE001 - optional cache
        pass


def _sec_fundamentals_uncached(symbol: str) -> FundamentalSnapshot | None:
    cik = _SEC_CIK.get(symbol.upper())
    if not cik or not sec_user_agent():
        return None
    try:
        facts = _fetch_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    except (HTTPError, URLError, TimeoutError, OSError, http.client.HTTPException, ValueError, TypeError, KeyError):
        return None
    try:
        return _snapshot_from_facts(symbol, facts)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise _StructuralMiss(str(exc)) from exc


def _snapshot_from_facts(symbol: str, facts: dict[str, object]) -> FundamentalSnapshot:
    revenue_values = _annual_values(facts, _TAGS["revenue"], prefer_larger_on_tie=True)
    revenue = float(revenue_values[0]["val"]) if revenue_values else None
    end = str(revenue_values[0]["end"]) if revenue_values else None
    fy = int(end[:4]) if end else None
    # Growth only against the period exactly one year earlier from the same tag.
    prior_revenue = None
    if len(revenue_values) > 1:
        gap = _days(str(revenue_values[1]["end"]), end) if end else None
        if gap is not None and 350 <= gap <= 380:
            prior_revenue = float(revenue_values[1]["val"])
    if end is None:
        operating = cfo = capex = eps = diluted_shares = debt_current = debt_noncurrent = cash = None
    else:
        # Every metric must describe the same fiscal period as revenue.
        operating = _value_at(facts, _TAGS["operating_income"], end)
        cfo = _value_at(facts, _TAGS["cfo"], end)
        capex = _value_at(facts, _TAGS["capex"], end)
        eps = _value_at(facts, _TAGS["eps"], end)
        diluted_shares = _value_at(facts, _TAGS["diluted_shares"], end)
        debt_current = _value_at(facts, _TAGS["debt_current"], end)
        debt_noncurrent = _value_at(facts, _TAGS["debt_noncurrent"], end)
        cash = _value_at(facts, _TAGS["cash"], end)
    shares_outstanding, shares_date = _latest_shares_outstanding(facts)
    fcf = cfo - abs(capex) if cfo is not None and capex is not None else None
    # A missing current portion counts as zero only when the noncurrent balance exists for the period.
    debt = (debt_current or 0) + debt_noncurrent if debt_noncurrent is not None else None
    growth = ((revenue / prior_revenue) - 1) * 100 if revenue is not None and prior_revenue and prior_revenue > 0 else None
    operating_margin = operating / revenue * 100 if operating is not None and revenue and revenue > 0 else None
    fcf_margin = fcf / revenue * 100 if fcf is not None and revenue and revenue > 0 else None
    net_debt = debt - cash if debt is not None and cash is not None else None
    if revenue is None:
        raise ValueError("no us-gaap 10-K revenue facts")
    return FundamentalSnapshot(symbol.upper(), fy, revenue, operating, fcf, eps, debt, cash, growth, operating_margin, fcf_margin, net_debt, "SEC Company Facts", "LIVE",
                               eps_period_end=end if eps is not None else None, diluted_shares=diluted_shares,
                               shares_outstanding=shares_outstanding, shares_outstanding_date=shares_date)


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
