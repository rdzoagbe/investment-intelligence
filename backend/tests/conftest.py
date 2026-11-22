from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Every test gets its own SQLite file and no external network by default."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MARKET_DATA_MODE", "demo")
    monkeypatch.setenv("FUNDAMENTALS_MODE", "demo")
    from app import history, market_data
    history._CACHE.clear()
    market_data._CACHE.clear()
