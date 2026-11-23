"""Daily price history and the statistics derived from it.

History comes from the Yahoo Finance chart endpoint (unofficial; personal research
use). Nothing is synthesised: when the provider is unavailable, or in demo mode,
history is None and every derived statistic is reported as unavailable.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from math import sqrt
from urllib.error import HTTPError, URLError
from urllib.parse import quote

from . import market_data

RANGES = {"1y", "2y", "5y", "10y"}
PROVIDER = "Yahoo Finance chart API (daily, adjusted close)"
# Yahoo's raw chart close is split-adjusted but not dividend-adjusted.
PROVIDER_UNADJUSTED = "Yahoo Finance chart API (daily close, split-adjusted only; dividends not included)"


@dataclass(frozen=True)
class PriceHistory:
    symbol: str
    dates: list[str]
    closes: list[float]
    currency: str
    provider: str = ""
    adjusted: bool = False  # True only when Yahoo's adjclose series was used
    # Stock splits reported by the provider inside this range: ((YYYY-MM-DD, new/old shares), ...).
    splits: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        if not self.provider:
            object.__setattr__(self, "provider", PROVIDER if self.adjusted else PROVIDER_UNADJUSTED)

    def as_dict(self) -> dict[str, object]:
        return {"symbol": self.symbol, "currency": self.currency, "provider": self.provider, "status": "LIVE", "adjusted": self.adjusted,
                "points": [{"date": d, "close": round(c, 4)} for d, c in zip(self.dates, self.closes)]}


_CACHE: dict[tuple[str, str], tuple[float, PriceHistory | None]] = {}
_LOCK = threading.Lock()


def parse_chart(symbol: str, payload: dict[str, object]) -> PriceHistory | None:
    """Parse a Yahoo chart response, preferring split/dividend-adjusted closes.

    Falls back to the raw close series when adjclose is missing or misaligned; the result
    then has adjusted=False and an "unadjusted" provider label so it is never mislabelled.
    """
    result = (payload.get("chart") or {}).get("result") or []  # type: ignore[union-attr]
    if not result:
        return None
    node = result[0]
    stamps = node.get("timestamp") or []
    indicators = node.get("indicators") or {}
    adj = (indicators.get("adjclose") or [{}])[0].get("adjclose")
    raw = (indicators.get("quote") or [{}])[0].get("close")
    adjusted = bool(adj) and len(adj) == len(stamps)
    series = adj if adjusted else raw
    if not series or len(series) != len(stamps):
        return None
    dates, closes = [], []
    for ts, close in zip(stamps, series):
        if isinstance(ts, (int, float)) and isinstance(close, (int, float)) and close > 0:
            dates.append(time.strftime("%Y-%m-%d", time.gmtime(int(ts))))
            closes.append(float(close))
    if len(closes) < 2:
        return None
    currency = str((node.get("meta") or {}).get("currency") or "")
    return PriceHistory(symbol, dates, closes, currency, adjusted=adjusted, splits=parse_splits(node))


def parse_splits(node: dict) -> tuple[tuple[str, float], ...]:
    """Split events from a chart result (events.splits). Malformed entries are skipped."""
    out = []
    events = (node.get("events") or {}).get("splits") or {}
    if isinstance(events, dict):
        for item in events.values():
            try:
                ts, num, den = int(item["date"]), float(item["numerator"]), float(item["denominator"])
            except (KeyError, TypeError, ValueError):
                continue
            if num > 0 and den > 0:
                out.append((time.strftime("%Y-%m-%d", time.gmtime(ts)), num / den))
    return tuple(sorted(out))


def price_history(symbol: str, range_: str = "2y") -> PriceHistory | None:
    if range_ not in RANGES:
        raise ValueError(f"range must be one of {sorted(RANGES)}")
    if os.getenv("MARKET_DATA_MODE", "live").strip().lower() == "demo":
        return None
    provider_symbol = market_data._provider_symbol(symbol)  # noqa: SLF001 - shared mapping
    if not provider_symbol:
        return None
    key = (provider_symbol, range_)
    ttl = float(os.getenv("HISTORY_CACHE_SECONDS", "21600"))
    with _LOCK:
        hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < (ttl if hit[1] else 300):
        return hit[1]
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(provider_symbol)}?range={range_}&interval=1d&events=div%2Csplits"
    try:
        result = parse_chart(symbol, market_data._fetch_json(url, timeout=float(os.getenv("MARKET_DATA_TIMEOUT", "8"))))  # noqa: SLF001
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, *market_data.PROVIDER_ERRORS):
        result = None
    with _LOCK:
        _CACHE[key] = (time.time(), result)
    return result


def daily_returns(closes: list[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]


def sma(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            out[i] = running / window
    return out


def _parse_dates(dates: list[str]) -> list[date] | None:
    try:
        return [date.fromisoformat(d) for d in dates]
    except (TypeError, ValueError):
        return None


def _last_index_on_or_before(days: list[date], target: date) -> int | None:
    found = None
    for i, d in enumerate(days):
        if d <= target:
            found = i
        else:
            break
    return found


def _lookback_indices(history: PriceHistory) -> tuple[int | None, int | None]:
    """(index of the close ~1 year before the last, index of the close ~1 month before the last).

    Uses calendar dates when available: the base is the last close on or before
    last_date - 365 days, or the first close when the series starts within a week of that
    date (a Yahoo "1y" range has ~250 bars, which the old fixed 253-bar lookback rejected).
    Without ISO dates it falls back to 253 / 22 trading bars.
    """
    c = history.closes
    days = _parse_dates(history.dates) if len(history.dates) == len(c) else None
    if days is None or days != sorted(days):
        base = len(c) - 253 if len(c) >= 253 else None
        end = len(c) - 22 if len(c) >= 22 else None
        return base, end
    last = days[-1]
    target = last - timedelta(days=365)
    base = _last_index_on_or_before(days, target)
    if base is None and days[0] <= target + timedelta(days=7):
        base = 0
    end = _last_index_on_or_before(days, last - timedelta(days=30))
    return base, end


def statistics(history: PriceHistory) -> dict[str, float | None]:
    """Trailing ~1-year statistics (calendar lookback of 365 days; 12-1 momentum ends ~30 days ago)."""
    c = history.closes
    base, month_ago = _lookback_indices(history)
    window = c[base:] if base is not None else c[-253:]
    rets = daily_returns(window)
    vol = None
    if len(rets) > 20:
        mean = sum(rets) / len(rets)
        vol = sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) * sqrt(252) * 100
    # 12-1 momentum: return from ~12 months ago to ~1 month ago (skips the latest month's reversal effect).
    mom_12_1 = (c[month_ago] / c[base] - 1) * 100 if base is not None and month_ago is not None and month_ago > base else None
    ret_1y = (c[-1] / c[base] - 1) * 100 if base is not None else None
    sma200 = sma(c, 200)[-1]
    above_200 = (c[-1] / sma200 - 1) * 100 if sma200 else None
    peak, max_dd = window[0], 0.0
    for v in window:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    return {"volatility_1y_pct": round(vol, 2) if vol is not None else None,
            "momentum_12_1_pct": round(mom_12_1, 2) if mom_12_1 is not None else None,
            "return_1y_pct": round(ret_1y, 2) if ret_1y is not None else None,
            "vs_200d_average_pct": round(above_200, 2) if above_200 is not None else None,
            "max_drawdown_1y_pct": round(max_dd * 100, 2) if len(c) >= 2 else None,
            "observations": len(c)}


def momentum_score(stats: dict[str, float | None]) -> float | None:
    """Map trailing momentum to 0-100. 50 = flat; +/-40% 12-1 momentum saturates; trend adds +/-10."""
    mom = stats.get("momentum_12_1_pct")
    if mom is None:
        return None
    score = 50 + max(-40.0, min(40.0, mom)) * 1.0
    trend = stats.get("vs_200d_average_pct")
    if trend is not None:
        score += 10 if trend > 0 else -10
    return round(max(0.0, min(100.0, score)), 1)
