"""News headlines (RSS), a static macro context note, and the rule-based bull/bear packet.

Nothing here calls a paid AI model: the bull/bear packet is built from the deterministic
score and the curated notes only. News comes from public RSS feeds and is cached briefly so
repeated page loads do not hammer the feed hosts.
"""
from __future__ import annotations

import html
import http.client
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from time import time
from urllib.request import Request, urlopen

DEFAULT_USER_AGENT = "Investment-Intelligence/1.0"
NEWS_CACHE_TTL = 600  # seconds; successful fetches
NEWS_FAILURE_TTL = 120  # seconds; empty or failed fetches are retried sooner
FEEDS = [
    {"name": "Yahoo Finance headlines", "url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=MSFT,AAPL,NVDA,AMZN&region=US&lang=en-US"},
    {"name": "SEC press releases", "url": "https://www.sec.gov/news/pressreleases.rss"},
]

_NEWS_CACHE: dict[str, object] = {}
_NEWS_LOCK = threading.Lock()


@dataclass(frozen=True)
class IntelligenceItem:
    category: str
    title: str
    summary: str
    source: str
    timestamp: int | None = None  # publication time from <pubDate>; None when the feed gives none
    impact: str = "NEUTRAL"
    feed: str | None = None
    fetched_at: int | None = None


def _clean(raw: str) -> str:
    """Unwrap CDATA, strip markup and decode HTML entities."""
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", raw, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(html.unescape(text))  # feeds often double-escape (&amp;amp;)
    return re.sub(r"\s+", " ", text).strip()


def _pub_timestamp(value: str) -> int | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    try:
        return int(dt.timestamp())
    except (OverflowError, OSError, ValueError):
        return None


def parse_rss(text: str, fallback_source: str, limit: int = 20, feed: str | None = None) -> list[IntelligenceItem]:
    blocks = re.findall(r"<item\b[^>]*>(.*?)</item>", text, flags=re.S | re.I)
    out: list[IntelligenceItem] = []
    fetched = int(time())
    for block in blocks[:limit]:
        def tag(name: str) -> str:
            m = re.search(fr"<{name}\b[^>]*>(.*?)</{name}>", block, flags=re.S | re.I)
            return _clean(m.group(1)) if m else ""
        title, desc, link = tag("title"), tag("description"), tag("link")
        if title:
            out.append(IntelligenceItem("NEWS", title, desc[:500], link or fallback_source, _pub_timestamp(tag("pubDate")), feed=feed, fetched_at=fetched))
    return out


def _user_agent_for(url: str) -> str | None:
    """SEC asks automated clients for a declared name and email; without one we skip sec.gov."""
    if "sec.gov" in url:
        from .fundamentals import sec_user_agent
        return sec_user_agent()
    return DEFAULT_USER_AGENT


def rss_items(url: str, limit: int = 20, feed: str | None = None) -> list[IntelligenceItem]:
    user_agent = _user_agent_for(url)
    if not user_agent:
        return []
    try:
        req = Request(url, headers={"User-Agent": user_agent, "Accept": "application/rss+xml, application/xml, text/xml"})
        with urlopen(req, timeout=float(os.getenv("NEWS_TIMEOUT", "6"))) as response:  # noqa: S310 - fixed feed URLs
            text = response.read().decode("utf-8", errors="replace")
        return parse_rss(text, url, limit, feed)
    except (OSError, http.client.HTTPException, ValueError, UnicodeError):
        # OSError covers URLError, HTTPError, timeouts and connection resets.
        return []


def _fetch_all() -> dict[str, object]:
    statuses: list[dict[str, object]] = []
    results: dict[str, list[IntelligenceItem]] = {}
    active = []
    for feed in FEEDS:
        if _user_agent_for(feed["url"]) is None:
            statuses.append({"name": feed["name"], "status": "SKIPPED", "items": 0, "note": "Set SEC_USER_AGENT ('Name email@domain') to enable the SEC feed."})
        else:
            active.append(feed)
    if active:
        deadline = float(os.getenv("NEWS_TOTAL_TIMEOUT", "10"))
        pool = ThreadPoolExecutor(max_workers=len(active))
        futures = {feed["name"]: pool.submit(rss_items, feed["url"], 8, feed["name"]) for feed in active}
        wait(list(futures.values()), timeout=deadline)
        pool.shutdown(wait=False, cancel_futures=True)
        for feed in active:
            fut = futures[feed["name"]]
            items = fut.result() if fut.done() and not fut.cancelled() and fut.exception() is None else []
            results[feed["name"]] = items
            statuses.append({"name": feed["name"], "status": "LIVE" if items else "UNAVAILABLE", "items": len(items)})
    order = {f["name"]: i for i, f in enumerate(FEEDS)}
    statuses.sort(key=lambda s: order.get(str(s["name"]), 99))
    items = [i for f in FEEDS for i in results.get(f["name"], [])]
    return {
        "items": [i.__dict__ for i in items[:20]],
        "source_count": sum(1 for s in statuses if s["status"] == "LIVE"),
        "feeds": statuses,
        "status": "LIVE" if items else "UNAVAILABLE",
        "fetched_at": int(time()),
    }


def market_intelligence() -> dict[str, object]:
    """Headlines from the configured feeds, cached ~10 minutes (failures ~2 minutes)."""
    with _NEWS_LOCK:
        cached = _NEWS_CACHE.get("value")
        expires = float(_NEWS_CACHE.get("expires", 0))  # type: ignore[arg-type]
        if cached is not None and time() < expires:
            return cached  # type: ignore[return-value]
        value = _fetch_all()
        _NEWS_CACHE["value"] = value
        _NEWS_CACHE["expires"] = time() + (NEWS_CACHE_TTL if value["items"] else NEWS_FAILURE_TTL)
        return value


def macro_snapshot() -> dict[str, object]:
    """Static context notes written into the tool. Not computed from any market data."""
    return {
        "regime": "NOT_ASSESSED",
        "status": "STATIC_PLACEHOLDER",
        "label": "Static context notes (not computed from data)",
        "drivers": [
            {"name": "Rates", "direction": "WATCH", "impact": "HIGH", "note": "Long-duration valuations remain sensitive to changes in real yields."},
            {"name": "Growth", "direction": "WATCH", "impact": "MEDIUM", "note": "Earnings revisions should be monitored alongside price momentum."},
            {"name": "FX", "direction": "WATCH", "impact": "MEDIUM", "note": "Currency moves can alter reported growth and cross-market returns."},
        ],
        "disclaimer": "These are fixed reminders of what to watch, written into the tool. They are not computed from current rates, growth or FX data and are not an assessment or forecast.",
    }


def bull_bear(symbol: str, score: float, catalysts: list[str], risks: list[str]) -> dict[str, object]:
    """Rule-based arguments for and against, from the deterministic score and curated notes only."""
    from .engine import band_label

    band = band_label(score)
    if band == "High score":
        score_line = f"Score of {score:.1f}/100 ({band} band): most modeled factors are favorable."
    elif band == "Watch":
        score_line = f"Score of {score:.1f}/100 ({band} band): several modeled factors are favorable."
    elif band == "Neutral":
        score_line = f"Score of {score:.1f}/100 ({band} band): modeled factors are mixed."
    else:
        score_line = f"Score of {score:.1f}/100 ({band} band): few modeled factors are favorable."
    bull = [score_line, *catalysts[:2]] if band in {"High score", "Watch"} else list(catalysts[:2])
    bear = ["Valuation and expectation risk can overwhelm strong fundamentals.", *risks[:2]]
    if band not in {"High score", "Watch"}:
        bear.insert(0, score_line)
    return {"symbol": symbol, "mode": "RULE_BASED", "band": band, "bull": bull, "bear": bear,
            "evidence": ["Deterministic score", "Curated catalyst notes (seed)", "Curated risk notes (seed)"],
            "confidence": round(max(0, min(100, 50 + abs(score - 75))), 1), "model_provider": "none"}
