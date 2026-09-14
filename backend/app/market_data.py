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
    "MSFT": "MSFT",
    "ASML": "ASML",
    "VISA": "V",
    "AMZN": "AMZN",
    # Access Bank Ghana is not reliably available through Yahoo's global feed;
    # the adapter therefore reports demo data for this symbol until a GSE feed is configured.
    "ACCESS": None,
}


def _fetch_json(url: str, timeout: float = 5.0) -> dict[str, object]:
    request = Request(
        url,
        headers={
            "User-Agent": "Investment-Intelligence/1.0",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is constructed internally
        return json.loads(response.read().decode("utf-8"))


def yahoo_quote(symbol: str) -> MarketQuote | None:
    yahoo_symbol = _YAHOO_SYMBOLS.get(symbol)
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
        return MarketQuote(
            symbol=symbol,
            price=float(price),
            previous_close=float(previous) if isinstance(previous, (int, float)) else None,
            change_pct=change,
            currency=str(meta.get("currency") or ""),
            timestamp=int(timestamp) if isinstance(timestamp, (int, float)) else None,
            provider="Yahoo Finance chart API",
            status="LIVE",
        )
    except (HTTPError, URLError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def quote_for_asset(asset: AssetSnapshot) -> MarketQuote:
    mode = os.getenv("MARKET_DATA_MODE", "live").strip().lower()
    if mode != "demo":
        live = yahoo_quote(asset.symbol)
        if live:
            return live

    return MarketQuote(
        symbol=asset.symbol,
        price=asset.price,
        previous_close=round(asset.price / (1 + asset.change_pct / 100), 4),
        change_pct=asset.change_pct,
        currency=asset.currency,
        timestamp=None,
        provider="Internal deterministic dataset",
        status="DEMO",
    )


def live_quotes() -> list[dict[str, object]]:
    quotes = [quote_for_asset(asset) for asset in ASSETS]
    return [
        {
            "symbol": quote.symbol,
            "price": quote.price,
            "previous_close": quote.previous_close,
            "change_pct": quote.change_pct,
            "currency": quote.currency,
            "timestamp": quote.timestamp,
            "provider": quote.provider,
            "status": quote.status,
        }
        for quote in quotes
    ]


def market_data_status() -> dict[str, object]:
    mode = os.getenv("MARKET_DATA_MODE", "live").strip().lower()
    quotes = live_quotes()
    live_count = sum(quote["status"] == "LIVE" for quote in quotes)
    return {
        "mode": mode,
        "provider": "Yahoo Finance chart API",
        "live_quotes": live_count,
        "total_symbols": len(quotes),
        "last_checked_epoch": int(time.time()),
        "note": "GSE symbols use the internal fallback until a supported GSE market-data feed is configured.",
    }
