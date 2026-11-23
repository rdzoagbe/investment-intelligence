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
LOGIN_PER_EMAIL = (30, 15 * 60)  # across all IPs: slows distributed guessing on one account
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
_MAX_KEYS = 50_000


def reset() -> None:
    with _lock:
        _hits.clear()


def client_ip(request: Request) -> str:
    """Client address. Behind Render's proxy (RENDER is set) the first X-Forwarded-For hop."""
    if os.getenv("RENDER"):
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:64]
    return request.client.host if request.client else "unknown"


def hit(key: str, limit: int, window: int, now: float | None = None) -> int | None:
    """Record one attempt. Returns None when allowed, else the seconds to wait (Retry-After)."""
    now = time.monotonic() if now is None else now
    with _lock:
        bucket = _hits.get(key)
        if bucket is None:
            if len(_hits) >= _MAX_KEYS:
                _prune(now, window)
            bucket = _hits.setdefault(key, deque())
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            return max(1, math.ceil(bucket[0] + window - now))
        bucket.append(now)
        return None


def _prune(now: float, window: int) -> None:
    for key in [k for k, b in _hits.items() if not b or b[-1] <= now - window]:
        del _hits[key]
    if len(_hits) >= _MAX_KEYS:  # still full: drop the oldest half rather than grow forever
        for key in sorted(_hits, key=lambda k: _hits[k][-1] if _hits[k] else 0)[: _MAX_KEYS // 2]:
            del _hits[key]


def enforce(key: str, limit: int, window: int, message: str = "Too many requests. Please wait and try again.") -> None:
    retry_after = hit(key, limit, window)
    if retry_after is not None:
        raise HTTPException(429, message, headers={"Retry-After": str(retry_after)})
