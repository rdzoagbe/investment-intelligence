from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient

from app import assistant, llm, llm_anthropic
from app.main import app

client = TestClient(app)


def login(email="u@example.com"):
    r = client.post("/api/auth/register", json={"name": "User", "email": email, "password": "long-enough-1", "accept_terms": True})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_requires_login():
    assert client.post("/api/assistant/ask", json={"question": "hello there"}).status_code == 401


def test_without_a_model_returns_evidence_only():
    h = login()
    r = client.post("/api/assistant/ask", json={"question": "How does NVDA compare with Microsoft?"}, headers=h).json()
    assert r["provider"] == "none" and r["answer"] is None
    titles = [e["title"] for e in r["evidence"]]
    assert "NVDA price" in titles and "MSFT price" in titles
    assert all(e["id"] == f"E{i + 1}" for i, e in enumerate(r["evidence"]))
    assert next(e for e in r["evidence"] if e["title"] == "NVDA price")["status"] == "DEMO"


def test_personal_data_only_when_asked_and_only_own():
    a, b = login("a@example.com"), login("b@example.com")
    client.post("/api/me/holdings", json={"symbol": "MSFT", "quantity": 2, "average_cost": 100}, headers=a)
    ev_b = client.post("/api/assistant/ask", json={"question": "What is in my portfolio?"}, headers=b).json()["evidence"]
    assert not any("MSFT" in e["title"] for e in ev_b)
    ev_a = client.post("/api/assistant/ask", json={"question": "What is in my portfolio?"}, headers=a).json()["evidence"]
    # Demo mode: the holding is valued from a DEMO quote, so it is labelled DEMO, not USER.
    holding = next(e for e in ev_a if e["title"] == "Your holding MSFT")
    assert holding["status"] == "DEMO" and holding["personal"] is True and "DEMO price" in holding["detail"]
    ev_general = client.post("/api/assistant/ask", json={"question": "Tell me about Microsoft"}, headers=a).json()["evidence"]
    assert not any(e["status"] == "USER" or e["personal"] for e in ev_general)


def fake_model(monkeypatch, text="", refused=False, raise_exc=None):
    calls = []
    def complete(system, user, budget_s=None):
        calls.append((system, user))
        if raise_exc:
            raise raise_exc
        return {"text": text, "model": "test-model", "refused": refused, "provider": "anthropic"}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(llm, "complete", complete)
    return calls


def test_valid_citations_are_kept_and_prompt_is_grounded(monkeypatch):
    calls = fake_model(monkeypatch, "NVDA's score is high [E2] but valuation is a seed input [E4].")
    r = client.post("/api/assistant/ask", json={"question": "Is NVDA attractive?"}, headers=login()).json()
    assert r["grounded"] is True and r["citations"] == ["E2", "E4"]
    system, user = calls[0]
    assert "Use only the numbered evidence" in system and "Do not tell the user to buy, sell or hold" in system
    assert "[E1] NVDA price | status: DEMO" in user and "<question>" in user


def test_invented_citations_are_removed_and_flagged(monkeypatch):
    fake_model(monkeypatch, "Revenue doubled [E99]. Score is high [E2].")
    r = client.post("/api/assistant/ask", json={"question": "Is NVDA attractive?"}, headers=login()).json()
    assert "[E99]" not in r["answer"] and r["removed_citations"] == ["E99"] and r["grounded"] is False


def test_uncited_answer_is_flagged_unverified(monkeypatch):
    fake_model(monkeypatch, "It is a great company.")
    r = client.post("/api/assistant/ask", json={"question": "Is NVDA attractive?"}, headers=login()).json()
    assert r["grounded"] is False and "unverified" in r["notice"]


def test_refusal_and_provider_errors_degrade_to_evidence(monkeypatch):
    fake_model(monkeypatch, refused=True)
    r = client.post("/api/assistant/ask", json={"question": "Is NVDA attractive?"}, headers=login("r@example.com")).json()
    assert r["answer"] is None and "declined" in r["notice"] and r["evidence"]
    fake_model(monkeypatch, raise_exc=TimeoutError())
    r = client.post("/api/assistant/ask", json={"question": "Is NVDA attractive?"}, headers=login("t@example.com")).json()
    assert r["answer"] is None and "TimeoutError" in r["notice"]


def test_daily_limit_falls_back_to_evidence(monkeypatch):
    calls = fake_model(monkeypatch, "Score [E2].")
    monkeypatch.setenv("ASSISTANT_DAILY_LIMIT", "1")
    h = login("lim@example.com")
    assert client.post("/api/assistant/ask", json={"question": "Is NVDA attractive?"}, headers=h).json()["answer"]
    r = client.post("/api/assistant/ask", json={"question": "Is NVDA attractive?"}, headers=h).json()
    assert r["answer"] is None and "Daily limit" in r["notice"] and len(calls) == 1
    assert len(client.get("/api/me/assistant/history", headers=h).json()["items"]) == 2


def test_provider_selection(monkeypatch):
    assert llm.provider() == "none"
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert llm.provider() == "openai"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    assert llm.provider() == "anthropic"
    monkeypatch.setenv("ASSISTANT_PROVIDER", "openai")
    assert llm.provider() == "openai"
    monkeypatch.setenv("ASSISTANT_PROVIDER", "none")
    assert llm.provider() == "none"


class FakeAnthropic:
    last: dict = {}
    def __init__(self, **kwargs):
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))
    def _create(self, **kwargs):
        FakeAnthropic.last = kwargs
        stop = kwargs.pop("_stop", None)
        return types.SimpleNamespace(stop_reason=FakeAnthropic.stop, model=kwargs["model"], content=[
            types.SimpleNamespace(type="thinking", thinking=""), types.SimpleNamespace(type="text", text=" Answer [E1]. ")])


def test_anthropic_request_shape(monkeypatch):
    monkeypatch.setattr(llm_anthropic.anthropic, "Anthropic", FakeAnthropic)
    FakeAnthropic.stop = "end_turn"
    out = llm_anthropic.complete("SYS", "USER")
    k = FakeAnthropic.last
    assert k["model"] == "claude-opus-5-5" and k["system"] == "SYS"
    assert k["messages"] == [{"role": "user", "content": "USER"}]
    assert k["fallbacks"] == "default" and k["betas"] == ["server-side-fallback-2026-07-01"]
    assert k["output_config"] == {"effort": "high"} and "thinking" not in k
    assert k["max_tokens"] == 16000
    assert out == {"text": "Answer [E1].", "model": "claude-opus-5-5", "refused": False, "truncated": False, "provider": "anthropic"}
    FakeAnthropic.stop = "refusal"
    assert llm_anthropic.complete("S", "U")["refused"] is True
