from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class Holding:
    symbol: str
    quantity: float
    average_cost: float
    price: float
    currency: str = "USD"

    @property
    def market_value(self) -> float:
        return self.quantity * self.price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.average_cost

    @property
    def pnl(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def pnl_pct(self) -> float:
        return self.pnl / self.cost_basis * 100 if self.cost_basis else 0.0


def portfolio_snapshot(holdings: list[Holding], cash: float = 0.0, benchmark_return_pct: float = 0.0) -> dict[str, object]:
    invested = sum(h.market_value for h in holdings)
    total = invested + cash
    cost = sum(h.cost_basis for h in holdings)
    pnl = sum(h.pnl for h in holdings)
    allocation = [{"symbol": h.symbol, "value": round(h.market_value, 2), "weight_pct": round(h.market_value / total * 100, 2) if total else 0, "pnl": round(h.pnl, 2), "pnl_pct": round(h.pnl_pct, 2)} for h in holdings]
    concentration = max((x["weight_pct"] for x in allocation), default=0)
    return {"value": round(total, 2), "invested": round(invested, 2), "cash": round(cash, 2), "cash_pct": round(cash / total * 100, 2) if total else 0, "cost_basis": round(cost, 2), "pnl": round(pnl, 2), "return_pct": round(pnl / cost * 100, 2) if cost else 0, "benchmark_return_pct": benchmark_return_pct, "alpha_pct": round(pnl / cost * 100 - benchmark_return_pct, 2) if cost else 0, "largest_position_pct": concentration, "allocation": allocation, "risk_flags": (["HIGH_CONCENTRATION"] if concentration > 35 else []) + (["LOW_CASH"] if total and cash / total < 5 / 100 else [])}


def risk_metrics(returns: list[float], risk_free_pct: float = 0.0) -> dict[str, float | None]:
    if not returns:
        return {"volatility_pct": None, "sharpe": None, "max_drawdown_pct": None}
    mean = sum(returns) / len(returns)
    variance = sum((x - mean) ** 2 for x in returns) / max(len(returns) - 1, 1)
    volatility = sqrt(variance) * sqrt(252) * 100
    sharpe = ((mean * 252) - risk_free_pct / 100) / sqrt(variance) * sqrt(252) if variance > 0 else None
    wealth = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        wealth *= 1 + r
        peak = max(peak, wealth)
        max_dd = min(max_dd, wealth / peak - 1)
    return {"volatility_pct": round(volatility, 2), "sharpe": round(sharpe, 2) if sharpe is not None else None, "max_drawdown_pct": round(max_dd * 100, 2)}
