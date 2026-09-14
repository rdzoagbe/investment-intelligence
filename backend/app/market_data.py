from __future__ import annotations

import json
import os
import time
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


def yahoo_quote(symbol: str) -> MarketQuote | None:
    yahoo_symbol = _provider_symbol(symbol)
    if not yahoo_symbol:
        return None
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


def live_quotes() -> list[dict[str, object]]:
    return [{"symbol": q.symbol, "price": q.price, "previous_close": q.previous_close, "change_pct": q.change_pct, "currency": q.currency, "timestamp": q.timestamp, "provider": q.provider, "status": q.status} for q in (quote_for_asset(asset) for asset in ASSETS)]


def market_data_status() -> dict[str, object]:
    mode = os.getenv("MARKET_DATA_MODE", "live").strip().lower()
    quotes = live_quotes()
    live_count = sum(q["status"] == "LIVE" for q in quotes)
    return {"mode": mode, "provider": "Yahoo Finance chart API", "live_quotes": live_count, "total_symbols": len(quotes), "last_checked_epoch": int(time.time()), "coverage_pct": round(live_count / len(quotes) * 100, 1) if quotes else 0, "note": "GSE symbols use the internal fallback until a supported GSE market-data feed is configured."}
