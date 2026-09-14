from __future__ import annotations


def position_risk(
    portfolio_value: float,
    entry_price: float,
    stop_price: float,
    max_risk_pct: float = 1.0,
) -> dict[str, float]:
    if portfolio_value <= 0 or entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        raise ValueError("portfolio_value, entry_price and a lower stop_price are required")
    risk_per_share = entry_price - stop_price
    risk_budget = portfolio_value * (max_risk_pct / 100)
    shares = risk_budget / risk_per_share
    position_value = shares * entry_price
    position_weight_pct = (position_value / portfolio_value) * 100
    return {
        "risk_budget": round(risk_budget, 2),
        "risk_per_share": round(risk_per_share, 2),
        "shares": round(shares, 4),
        "position_value": round(position_value, 2),
        "position_weight_pct": round(position_weight_pct, 2),
        "max_risk_pct": max_risk_pct,
    }
