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
