from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Every test gets its own SQLite file and no external network by default."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ASSISTANT_PROVIDER", raising=False)
    monkeypatch.delenv("JOB_TOKEN", raising=False)
    monkeypatch.setenv("MARKET_DATA_MODE", "demo")
    monkeypatch.setenv("FUNDAMENTALS_MODE", "demo")
    monkeypatch.delenv("RENDER", raising=False)
    # The dashboard's fire-and-forget snapshot thread could outlive the test and write to
    # another test's database; tests of that hook enable it explicitly.
    monkeypatch.setenv("DASHBOARD_DAILY_SNAPSHOT", "false")
    from app import history, market_data, ratelimit
    ratelimit.reset()
    history._CACHE.clear()
    market_data._CACHE.clear()
