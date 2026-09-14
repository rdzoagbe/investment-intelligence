from __future__ import annotations

from dataclasses import asdict
from math import isfinite

from .data import ASSETS, AssetSnapshot, get_asset
from .fundamentals import fundamentals_for_asset
from .market_data import live_quotes
from .risk import position_risk
from .valuation import scenario_values


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_asset(asset: AssetSnapshot, quote: dict[str, object] | None = None) -> dict[str, object]:
    price = float(quote["price"]) if quote and isinstance(quote.get("price"), (int, float)) else asset.price
    change_pct = float(quote["change_pct"]) if quote and isinstance(quote.get("change_pct"), (int, float)) else asset.change_pct
    fundamentals = fundamentals_for_asset(asset)
    growth_input = fundamentals.revenue_growth_pct if fundamentals.revenue_growth_pct is not None else asset.revenue_growth_pct
    margin_input = fundamentals.operating_margin_pct if fundamentals.operating_margin_pct is not None else asset.operating_margin_pct
    fcf_input = fundamentals.free_cash_flow_margin_pct if fundamentals.free_cash_flow_margin_pct is not None else asset.free_cash_flow_margin_pct
    fundamental = clamp(35 + margin_input * 0.55 + fcf_input * 0.35 + max(growth_input, 0) * 0.8 - max(asset.net_debt_to_ebitda, 0) * 7)
    growth = clamp(45 + growth_input * 2.1)
    cash_flow = clamp(35 + fcf_input * 1.35)
    balance_sheet = clamp(92 - max(asset.net_debt_to_ebitda, 0) * 18)
    valuation = clamp(108 - asset.pe_ratio * 1.15)
    momentum = clamp(asset.momentum_score)
    sentiment = clamp(asset.sentiment_score)
    composite = round(fundamental * 0.24 + growth * 0.18 + cash_flow * 0.16 + balance_sheet * 0.12 + valuation * 0.14 + momentum * 0.09 + sentiment * 0.07, 1)
    verdict = "BUY" if composite >= 85 else "WATCH" if composite >= 72 else "HOLD" if composite >= 60 else "AVOID"
    return {
        "symbol": asset.symbol, "name": asset.name, "market": asset.market, "currency": asset.currency,
        "price": price, "change_pct": change_pct, "score": composite, "verdict": verdict,
        "breakdown": {"fundamental": round(fundamental), "growth": round(growth), "cash_flow": round(cash_flow), "balance_sheet": round(balance_sheet), "valuation": round(valuation), "momentum": round(momentum), "sentiment": round(sentiment)},
        "fundamental_inputs": {"revenue_growth_pct": round(growth_input, 2), "operating_margin_pct": round(margin_input, 2), "free_cash_flow_margin_pct": round(fcf_input, 2), "source": fundamentals.source, "status": fundamentals.status},
        "macro_sensitivity": asset.macro_sensitivity,
        "price_source": str(quote.get("provider")) if quote else "Internal deterministic dataset",
        "price_status": str(quote.get("status")) if quote else "DEMO",
    }


def scanner(limit: int = 5) -> list[dict[str, object]]:
    quotes = {str(q["symbol"]): q for q in live_quotes()}
    ranked = sorted((score_asset(asset, quotes.get(asset.symbol)) for asset in ASSETS), key=lambda item: item["score"], reverse=True)
    return ranked[:limit]


def analyze_asset(symbol: str) -> dict[str, object] | None:
    asset = get_asset(symbol)
    if asset is None:
        return None
    quote = next((q for q in live_quotes() if q["symbol"] == asset.symbol), None)
    scored = score_asset(asset, quote)
    current_price = float(scored["price"])
    scenarios = scenario_values(current_price, asset.revenue_growth_pct, asset.pe_ratio)
    base = next(item for item in scenarios if item["label"] == "Base")
    risk = position_risk(portfolio_value=12450, entry_price=current_price, stop_price=current_price * 0.92, max_risk_pct=1.0)
    return {
        **scored,
        "thesis": {
            "bull": [f"Revenue growth is {scored['fundamental_inputs']['revenue_growth_pct']:.1f}% from the tracked fundamental source.", f"Operating margin is {scored['fundamental_inputs']['operating_margin_pct']:.1f}% and free-cash-flow margin is {scored['fundamental_inputs']['free_cash_flow_margin_pct']:.1f}%.", asset.catalysts[0]],
            "bear": [f"A P/E of {asset.pe_ratio:.1f} leaves valuation sensitivity in the thesis.", asset.risks[0], asset.risks[1]],
            "invalidation": "The thesis is weakened materially if growth, cash generation or balance-sheet quality deteriorate versus the tracked assumptions.",
            "market_question": "What does the market already know that this score may be missing?",
        },
        "valuation": {"scenarios": scenarios, "base_case": base},
        "risk": risk,
        "raw_inputs": asdict(asset),
        "data_status": "LIVE_MARKET_DATA" if scored["price_status"] == "LIVE" else "DEMO_DATASET",
    }


def validate_numeric_values(payload: dict[str, object]) -> None:
    for key, value in payload.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not isfinite(float(value)):
            raise ValueError(f"Non-finite numeric value for {key}")
