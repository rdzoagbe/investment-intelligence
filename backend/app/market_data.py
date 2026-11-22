from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

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


def _fetch_json(url: str, timeout: float = 5.0) -> dict[str, object]:
    request = Request(url, headers={"User-Agent": "Investment-Intelligence/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is constructed internally
        return json.loads(response.read().decode("utf-8"))


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


def _yahoo_fetch(symbol: str, yahoo_symbol: str) -> MarketQuote | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(yahoo_symbol)}?range=5d&interval=1d"
    try:
        payload = _fetch_json(url, timeout=float(os.getenv("MARKET_DATA_TIMEOUT", "5")))
        result = payload.get("chart", {}).get("result", [])
        if not result:
            return None
        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        previous = meta.get("previousClose") or meta.get("chartPreviousClose")
        if not isinstance(price, (int, float)) or price <= 0:
            return None
        change = None
        if isinstance(previous, (int, float)) and previous > 0:
            change = round((float(price) / float(previous) - 1) * 100, 3)
        timestamp = meta.get("regularMarketTime")
        return MarketQuote(symbol, float(price), float(previous) if isinstance(previous, (int, float)) else None, change, str(meta.get("currency") or ""), int(timestamp) if isinstance(timestamp, (int, float)) else None, "Yahoo Finance chart API", "LIVE")
    except (HTTPError, URLError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def quote_for_asset(asset: AssetSnapshot) -> MarketQuote:
    mode = os.getenv("MARKET_DATA_MODE", "live").strip().lower()
    if mode != "demo":
        live = yahoo_quote(asset.symbol)
        if live:
            return live
    return MarketQuote(asset.symbol, asset.price, round(asset.price / (1 + asset.change_pct / 100), 4), asset.change_pct, asset.currency, None, "Internal deterministic dataset", "DEMO")


def quote_dict(q: MarketQuote) -> dict[str, object]:
    return {"symbol": q.symbol, "price": q.price, "previous_close": q.previous_close, "change_pct": q.change_pct, "currency": q.currency, "timestamp": q.timestamp, "provider": q.provider, "status": q.status}


def live_quotes() -> list[dict[str, object]]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        return [quote_dict(q) for q in pool.map(quote_for_asset, ASSETS)]


def market_data_status() -> dict[str, object]:
    mode = os.getenv("MARKET_DATA_MODE", "live").strip().lower()
    quotes = live_quotes()
    live_count = sum(q["status"] == "LIVE" for q in quotes)
    return {"mode": mode, "provider": "Yahoo Finance chart API", "live_quotes": live_count, "total_symbols": len(quotes), "last_checked_epoch": int(time.time()), "coverage_pct": round(live_count / len(quotes) * 100, 1) if quotes else 0, "note": "GSE symbols use the internal fallback until a supported GSE market-data feed is configured."}


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
