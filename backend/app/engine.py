from __future__ import annotations

from dataclasses import asdict
from math import isfinite

from .data import ASSETS, AssetSnapshot, get_asset
from .risk import position_risk
from .valuation import scenario_values


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_asset(asset: AssetSnapshot) -> dict[str, object]:
    fundamental = clamp(35 + asset.operating_margin_pct * 0.55 + asset.free_cash_flow_margin_pct * 0.35 + max(asset.revenue_growth_pct, 0) * 0.8 - max(asset.net_debt_to_ebitda, 0) * 7)
    growth = clamp(45 + asset.revenue_growth_pct * 2.1)
    cash_flow = clamp(35 + asset.free_cash_flow_margin_pct * 1.35)
    balance_sheet = clamp(92 - max(asset.net_debt_to_ebitda, 0) * 18)
    valuation = clamp(108 - asset.pe_ratio * 1.15)
    momentum = clamp(asset.momentum_score)
    sentiment = clamp(asset.sentiment_score)

    composite = round(
        fundamental * 0.24 + growth * 0.18 + cash_flow * 0.16 + balance_sheet * 0.12 + valuation * 0.14 + momentum * 0.09 + sentiment * 0.07,
        1,
    )
    verdict = "BUY" if composite >= 85 else "WATCH" if composite >= 72 else "HOLD" if composite >= 60 else "AVOID"
    return {
        "symbol": asset.symbol,
        "name": asset.name,
        "market": asset.market,
        "currency": asset.currency,
        "price": asset.price,
        "change_pct": asset.change_pct,
        "score": composite,
        "verdict": verdict,
        "breakdown": {
            "fundamental": round(fundamental), "growth": round(growth), "cash_flow": round(cash_flow),
            "balance_sheet": round(balance_sheet), "valuation": round(valuation), "momentum": round(momentum), "sentiment": round(sentiment),
        },
        "macro_sensitivity": asset.macro_sensitivity,
    }


def scanner(limit: int = 5) -> list[dict[str, object]]:
    ranked = sorted((score_asset(asset) for asset in ASSETS), key=lambda item: item["score"], reverse=True)
    return ranked[:limit]


def analyze_asset(symbol: str) -> dict[str, object] | None:
    asset = get_asset(symbol)
    if asset is None:
        return None

    scored = score_asset(asset)
    scenarios = scenario_values(asset.price, asset.revenue_growth_pct, asset.pe_ratio)
    base = next(item for item in scenarios if item["label"] == "Base")
    risk = position_risk(portfolio_value=12450, entry_price=asset.price, stop_price=asset.price * 0.92, max_risk_pct=1.0)

    return {
        **scored,
        "thesis": {
            "bull": [
                f"Revenue growth is {asset.revenue_growth_pct:.1f}% in the model dataset.",
                f"Operating margin is {asset.operating_margin_pct:.1f}% and free-cash-flow margin is {asset.free_cash_flow_margin_pct:.1f}%.",
                asset.catalysts[0],
            ],
            "bear": [
                f"A P/E of {asset.pe_ratio:.1f} leaves valuation sensitivity in the thesis.",
                asset.risks[0],
                asset.risks[1],
            ],
            "invalidation": "The thesis is weakened materially if growth, cash generation or balance-sheet quality deteriorate versus the tracked assumptions.",
            "market_question": "What does the market already know that this score may be missing?",
        },
        "valuation": {"scenarios": scenarios, "base_case": base},
        "risk": risk,
        "raw_inputs": asdict(asset),
        "data_status": "DEMO_DATASET",
    }


def validate_numeric_values(payload: dict[str, object]) -> None:
    for key, value in payload.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not isfinite(float(value)):
            raise ValueError(f"Non-finite numeric value for {key}")
