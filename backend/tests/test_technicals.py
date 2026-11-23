from __future__ import annotations

import math

import pytest

from app.technicals import overlays, support_resistance, trend_line


def test_trend_line_recovers_constant_growth():
    closes = [100 * math.exp(0.001 * i) for i in range(300)]
    t = trend_line(closes)
    assert t is not None and t["direction"] == "UP"
    assert t["r_squared"] == pytest.approx(1.0, abs=1e-6)
    assert t["annualised_slope_pct"] == pytest.approx((math.exp(0.252) - 1) * 100, abs=0.05)
    assert t["values"][0] == pytest.approx(100, rel=1e-4) and len(t["values"]) == 300


def test_trend_line_needs_enough_positive_data():
    assert trend_line([1.0] * 10) is None
    assert trend_line([1.0] * 30 + [0.0]) is None


def test_support_and_resistance_from_repeated_turning_points():
    # Oscillates between ~90 and ~110 several times, then sits at 100.
    closes = []
    for _ in range(5):
        closes += [100 + 10 * math.sin(math.pi * k / 10) for k in range(20)]
    closes += [100.0] * 3
    dates = [f"d{i}" for i in range(len(closes))]
    lv = support_resistance(closes, dates)
    assert lv["resistance"] and lv["support"]
    r, s = lv["resistance"][0], lv["support"][0]
    assert r["level"] == pytest.approx(110, rel=0.01) and r["touches"] >= 3 and r["strength"] == "STRONG"
    assert s["level"] == pytest.approx(90, rel=0.01) and s["touches"] >= 3
    assert r["distance_pct"] > 0 > s["distance_pct"]


def test_levels_are_on_the_correct_side_of_price():
    closes = [100 + (i % 17) - (i % 5) * 1.5 for i in range(250)]
    lv = support_resistance(closes, [str(i) for i in range(250)])
    assert all(x["level"] < closes[-1] for x in lv["support"])
    assert all(x["level"] > closes[-1] for x in lv["resistance"])


def test_overlays_shape_and_moving_averages():
    closes = [float(i + 1) for i in range(260)]
    o = overlays(closes, [str(i) for i in range(260)])
    assert len(o["sma50"]) == 260 and o["sma50"][48] is None and o["sma50"][49] == pytest.approx(25.5)
    assert o["sma200"][199] == pytest.approx(100.5)
    assert "not forecasts" in o["disclaimer"]
