"""Small in-process sliding-window rate limiter for auth and assistant endpoints.

State lives in this process only. The Render deployment runs a single free instance, so
that is enough to stop brute-force guessing, PBKDF2 CPU exhaustion and bulk sign-ups. With
several instances each one keeps its own counters (limits multiply by the instance count);
move the counters to the database or Redis before scaling out. Counters reset on restart.
"""
from __future__ import annotations

import math
import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

# (limit, window_seconds)
LOGIN_PER_EMAIL_IP = (10, 15 * 60)
LOGIN_PER_IP = (50, 15 * 60)
# No account-wide limit across all IPs: it would let anyone lock a victim out of their own
# account by failing logins on purpose. Guessing is limited per IP and per (email, IP) instead.
REGISTER_PER_IP = (5, 60 * 60)
ASSISTANT_PER_USER = (6, 60)


def assistant_global_daily() -> tuple[int, int]:
    """Ceiling on assistant asks across all users per day (protects the operator's AI bill)."""
    try:
        limit = int(os.getenv("ASSISTANT_GLOBAL_DAILY_LIMIT", "500"))
    except ValueError:
        limit = 500
    return max(limit, 1), 24 * 60 * 60


_lock = threading.Lock()
_hits: dict[str, deque[float]] = {}
_windows: dict[str, int] = {}  # each key's own window, so pruning never drops a live long-window counter
_MAX_KEYS = 50_000


def reset() -> None:
    with _lock:
        _hits.clear()
        _windows.clear()


def client_ip(request: Request) -> str:
    """Client address for rate limiting.

    Behind Render's proxy (RENDER is set) the proxy APPENDS the address it saw to any
    X-Forwarded-For the client sent, so only the right-most entry is trustworthy; the left
    entries are client-controlled and must never be used as a rate-limit key.
    TRUSTED_PROXY_HOPS can be raised if more trusted proxies sit in front of Render.
    """
    if os.getenv("RENDER"):
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        try:
            trusted = max(1, int(os.getenv("TRUSTED_PROXY_HOPS", "1")))
        except ValueError:
            trusted = 1
        if len(hops) >= trusted:
            return hops[-trusted][:64]
    return request.client.host if request.client else "unknown"


def hit(key: str, limit: int, window: int, now: float | None = None) -> int | None:
    """Record one attempt. Returns None when allowed, else the seconds to wait (Retry-After)."""
    now = time.monotonic() if now is None else now
    with _lock:
        bucket = _hits.get(key)
        if bucket is None:
            if len(_hits) >= _MAX_KEYS:
                _prune(now)
            bucket = _hits.setdefault(key, deque())
        _windows[key] = max(_windows.get(key, 0), window)
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            return max(1, math.ceil(bucket[0] + window - now))
        bucket.append(now)
        return None


def _prune(now: float) -> None:
    """Drop counters whose newest hit is older than THEIR OWN window (they can no longer block)."""
    for key in [k for k, b in _hits.items() if not b or b[-1] <= now - _windows.get(k, 0)]:
        del _hits[key]
        _windows.pop(key, None)
    if len(_hits) >= _MAX_KEYS:  # still full: drop the oldest half of the SHORT-window keys first
        short = sorted((k for k in _hits if _windows.get(k, 0) < 3600), key=lambda k: _hits[k][-1] if _hits[k] else 0)
        for key in short[: _MAX_KEYS // 2]:
            del _hits[key]
            _windows.pop(key, None)


def enforce(key: str, limit: int, window: int, message: str = "Too many requests. Please wait and try again.") -> None:
    retry_after = hit(key, limit, window)
    if retry_after is not None:
        raise HTTPException(429, message, headers={"Retry-After": str(retry_after)})
