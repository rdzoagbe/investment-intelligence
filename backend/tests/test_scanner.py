from __future__ import annotations

from app.data import ASSETS
from app.engine import scanner


def test_scanner_ranks_full_seed_universe():
    ranked = scanner(100)
    assert len(ranked) == len(ASSETS)
    scores = [item["score"] for item in ranked]
    assert scores == sorted(scores, reverse=True)
    assert len({item["symbol"] for item in ranked}) == len(ASSETS)


def test_scanner_limit_is_respected():
    assert len(scanner(3)) == 3


def test_scanner_emits_neutral_bands_only():
    for item in scanner(100):
        assert item["verdict"] in {"HIGH_SCORE", "WATCH", "NEUTRAL", "LOW_SCORE"}
        assert item["band"] in {"High score", "Watch", "Neutral", "Low score"}
        assert item["fundamental_inputs"]["status"] in {"LIVE", "PARTIAL", "DEMO"}
        assert set(item["fundamental_inputs"]["field_sources"]) == {"revenue_growth_pct", "operating_margin_pct", "free_cash_flow_margin_pct"}
