from __future__ import annotations

import http.client
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import tiingo
from .data import ASSETS, AssetSnapshot


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    price: float
    previous_close: float | None
    change_pct: float | None
    currency: str
    timestamp: int | None
    provider: str
    status: str


_YAHOO_SYMBOLS = {
    "ACCESS": None,
    "VISA": "V",
    # Listings whose Yahoo symbol differs from the internal symbol. ASML and SAP are
    # quoted on their home exchanges so the provider currency (EUR) matches the dataset.
    "ASML": "ASML.AS",
    "SAP": "SAP.DE",
    "BRK-B": "BRK-B",
    "NESN.SW": "NESN.SW",
    "MC.PA": "MC.PA",
    "SU.PA": "SU.PA",
    "AIR.PA": "AIR.PA",
}


def _provider_symbol(symbol: str) -> str | None:
    if symbol in _YAHOO_SYMBOLS:
        return _YAHOO_SYMBOLS[symbol]
    if symbol in {asset.symbol for asset in ASSETS if asset.market != "GSE"}:
        return symbol
    return None


# Every transport or parse failure a provider call can produce. urllib only wraps
# errors raised while sending the request in URLError; errors from getresponse()/read()
# (RemoteDisconnected, IncompleteRead, ConnectionResetError, ssl.SSLError, ...) arrive
# unwrapped, so adapters must catch these broad bases.
PROVIDER_ERRORS: tuple[type[BaseException], ...] = (OSError, http.client.HTTPException, ValueError, TypeError, KeyError, IndexError, AttributeError)


# Provider health, shown (without secrets) on the Settings page so a blocked or failing
# provider is visible instead of silently turning every price into a DEMO fallback.
_HEALTH_LOCK = threading.Lock()
_HEALTH: dict[str, object] = {"last_success": None, "last_error": None, "last_error_at": None, "consecutive_failures": 0, "backoff_until": None}
# After the provider says "slow down" (HTTP 429) or refuses (401/403), stop calling it for a while.
# Retrying immediately only prolongs a rate limit. No attempt is made to disguise the client.
RATE_LIMIT_BACKOFF_SECONDS = 15 * 60


class ProviderBackoff(URLError):
    """Raised without a network call while the provider is in a back-off window."""


def provider_health() -> dict[str, object]:
    with _HEALTH_LOCK:
        h = dict(_HEALTH)
    now = time.time()
    fmt = lambda t: time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(t)) if isinstance(t, (int, float)) else "never"  # noqa: E731
    backoff = h["backoff_until"]
    return {"last_success": fmt(h["last_success"]), "last_error": h["last_error"] or "none",
            "last_error_at": fmt(h["last_error_at"]), "consecutive_failures": h["consecutive_failures"],
            "paused_until": fmt(backoff) if isinstance(backoff, (int, float)) and backoff > now else "not paused"}


def _record(ok: bool, error: str | None = None, backoff: bool = False) -> None:
    now = time.time()
    with _HEALTH_LOCK:
        if ok:
            _HEALTH.update(last_success=now, consecutive_failures=0)
        else:
            _HEALTH.update(last_error=error, last_error_at=now, consecutive_failures=int(_HEALTH["consecutive_failures"]) + 1)  # type: ignore[arg-type]
            if backoff:
                _HEALTH["backoff_until"] = now + RATE_LIMIT_BACKOFF_SECONDS


def _fetch_json(url: str, timeout: float = 5.0) -> dict[str, object]:
    """Fetch and decode JSON. Any transport/parse failure is re-raised as URLError and recorded."""
    with _HEALTH_LOCK:
        until = _HEALTH["backoff_until"]
    if isinstance(until, (int, float)) and until > time.time():
        raise ProviderBackoff("provider paused after a rate-limit/refusal response")
    request = Request(url, headers={"User-Agent": "Investment-Intelligence/1.0", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is constructed internally
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        _record(False, f"HTTP {exc.code} {exc.reason}", backoff=exc.code in (401, 403, 429))
        raise
    except URLError as exc:
        _record(False, f"network error: {exc.reason}")
        raise
    except (OSError, http.client.HTTPException, ValueError) as exc:
        _record(False, f"{type(exc).__name__}: {exc}"[:200])
        raise URLError(exc) from exc
    _record(True)
    return data


_CACHE: dict[str, tuple[float, MarketQuote | None]] = {}
_CACHE_LOCK = threading.Lock()


def yahoo_quote(symbol: str, provider_symbol: str | None = None) -> MarketQuote | None:
    """Cached quote lookup. Failures are cached too so a slow provider cannot stall every request."""
    yahoo_symbol = provider_symbol or _provider_symbol(symbol)
    if not yahoo_symbol:
        return None
    ttl = float(os.getenv("MARKET_DATA_CACHE_SECONDS", "60"))
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(yahoo_symbol)
    if hit and now - hit[0] < ttl:
        cached = hit[1]
        return MarketQuote(symbol, cached.price, cached.previous_close, cached.change_pct, cached.currency, cached.timestamp, cached.provider, cached.status) if cached else None
    result = _yahoo_fetch(symbol, yahoo_symbol)
    with _CACHE_LOCK:
        _CACHE[yahoo_symbol] = (now, result)
    return result


def _local_date(epoch: float, gmtoffset: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(int(epoch) + gmtoffset))


def previous_session_close(node: dict[str, object]) -> float | None:
    """True previous trading-session close from a Yahoo chart result node.

    For range=5d the chart meta carries chartPreviousClose, which is the close BEFORE the
    five-day window (a ~weekly base), and usually no previousClose. So the previous close
    is derived from the daily bars: the last non-null close whose bar falls on an earlier
    exchange-local date than the session of regularMarketTime (that handles both a
    finished session and today's in-progress bar). meta.previousClose, which Yahoo only
    sends when it means the prior session close, is used when no bars are available.
    chartPreviousClose is never used. Returns None when it cannot be determined.
    """
    meta = node.get("meta") or {}
    if not isinstance(meta, dict):
        return None
    stamps = node.get("timestamp") or []
    indicators = node.get("indicators") or {}
    quotes = indicators.get("quote") if isinstance(indicators, dict) else None
    closes = (quotes[0] or {}).get("close") if isinstance(quotes, list) and quotes and isinstance(quotes[0], dict) else None
    market_time = meta.get("regularMarketTime")
    if isinstance(stamps, list) and isinstance(closes, list) and stamps and len(stamps) == len(closes) and isinstance(market_time, (int, float)):
        offset = meta.get("gmtoffset")
        offset = int(offset) if isinstance(offset, (int, float)) else 0
        session = _local_date(market_time, offset)
        for ts, close in zip(reversed(stamps), reversed(closes)):
            if not isinstance(ts, (int, float)) or not isinstance(close, (int, float)) or close <= 0:
                continue
            if _local_date(ts, offset) < session:
                return float(close)
        return None
    previous = meta.get("previousClose")
    if isinstance(previous, (int, float)) and previous > 0:
        return float(previous)
    return None


def _yahoo_fetch(symbol: str, yahoo_symbol: str) -> MarketQuote | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(yahoo_symbol)}?range=5d&interval=1d"
    try:
        payload = _fetch_json(url, timeout=float(os.getenv("MARKET_DATA_TIMEOUT", "5")))
        result = payload.get("chart", {}).get("result", [])
        if not result:
            return None
        node = result[0]
        meta = node.get("meta", {})
        price = meta.get("regularMarketPrice")
        if not isinstance(price, (int, float)) or price <= 0:
            return None
        previous = previous_session_close(node)
        change = round((float(price) / previous - 1) * 100, 3) if previous else None
        timestamp = meta.get("regularMarketTime")
        return MarketQuote(symbol, float(price), previous, change, str(meta.get("currency") or ""), int(timestamp) if isinstance(timestamp, (int, float)) else None, "Yahoo Finance chart API", "LIVE")
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, *PROVIDER_ERRORS):
        return None


def tiingo_quote(symbol: str) -> MarketQuote | None:
    """Quote from the licensed Tiingo feed for covered US stocks (None when off or missing)."""
    ticker = tiingo.ticker_for(symbol)
    if not ticker or not tiingo.enabled():
        return None
    row = tiingo.quotes().get(ticker)
    if not row:
        return None
    price, previous = float(row["price"]), row["previous_close"]  # type: ignore[arg-type]
    change = round((price / float(previous) - 1) * 100, 3) if isinstance(previous, float) else None
    stamp = row["timestamp"]
    return MarketQuote(symbol, price, previous if isinstance(previous, float) else None, change, "USD", stamp if isinstance(stamp, int) else None, tiingo.QUOTE_PROVIDER, "LIVE")


def quote_for_asset(asset: AssetSnapshot) -> MarketQuote:
    mode = os.getenv("MARKET_DATA_MODE", "live").strip().lower()
    if mode != "demo":
        live = tiingo_quote(asset.symbol) or yahoo_quote(asset.symbol)
        if live:
            return live
    return MarketQuote(asset.symbol, asset.price, round(asset.price / (1 + asset.change_pct / 100), 4), asset.change_pct, asset.currency, None, "Internal deterministic dataset", "DEMO")


def quote_dict(q: MarketQuote) -> dict[str, object]:
    return {"symbol": q.symbol, "price": q.price, "previous_close": q.previous_close, "change_pct": q.change_pct, "currency": q.currency, "timestamp": q.timestamp, "provider": q.provider, "status": q.status}


def live_quotes() -> list[dict[str, object]]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        return [quote_dict(q) for q in pool.map(quote_for_asset, ASSETS)]


def provider_label() -> str:
    if tiingo.enabled():
        return f"{tiingo.QUOTE_PROVIDER} for US stocks; Yahoo Finance chart API (unofficial) for other listings"
    return "Yahoo Finance chart API (unofficial; personal research use)"


def market_data_status() -> dict[str, object]:  # noqa: D401
    mode = os.getenv("MARKET_DATA_MODE", "live").strip().lower()
    quotes = live_quotes()
    live_count = sum(q["status"] == "LIVE" for q in quotes)
    return {"mode": mode, "provider": provider_label(), "live_quotes": live_count, "total_symbols": len(quotes), "last_checked_epoch": int(time.time()), "coverage_pct": round(live_count / len(quotes) * 100, 1) if quotes else 0, "note": "GSE symbols use the internal fallback until a supported GSE market-data feed is configured."}


# Benchmarks shown on the dashboard. No fallback values are invented: if the
# provider is unavailable the value is reported as unavailable.
INDEX_SYMBOLS: tuple[tuple[str, str], ...] = (
    ("S&P 500", "^GSPC"),
    ("NASDAQ Composite", "^IXIC"),
    ("DAX", "^GDAXI"),
    ("EUR/USD", "EURUSD=X"),
    ("Gold futures", "GC=F"),
)


def index_quotes() -> list[dict[str, object]]:
    mode = os.getenv("MARKET_DATA_MODE", "live").strip().lower()
    out: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        quotes = list(pool.map(lambda item: yahoo_quote(item[0], item[1]) if mode != "demo" else None, INDEX_SYMBOLS))
    for (name, provider_symbol), q in zip(INDEX_SYMBOLS, quotes):
        out.append({"name": name, "symbol": provider_symbol, "value": q.price if q else None, "change_pct": q.change_pct if q else None, "timestamp": q.timestamp if q else None, "provider": q.provider if q else None, "status": "LIVE" if q else "UNAVAILABLE"})
    return out


# --- FX ---------------------------------------------------------------------------
# Rates come from the provider only. Nothing is assumed: when a rate cannot be fetched
# it is reported UNAVAILABLE with rate None, never 1:1 or a seed value.
_FX_CACHE: dict[str, tuple[float, dict[str, object]]] = {}
_CURRENCY = re.compile(r"^[A-Z]{3}$")
# Minor-unit quotes (e.g. London prices in pence) and their major currency.
_MINOR_UNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ILA": ("ILS", 100.0), "ZAc": ("ZAR", 100.0)}


def _fx_unavailable() -> dict[str, object]:
    return {"rate": None, "status": "UNAVAILABLE", "source": None, "timestamp": None}


def _fx_fetch(base: str, quote_ccy: str) -> dict[str, object]:
    pair = f"{base}{quote_ccy}=X"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(pair)}?range=1d&interval=1d"
    try:
        payload = _fetch_json(url, timeout=float(os.getenv("MARKET_DATA_TIMEOUT", "5")))
        result = payload.get("chart", {}).get("result", [])
        if not result:
            return _fx_unavailable()
        meta = result[0].get("meta", {})
        rate = meta.get("regularMarketPrice")
        if not isinstance(rate, (int, float)) or rate <= 0:
            return _fx_unavailable()
        stamp = meta.get("regularMarketTime")
        return {"rate": float(rate), "status": "LIVE", "source": f"Yahoo Finance chart API ({pair})", "timestamp": int(stamp) if isinstance(stamp, (int, float)) else None}
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, *PROVIDER_ERRORS):
        return _fx_unavailable()


def fx_rate(base: str, quote: str) -> dict[str, object]:  # noqa: A002 - contract name
    """Units of `quote` currency per one unit of `base` currency.

    Returns {"rate", "status": LIVE|UNAVAILABLE|IDENTITY, "source", "timestamp"}. Never raises
    and never invents a rate; demo mode makes no network calls so rates are UNAVAILABLE.
    """
    base = str(base or "").strip()
    quote_ccy = str(quote or "").strip()
    divisor = 1.0
    if base in _MINOR_UNITS:
        base, divisor = _MINOR_UNITS[base]
    quote_divisor = 1.0
    if quote_ccy in _MINOR_UNITS:
        quote_ccy, quote_divisor = _MINOR_UNITS[quote_ccy]
    base, quote_ccy = base.upper(), quote_ccy.upper()
    if not _CURRENCY.match(base) or not _CURRENCY.match(quote_ccy):
        return _fx_unavailable()
    if base == quote_ccy:
        factor = quote_divisor / divisor
        return {"rate": factor, "status": "IDENTITY", "source": None if factor == 1.0 else "Minor currency unit conversion", "timestamp": None}
    if os.getenv("MARKET_DATA_MODE", "live").strip().lower() == "demo":
        return _fx_unavailable()
    key = f"{base}{quote_ccy}"
    ttl = float(os.getenv("MARKET_DATA_CACHE_SECONDS", "60"))
    now = time.time()
    with _CACHE_LOCK:
        hit = _FX_CACHE.get(key)
    if hit and now - hit[0] < ttl:
        result = dict(hit[1])
    else:
        result = _fx_fetch(base, quote_ccy)
        with _CACHE_LOCK:
            _FX_CACHE[key] = (now, dict(result))
    if result["rate"] is not None and (divisor != 1.0 or quote_divisor != 1.0):
        result["rate"] = float(result["rate"]) * quote_divisor / divisor
    return result
