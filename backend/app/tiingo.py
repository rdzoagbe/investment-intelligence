"""Tiingo adapter: US stock quotes and daily price history from a licensed API.

Endpoints and fields follow Tiingo's public documentation (tiingo.com/documentation):
  * 24x5 Consolidated snapshot, all tickers in one request: GET /tiingo/equity/intraday
    fields used: ticker, timestamp, tngoLast, prevClose, prevDate
  * End-of-day prices: GET /tiingo/daily/<ticker>/prices?startDate=YYYY-MM-DD
    fields used: date, adjClose (split- and dividend-adjusted), splitFactor
  * Authentication: header "Authorization: Token <key>" (the key never appears in a URL or log).

Licence. Tiingo's free plan is "Internal Use Only: you may only use the data for your own
personal use and you may not display or share the data with another person or organization"
(tiingo.com/about/pricing). So with the default TIINGO_LICENSE=personal the adapter only runs
when the deployment is private (OWNER_USER_IDS set; main.py then restricts the API to those
accounts and closes sign-up). TIINGO_LICENSE=commercial is for an operator who holds a Tiingo
licence that allows showing the data to other people; the app cannot verify that licence.

Free-plan limits (same page): 50 requests/hour, 1,000/day, 500 unique symbols/month. A local
budget stays under them (TIINGO_MAX_REQUESTS_PER_HOUR, default 40; per day, default 800).
"""
from __future__ import annotations

import http.client
import json
import os
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from . import db
from .data import ASSETS

BASE_URL = "https://api.tiingo.com"
QUOTE_PROVIDER = "Tiingo 24x5 consolidated (licensed API)"
HISTORY_PROVIDER = "Tiingo end-of-day (licensed API; split- and dividend-adjusted close)"
LICENCE_NOTE = "Tiingo free plan: internal, personal use only; data may not be shown to other people."

# Internal symbol -> Tiingo ticker, for US-listed USD assets only. Share classes use "-" in
# Tiingo symbology ("BRK.A" is "BRK-A"), so BRK-B is unchanged.
_RENAMED = {"VISA": "V"}
_US_MARKETS = {"NASDAQ", "NYSE"}
TICKERS: dict[str, str] = {a.symbol: _RENAMED.get(a.symbol, a.symbol) for a in ASSETS if a.market in _US_MARKETS and a.currency == "USD"}

_ERRORS: tuple[type[BaseException], ...] = (OSError, http.client.HTTPException, ValueError, TypeError, KeyError, IndexError, AttributeError)
BACKOFF_SECONDS = 15 * 60


class Unavailable(Exception):
    """Tiingo was not called or did not return usable data (reason in the message)."""


def ticker_for(symbol: str) -> str | None:
    return TICKERS.get(symbol)


def api_key() -> str | None:
    key = os.getenv("TIINGO_API_KEY", "").strip()
    return key or None


def licence() -> str:
    value = os.getenv("TIINGO_LICENSE", "personal").strip().lower()
    return "commercial" if value == "commercial" else "personal"


def owner_ids() -> set[str]:
    return {x.strip() for x in os.getenv("OWNER_USER_IDS", "").split(",") if x.strip()}


def private_mode() -> bool:
    return bool(owner_ids())


def disabled_reason() -> str | None:
    """Why the adapter is off, or None when it may be used."""
    if os.getenv("MARKET_DATA_MODE", "live").strip().lower() == "demo":
        return "MARKET_DATA_MODE=demo"
    if not api_key():
        return "TIINGO_API_KEY is not set"
    if licence() == "personal" and not private_mode():
        return ("TIINGO_API_KEY is set but not used: the free Tiingo plan is for personal use only and this site is public. "
                "Set OWNER_USER_IDS to your account id to make the site private, or set TIINGO_LICENSE=commercial if your Tiingo plan allows showing data to others.")
    return None


def enabled() -> bool:
    return disabled_reason() is None


# --- request budget, back-off and health ---------------------------------------------
_LOCK = threading.Lock()
_SENT: deque[float] = deque()
_HEALTH: dict[str, object] = {"last_success": None, "last_error": None, "last_error_at": None, "consecutive_failures": 0, "backoff_until": None}


def _limits() -> tuple[int, int]:
    def read(name: str, default: int) -> int:
        try:
            return max(1, int(os.getenv(name, str(default))))
        except ValueError:
            return default
    return read("TIINGO_MAX_REQUESTS_PER_HOUR", 40), read("TIINGO_MAX_REQUESTS_PER_DAY", 800)


def _reserve() -> None:
    """Count one request against the local budget, or raise Unavailable without calling Tiingo."""
    per_hour, per_day = _limits()
    now = time.time()
    with _LOCK:
        until = _HEALTH["backoff_until"]
        if isinstance(until, (int, float)) and until > now:
            raise Unavailable("paused after a refusal/rate-limit response")
        while _SENT and now - _SENT[0] > 86400:
            _SENT.popleft()
        last_hour = sum(1 for t in _SENT if now - t <= 3600)
        if last_hour >= per_hour or len(_SENT) >= per_day:
            raise Unavailable("local request budget reached (protects the Tiingo plan limits)")
        _SENT.append(now)


def _record(ok: bool, error: str | None = None, backoff: bool = False) -> None:
    now = time.time()
    with _LOCK:
        if ok:
            _HEALTH.update(last_success=now, consecutive_failures=0)
        else:
            _HEALTH.update(last_error=error, last_error_at=now, consecutive_failures=int(_HEALTH["consecutive_failures"]) + 1)  # type: ignore[arg-type]
            if backoff:
                _HEALTH["backoff_until"] = now + BACKOFF_SECONDS


def health() -> dict[str, object]:
    """Status for the Settings page. Contains no secret values."""
    now = time.time()
    with _LOCK:
        h = dict(_HEALTH)
        last_hour = sum(1 for t in _SENT if now - t <= 3600)
        last_day = sum(1 for t in _SENT if now - t <= 86400)
    per_hour, per_day = _limits()
    fmt = lambda t: time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(t)) if isinstance(t, (int, float)) else "never"  # noqa: E731
    backoff = h["backoff_until"]
    reason = disabled_reason()
    return {"enabled": reason is None, "disabled_reason": reason or "none", "licence": licence(), "licence_note": LICENCE_NOTE,
            "covers": f"{len(TICKERS)} US-listed stocks", "requests_last_hour": f"{last_hour} of {per_hour}", "requests_last_day": f"{last_day} of {per_day}",
            "last_success": fmt(h["last_success"]), "last_error": h["last_error"] or "none", "last_error_at": fmt(h["last_error_at"]),
            "paused_until": fmt(backoff) if isinstance(backoff, (int, float)) and backoff > now else "not paused"}


def _get(path: str, params: dict[str, str] | None = None, timeout: float = 15.0) -> object:
    """GET a Tiingo endpoint and decode JSON. Raises Unavailable on any failure."""
    key = api_key()
    if not key or not enabled():
        raise Unavailable(disabled_reason() or "disabled")
    _reserve()
    url = f"{BASE_URL}{path}" + (f"?{urlencode(params)}" if params else "")
    request = Request(url, headers={"Authorization": f"Token {key}", "Accept": "application/json", "User-Agent": "Investment-Intelligence/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https host
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        _record(False, f"HTTP {exc.code} {exc.reason}", backoff=exc.code in (401, 403, 429))
        raise Unavailable(f"HTTP {exc.code}") from exc
    except URLError as exc:
        _record(False, f"network error: {exc.reason}")
        raise Unavailable("network error") from exc
    except _ERRORS as exc:
        _record(False, f"{type(exc).__name__}"[:200])
        raise Unavailable(type(exc).__name__) from exc
    # Tiingo reports some errors as a JSON object with a "detail" message and HTTP 200.
    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        _record(False, f"Tiingo: {str(data['detail'])[:160]}")
        raise Unavailable("provider error")
    _record(True)
    return data


def _epoch(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return int(stamp.timestamp())


def _positive(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


# --- quotes ---------------------------------------------------------------------------
_QUOTES: dict[str, object] = {"at": 0.0, "data": None}
_QUOTES_LOCK = threading.Lock()


def parse_snapshot(payload: object) -> dict[str, dict[str, object]]:
    """Tiingo ticker (upper case) -> {price, previous_close, timestamp} for our tickers only."""
    rows = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    wanted = set(TICKERS.values())
    out: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if ticker not in wanted:
            continue
        price = _positive(row.get("tngoLast"))
        if price is None:
            continue
        out[ticker] = {"price": price, "previous_close": _positive(row.get("prevClose")), "timestamp": _epoch(row.get("timestamp"))}
    return out


def quotes() -> dict[str, dict[str, object]]:
    """Latest quotes for every covered ticker from ONE request, cached (TIINGO_QUOTE_CACHE_SECONDS, default 600)."""
    if not enabled():
        return {}
    ttl = float(os.getenv("TIINGO_QUOTE_CACHE_SECONDS", "600"))
    with _QUOTES_LOCK:  # one request at a time; concurrent callers wait for it and share the result
        now = time.time()
        data = _QUOTES["data"]
        age = now - float(_QUOTES["at"])  # type: ignore[arg-type]
        if age < (ttl if data else min(ttl, 300.0)) and _QUOTES["at"]:
            return data or {}  # type: ignore[return-value]
        try:
            data = parse_snapshot(_get("/tiingo/equity/intraday", timeout=20.0))
        except Unavailable:
            data = {}
        _QUOTES.update(at=now, data=data)
        return data


# --- daily history --------------------------------------------------------------------
_HISTORY: dict[str, tuple[float, dict[str, object] | None]] = {}
_HISTORY_LOCKS: dict[str, threading.Lock] = {}
_HISTORY_GUARD = threading.Lock()
HISTORY_YEARS = 10


def parse_daily(payload: object) -> dict[str, object] | None:
    """{dates, closes (adjClose), splits ((date, splitFactor), ...)} from an end-of-day price list."""
    if not isinstance(payload, list):
        return None
    dates: list[str] = []
    closes: list[float] = []
    splits: list[tuple[str, float]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        day = str(row.get("date") or "")[:10]
        close = _positive(row.get("adjClose"))
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        if close is None:
            continue
        if dates and day <= dates[-1]:
            continue  # keep strictly increasing dates
        dates.append(day)
        closes.append(close)
        factor = row.get("splitFactor")
        if isinstance(factor, (int, float)) and factor > 0 and abs(float(factor) - 1.0) > 1e-9:
            splits.append((day, float(factor)))
    if len(closes) < 2:
        return None
    return {"dates": dates, "closes": closes, "splits": splits}


def _db_load(key: str, ttl: float) -> dict[str, object] | None:
    try:
        row = db.fetch_one("SELECT fetched_at, payload FROM provider_cache WHERE cache_key=?", (key,))
    except Exception:  # noqa: BLE001 - the cache is optional; a database outage must not break prices
        return None
    if not row or time.time() - float(row["fetched_at"]) >= ttl:
        return None
    try:
        value = json.loads(row["payload"])
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _db_store(key: str, value: dict[str, object]) -> None:
    try:
        db.execute("INSERT INTO provider_cache (cache_key, fetched_at, payload) VALUES (?, ?, ?) "
                   "ON CONFLICT (cache_key) DO UPDATE SET fetched_at = excluded.fetched_at, payload = excluded.payload",
                   (key, int(time.time()), json.dumps(value)))
    except Exception:  # noqa: BLE001 - optional cache
        pass


def daily_history(symbol: str) -> dict[str, object] | None:
    """Up to 10 years of adjusted daily closes for one covered symbol, or None.

    One request per ticker per TIINGO_HISTORY_CACHE_SECONDS (default 12 h), shared by every
    chart range; kept in memory and in the database so restarts do not refetch.
    """
    ticker = ticker_for(symbol)
    if not ticker or not enabled():
        return None
    ttl = float(os.getenv("TIINGO_HISTORY_CACHE_SECONDS", "43200"))
    with _HISTORY_GUARD:
        lock = _HISTORY_LOCKS.setdefault(ticker, threading.Lock())
    with lock:  # concurrent requests for the same ticker share one fetch
        hit = _HISTORY.get(ticker)
        if hit and time.time() - hit[0] < (ttl if hit[1] else 300.0):
            return hit[1]
        key = f"tiingo:daily:{ticker}"
        value = _db_load(key, ttl)
        if value is None:
            start = (date.today() - timedelta(days=365 * HISTORY_YEARS + 10)).isoformat()
            try:
                value = parse_daily(_get(f"/tiingo/daily/{quote(ticker.lower())}/prices", {"startDate": start}))
            except Unavailable:
                value = None
            if value is not None:
                _db_store(key, value)
        _HISTORY[ticker] = (time.time(), value)
        return value


def reset_for_tests() -> None:
    with _LOCK:
        _SENT.clear()
        _HEALTH.update(last_success=None, last_error=None, last_error_at=None, consecutive_failures=0, backoff_until=None)
    with _QUOTES_LOCK:
        _QUOTES.update(at=0.0, data=None)
    with _HISTORY_GUARD:
        _HISTORY.clear()
