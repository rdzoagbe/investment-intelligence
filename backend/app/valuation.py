from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValuationScenario:
    label: str
    revenue_growth: float
    terminal_multiple: float
    fair_value: float


def scenario_values(price: float, revenue_growth_pct: float, pe_ratio: float) -> list[dict[str, float | str]]:
    """Simple scenario scaffold; assumptions are intentionally explicit and inspectable."""
    # Bear inputs are derived from Base and can never exceed it (a fixed floor would
    # invert the ordering for low P/E or negative growth).
    bear_growth = min(revenue_growth_pct, max(revenue_growth_pct - 8, -90.0))
    bear_multiple = min(pe_ratio, max(pe_ratio - 8, pe_ratio * 0.7))
    scenarios = [
        ("Bear", bear_growth, bear_multiple),
        ("Base", revenue_growth_pct, pe_ratio),
        ("Bull", revenue_growth_pct + 6, pe_ratio + 6),
    ]
    values: list[dict[str, float | str]] = []
    for label, growth, multiple in scenarios:
        growth_factor = 1 + growth / 100
        fair_value = round(price * growth_factor * (multiple / max(pe_ratio, 1)), 2)
        upside_pct = round((fair_value / price - 1) * 100, 1)
        values.append({"label": label, "growth_pct": round(growth, 1), "multiple": round(multiple, 1), "fair_value": fair_value, "upside_pct": upside_pct})
    return values
