from __future__ import annotations

import io
import json
import threading
import time
import types

import anthropic
import pytest
from fastapi.testclient import TestClient

from app import assistant, intelligence, llm, llm_anthropic, llm_openai
from app.main import app

client = TestClient(app)


def login(email="g3@example.com"):
    r = client.post("/api/auth/register", json={"name": "User", "email": email, "password": "long-enough-1", "accept_terms": True})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(autouse=True)
def clear_news_cache():
    intelligence._NEWS_CACHE.clear()
    yield
    intelligence._NEWS_CACHE.clear()


# ---------- citations (finding 8) ----------
def test_grouped_lowercase_and_range_citations_are_validated():
    text, valid, invalid = assistant._check_citations("Revenue grew [E1, E9]. Margin [e7]. Price [E2-E8]. Also [E1; E2]. [E1]", {"E1", "E2"})
    assert valid == ["E1", "E2"]
    assert invalid == ["E3", "E4", "E5", "E6", "E7", "E8", "E9"]
    assert "[E9]" not in text and "[e7]" not in text and "E8" not in text
    assert "Revenue grew [E1]." in text and "Price [E2]." in text and "Also [E1][E2]." in text


def test_grouped_valid_citations_count_as_grounded():
    text, valid, invalid = assistant._check_citations("Score high [E1, E2] and [e3].", {"E1", "E2", "E3"})
    assert text == "Score high [E1][E2] and [E3]." and valid == ["E1", "E2", "E3"] and invalid == []


# ---------- asset detection (19, 51, 62, 63) ----------
def syms(q):
    return [a.symbol for a in assistant._mentioned_assets(q)]


def test_ticker_at_end_of_sentence():
    assert syms("Tell me about MSFT.") == ["MSFT"]
    assert syms("Compare TSLA and KO.") == ["TSLA", "KO"]
    assert "MC.PA" in syms("What about MC.PA?")


def test_lowercase_tickers_accents_and_aliases():
    assert syms("what is the score for aapl and msft?") == ["AAPL", "MSFT"]
    assert syms("How does Nestle look?") == ["NESN.SW"]
    assert syms("Is Lilly expensive?") == ["LLY"]
    # ordinary-word tickers stay case-sensitive
    assert syms("I need a visa and some sap for the tree") == []


def test_ambiguous_words_do_not_match():
    assert syms("Access to the data is limited.") == []
    assert syms("A Meta-analysis of returns") == []
    assert syms("Is Access Bank profitable?") == ["ACCESS"]
    assert syms("How is Meta doing?") == ["META"]


def test_assets_are_ordered_by_mention_and_drops_are_reported(monkeypatch):
    assert syms("Compare Tesla with Microsoft, Amazon, NVIDIA and Broadcom") == ["TSLA", "MSFT", "AMZN", "NVDA"]
    r = client.post("/api/assistant/ask", json={"question": "Compare Tesla with Microsoft, Amazon, NVIDIA and Broadcom"}, headers=login()).json()
    assert r["omitted_assets"] == ["AVGO"] and "AVGO" in r["notice"]


# ---------- evidence labels (20, 45) ----------
def test_scanner_summary_labels_demo_prices():
    ev = assistant.gather_evidence("What looks interesting today?", None)
    top = next(e for e in ev if e.title == "Top-scoring assets")
    assert top.status == "DEMO" and "DEMO" in top.detail


def test_macro_is_a_static_label_not_an_assessment():
    m = intelligence.macro_snapshot()
    assert m["status"] == "STATIC_PLACEHOLDER" and m["regime"] == "NOT_ASSESSED"
    ev = assistant.gather_evidence("How do interest rates affect things?", None)
    macro = next(e for e in ev if e.title == "Macro context notes")
    assert macro.status == "STATIC" and "not computed" in macro.source


# ---------- privacy notice (24) ----------
def fake_model(monkeypatch, text="Score [E1].", refused=False, raise_exc=None, truncated=False, delay=0.0):
    calls = []

    def complete(system, user, budget_s=None):
        calls.append((system, user, budget_s))
        if delay:
            time.sleep(delay)
        if raise_exc:
            raise raise_exc
        return {"text": text, "model": "test-model", "refused": refused, "truncated": truncated, "provider": "anthropic"}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(llm, "complete", complete)
    return calls


def test_privacy_notice_when_personal_data_is_sent(monkeypatch):
    calls = fake_model(monkeypatch)
    h = login("priv@example.com")
    client.post("/api/me/holdings", json={"symbol": "MSFT", "quantity": 2, "average_cost": 100}, headers=h)
    r = client.post("/api/assistant/ask", json={"question": "What is in my portfolio?"}, headers=h).json()
    assert "Anthropic" in r["privacy_notice"] and "holdings" in r["privacy_notice"]
    assert "Your holding MSFT" in calls[0][1]
    r2 = client.post("/api/assistant/ask", json={"question": "Tell me about Microsoft"}, headers=h).json()
    assert "privacy_notice" not in r2


def test_no_privacy_notice_without_a_model():
    h = login("priv2@example.com")
    r = client.post("/api/assistant/ask", json={"question": "What is in my portfolio?"}, headers=h).json()
    assert r["provider"] == "none" and "privacy_notice" not in r


# ---------- daily limit race and failures (11, 31) ----------
def test_concurrent_requests_cannot_exceed_daily_limit(monkeypatch):
    calls = fake_model(monkeypatch, delay=0.2)
    monkeypatch.setenv("ASSISTANT_DAILY_LIMIT", "2")
    login("race@example.com")
    from app import db
    user_id = int(db.fetch_one("SELECT id FROM users WHERE email=?", ("race@example.com",))["id"])
    results = []

    def one():
        results.append(assistant.ask("Is NVDA attractive?", user_id))

    threads = [threading.Thread(target=one) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 2
    assert sum(1 for r in results if r["answer"]) == 2
    assert sum(1 for r in results if "Daily limit" in str(r.get("notice"))) == 6
    assert assistant._daily_count(user_id) == 2


def test_failed_provider_calls_do_not_use_the_allowance(monkeypatch):
    fake_model(monkeypatch, raise_exc=TimeoutError())
    monkeypatch.setenv("ASSISTANT_DAILY_LIMIT", "1")
    h = login("fail@example.com")
    for _ in range(2):
        r = client.post("/api/assistant/ask", json={"question": "Is NVDA attractive?"}, headers=h).json()
        assert "TimeoutError" in r["notice"] and "Daily limit" not in r["notice"]
    fake_model(monkeypatch, text="Score [E2].")
    assert client.post("/api/assistant/ask", json={"question": "Is NVDA attractive?"}, headers=h).json()["answer"]
    items = client.get("/api/me/assistant/history", headers=h).json()["items"]
    assert len(items) == 3 and not any(i.get("pending") for i in items)


def test_budget_is_passed_and_fits_request_ceiling(monkeypatch):
    calls = fake_model(monkeypatch)
    client.post("/api/assistant/ask", json={"question": "Is NVDA attractive?"}, headers=login("budget@example.com"))
    assert 0 < calls[0][2] <= llm.REQUEST_BUDGET_S - 5
    monkeypatch.setenv("AI_TIMEOUT", "500")
    assert llm.model_budget() <= llm.REQUEST_BUDGET_S - 10


def test_truncated_empty_answer_is_surfaced(monkeypatch):
    fake_model(monkeypatch, text="", truncated=True)
    r = client.post("/api/assistant/ask", json={"question": "Is NVDA attractive?"}, headers=login("trunc@example.com")).json()
    assert r["answer"] is None and r["truncated"] is True and "output length" in r["notice"]


# ---------- Anthropic provider timeouts ----------
class FlakyAnthropic:
    calls: list = []
    errors: list = []

    def __init__(self, **kwargs):
        FlakyAnthropic.calls.append(kwargs)
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        if FlakyAnthropic.errors:
            raise FlakyAnthropic.errors.pop(0)
        return types.SimpleNamespace(stop_reason="max_tokens", model=kwargs["model"], content=[types.SimpleNamespace(type="text", text="Partial")])


def test_anthropic_retries_once_within_budget(monkeypatch):
    monkeypatch.setattr(llm_anthropic.anthropic, "Anthropic", FlakyAnthropic)
    monkeypatch.setattr(llm_anthropic.time, "sleep", lambda s: None)
    FlakyAnthropic.calls = []
    import httpx2 as httpx
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    FlakyAnthropic.errors = [anthropic.APIConnectionError(request=req)]
    out = llm_anthropic.complete("S", "U", budget_s=60)
    assert out["truncated"] is True and out["text"] == "Partial"
    assert len(FlakyAnthropic.calls) == 2
    assert all(c["max_retries"] == 0 and c["timeout"] <= 60 for c in FlakyAnthropic.calls)
    FlakyAnthropic.calls = []
    FlakyAnthropic.errors = [anthropic.APITimeoutError(request=req)]
    with pytest.raises(anthropic.APITimeoutError):
        llm_anthropic.complete("S", "U", budget_s=60)
    assert len(FlakyAnthropic.calls) == 1


# ---------- OpenAI provider (39) ----------
def test_openai_parses_output_array_refusal_and_incomplete():
    payload = {"model": "m", "status": "completed", "output": [
        {"type": "reasoning", "content": None},
        {"type": "message", "content": [{"type": "output_text", "text": "Hello [E1]."}]}]}
    assert llm_openai.parse_response(payload, "m") == {"text": "Hello [E1].", "model": "m", "refused": False, "truncated": False, "provider": "openai"}
    refusal = {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No."}]}]}
    assert llm_openai.parse_response(refusal, "m")["refused"] is True
    incomplete = {"status": "incomplete", "output": [{"type": "message", "content": None}]}
    out = llm_openai.parse_response(incomplete, "m")
    assert out["truncated"] is True and out["text"] == ""


def test_openai_complete_reads_rest_payload(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["timeout"] = timeout
        seen["body"] = json.loads(req.data)
        return io.BytesIO(json.dumps({"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Ok"}]}]}).encode())

    monkeypatch.setattr(llm_openai, "urlopen", fake_urlopen)
    out = llm_openai.complete("S", "U", budget_s=42)
    assert out["text"] == "Ok" and seen["timeout"] == 42 and seen["body"]["max_output_tokens"] == 16000


# ---------- intelligence (4, 34, 35, 36, 44, 47) ----------
def test_bull_bear_is_rule_based_even_with_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")

    def boom(*a, **k):
        raise AssertionError("no network call expected")

    monkeypatch.setattr(intelligence, "urlopen", boom)
    out = intelligence.bull_bear("MSFT", 80.0, ["a"], ["b"])
    assert out["mode"] == "RULE_BASED" and out["model_provider"] == "none"
    assert not hasattr(intelligence, "_openai_synthesis")


def test_low_score_is_not_called_favorable():
    out = intelligence.bull_bear("X", 41.0, ["cat"], ["risk"])
    assert out["band"] == "Low score"
    assert not any("favorable modeled factors" in s for s in out["bull"])
    assert any("Low score" in s for s in out["bear"])
    high = intelligence.bull_bear("X", 90.0, ["cat"], ["risk"])
    assert "High score" in high["bull"][0]


RSS = """<?xml version="1.0"?><rss><channel>
<item><title><![CDATA[Apple beats estimates]]></title><link>https://example.com/a?x=1&amp;y=2</link>
<description><![CDATA[<p>Revenue &amp; margins rose</p>]]></description><pubDate>Mon, 02 Nov 2026 14:30:00 GMT</pubDate></item>
<item><title>No date &amp; more</title><link>https://example.com/b</link></item>
</channel></rss>"""


def test_rss_parses_cdata_entities_and_pubdate():
    items = intelligence.parse_rss(RSS, "https://feed", 10, "Test")
    assert items[0].title == "Apple beats estimates"
    assert items[0].source == "https://example.com/a?x=1&y=2"
    assert items[0].summary == "Revenue & margins rose"
    assert items[0].timestamp == 1793629800
    assert items[1].title == "No date & more" and items[1].timestamp is None


def test_sec_feed_needs_declared_user_agent_and_news_is_cached(monkeypatch):
    requests = []

    def fake_urlopen(req, timeout):
        requests.append((req.full_url, req.get_header("User-agent")))
        return io.BytesIO(RSS.encode())

    monkeypatch.setattr(intelligence, "urlopen", fake_urlopen)
    out = intelligence.market_intelligence()
    assert all("sec.gov" not in url for url, _ in requests)
    assert out["source_count"] == 1 and out["status"] == "LIVE"
    assert {f["name"]: f["status"] for f in out["feeds"]}["SEC press releases"] == "SKIPPED"
    intelligence.market_intelligence()
    assert len(requests) == 1  # cached

    intelligence._NEWS_CACHE.clear()
    requests.clear()
    monkeypatch.setenv("SEC_USER_AGENT", "Jane Doe jane@example.com")
    out = intelligence.market_intelligence()
    sec = [ua for url, ua in requests if "sec.gov" in url]
    assert sec == ["Jane Doe jane@example.com"] and out["source_count"] == 2


def test_news_failures_are_reported_not_raised(monkeypatch):
    def fail(req, timeout):
        raise ConnectionResetError("reset")

    monkeypatch.setattr(intelligence, "urlopen", fail)
    out = intelligence.market_intelligence()
    assert out["items"] == [] and out["status"] == "UNAVAILABLE" and out["source_count"] == 0
