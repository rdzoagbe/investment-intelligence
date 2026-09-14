from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 10000.0
    position_pct: float = 0.20
    buy_threshold: float = 85.0
    sell_threshold: float = 60.0
    transaction_cost_bps: float = 10.0


def run_backtest(prices: list[float], scores: list[float], config: BacktestConfig | None = None) -> dict[str, object]:
    """Replay a deterministic score signal against supplied historical closes."""
    cfg = config or BacktestConfig()
    if len(prices) != len(scores) or len(prices) < 2:
        raise ValueError("prices and scores must have the same length and contain at least two observations")
    cash = cfg.initial_cash
    shares = 0.0
    equity: list[float] = []
    trades: list[dict[str, object]] = []
    for i, (price, score) in enumerate(zip(prices, scores)):
        if price <= 0:
            raise ValueError("historical prices must be positive")
        equity_value = cash + shares * price
        target = equity_value * cfg.position_pct / price if score >= cfg.buy_threshold else 0.0 if score < cfg.sell_threshold else shares
        delta = target - shares
        if abs(delta) > 1e-12:
            notional = abs(delta) * price
            fee = notional * cfg.transaction_cost_bps / 10000
            cash -= delta * price + fee
            shares = target
            trades.append({"index": i, "side": "BUY" if delta > 0 else "SELL", "price": price, "shares": abs(delta), "fee": round(fee, 4), "score": score})
        equity.append(cash + shares * price)
    total_return = equity[-1] / cfg.initial_cash - 1
    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        max_dd = min(max_dd, value / peak - 1)
    return {"initial_cash": cfg.initial_cash, "final_equity": round(equity[-1], 2), "total_return_pct": round(total_return * 100, 2), "max_drawdown_pct": round(max_dd * 100, 2), "trade_count": len(trades), "equity_curve": [round(x, 2) for x in equity], "trades": trades, "config": cfg.__dict__}
