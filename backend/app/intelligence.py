from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from time import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class IntelligenceItem:
    category: str
    title: str
    summary: str
    source: str
    timestamp: int | None = None
    impact: str = "NEUTRAL"


def rss_items(url: str, limit: int = 20) -> list[IntelligenceItem]:
    try:
        req = Request(url, headers={"User-Agent": "Investment-Intelligence/1.0"})
        with urlopen(req, timeout=float(os.getenv("NEWS_TIMEOUT", "6"))) as response:
            text = response.read().decode("utf-8", errors="replace")
        blocks = re.findall(r"<item>(.*?)</item>", text, flags=re.S | re.I)
        out: list[IntelligenceItem] = []
        for block in blocks[:limit]:
            def tag(name: str) -> str:
                m = re.search(fr"<{name}[^>]*>(.*?)</{name}>", block, flags=re.S | re.I)
                return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""
            title, desc, link = tag("title"), tag("description"), tag("link")
            if title:
                out.append(IntelligenceItem("NEWS", title, desc[:500], link or url, int(time())))
        return out
    except (HTTPError, URLError, TimeoutError, UnicodeError):
        return []


def market_intelligence() -> dict[str, object]:
    feeds = ["https://feeds.finance.yahoo.com/rss/2.0/headline?s=MSFT,AAPL,NVDA,AMZN&region=US&lang=en-US", "https://www.sec.gov/news/pressreleases.rss"]
    items: list[IntelligenceItem] = []
    for feed in feeds:
        items.extend(rss_items(feed, 8))
    return {"items": [i.__dict__ for i in items[:20]], "source_count": len(feeds), "status": "LIVE" if items else "FALLBACK"}


def macro_snapshot() -> dict[str, object]:
    return {"regime": "NEUTRAL", "drivers": [{"name": "Rates", "direction": "WATCH", "impact": "HIGH", "note": "Long-duration valuations remain sensitive to changes in real yields."}, {"name": "Growth", "direction": "WATCH", "impact": "MEDIUM", "note": "Earnings revisions should be monitored alongside price momentum."}, {"name": "FX", "direction": "WATCH", "impact": "MEDIUM", "note": "Currency moves can alter reported growth and cross-market returns."}], "disclaimer": "Macro labels are decision-support signals, not forecasts."}


def _openai_synthesis(symbol: str, score: float, catalysts: list[str], risks: list[str]) -> dict[str, object] | None:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    facts = json.dumps({"symbol": symbol, "score": score, "catalysts": catalysts[:4], "risks": risks[:4]})
    body = json.dumps({"model": model, "input": [{"role": "system", "content": [{"type": "input_text", "text": "You are an investment research challenger. Do not recommend manipulation or insider activity. Return concise bull and bear cases with explicit uncertainty. Treat supplied facts as the only evidence."}]}, {"role": "user", "content": [{"type": "input_text", "text": facts}]}]}).encode()
    try:
        req = Request("https://api.openai.com/v1/responses", data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=float(os.getenv("AI_TIMEOUT", "20"))) as response:
            payload = json.loads(response.read().decode())
        text = payload.get("output_text", "")
        return {"symbol": symbol, "mode": "MODEL", "model_provider": "OpenAI Responses API", "model": model, "analysis": text, "evidence": ["Deterministic score", "Tracked catalysts", "Tracked risks"], "confidence": round(max(0, min(100, 50 + abs(score - 75))), 1)} if text else None
    except (HTTPError, URLError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def bull_bear(symbol: str, score: float, catalysts: list[str], risks: list[str]) -> dict[str, object]:
    model_result = _openai_synthesis(symbol, score, catalysts, risks)
    if model_result:
        return model_result
    return {"symbol": symbol, "mode": "RULE_BASED", "bull": [f"Score of {score:.1f}/100 indicates favorable modeled factors.", *catalysts[:2]], "bear": ["Valuation and expectation risk can overwhelm strong fundamentals.", *risks[:2]], "evidence": ["Deterministic score", "Tracked catalysts", "Tracked risks"], "confidence": round(max(0, min(100, 50 + abs(score - 75))), 1), "model_provider": "none"}
