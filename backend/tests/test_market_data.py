from __future__ import annotations

import os

from app.data import get_asset
from app.market_data import quote_for_asset


def test_demo_mode_is_deterministic(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "demo")
    asset = get_asset("MSFT")
    assert asset is not None
    quote = quote_for_asset(asset)
    assert quote.status == "DEMO"
    assert quote.price == asset.price
    assert quote.change_pct == asset.change_pct


def test_unknown_yahoo_mapping_uses_fallback(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_MODE", "live")
    asset = get_asset("ACCESS")
    assert asset is not None
    quote = quote_for_asset(asset)
    assert quote.symbol == "ACCESS"
    assert quote.status == "DEMO"
    assert quote.provider == "Internal deterministic dataset"
