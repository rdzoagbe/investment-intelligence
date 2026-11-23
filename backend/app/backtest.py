from __future__ import annotations

from dataclasses import dataclass

from .history import PriceHistory, sma


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 10000.0
    position_pct: float = 0.20
    buy_threshold: float = 85.0
    sell_threshold: float = 60.0
    transaction_cost_bps: float = 10.0


def _max_drawdown(equity: list[float]) -> float:
    peak, max_dd = equity[0], 0.0
    for value in equity:
        peak = max(peak, value)
        max_dd = min(max_dd, value / peak - 1)
    return max_dd


def run_backtest(prices: list[float], scores: list[float], config: BacktestConfig | None = None) -> dict[str, object]:
    """Replay a signal against historical closes.

    Enters when the signal reaches buy_threshold while flat, exits when it falls below
    sell_threshold while invested, and otherwise holds (no daily rebalancing churn).
    A signal at index i is acted on at the close of index i.
    """
    cfg = config or BacktestConfig()
    if len(prices) != len(scores) or len(prices) < 2:
        raise ValueError("prices and scores must have the same length and contain at least two observations")
    cash, shares = cfg.initial_cash, 0.0
    equity: list[float] = []
    trades: list[dict[str, object]] = []
    for i, (price, score) in enumerate(zip(prices, scores)):
        if price <= 0:
            raise ValueError("historical prices must be positive")
        if shares == 0 and score >= cfg.buy_threshold:
            budget = (cash + shares * price) * cfg.position_pct
            qty = budget / (price * (1 + cfg.transaction_cost_bps / 10000))
            fee = qty * price * cfg.transaction_cost_bps / 10000
            cash -= qty * price + fee
            shares = qty
            trades.append({"index": i, "side": "BUY", "price": price, "shares": qty, "fee": round(fee, 4), "score": score})
        elif shares > 0 and score < cfg.sell_threshold:
            fee = shares * price * cfg.transaction_cost_bps / 10000
            cash += shares * price - fee
            trades.append({"index": i, "side": "SELL", "price": price, "shares": shares, "fee": round(fee, 4), "score": score})
            shares = 0.0
        equity.append(cash + shares * price)
    return {"initial_cash": cfg.initial_cash, "final_equity": round(equity[-1], 2), "total_return_pct": round((equity[-1] / cfg.initial_cash - 1) * 100, 2),
            "max_drawdown_pct": round(_max_drawdown(equity) * 100, 2), "trade_count": len(trades), "equity_curve": [round(x, 2) for x in equity],
            "trades": trades, "config": cfg.__dict__}


def trend_backtest(history: PriceHistory, window: int = 200, transaction_cost_bps: float = 10.0, initial_cash: float = 10000.0) -> dict[str, object]:
    """Price-only trend rule on real history versus buy-and-hold.

    Invested when the close is above its `window`-day average, in cash otherwise. It uses
    only information available on each date, so it has no look-ahead bias. The composite
    research score is NOT backtested: its fundamental inputs are today's values, not
    point-in-time data, so replaying it on past prices would be misleading.
    """
    closes = history.closes
    if len(closes) <= window + 1:
        raise ValueError(f"need more than {window + 1} daily closes; got {len(closes)}")
    avg = sma(closes, window)
    start = window - 1  # first index with a defined average
    prices = closes[start:]
    signal = [100.0 if closes[i] > (avg[i] or 0) else 0.0 for i in range(start, len(closes))]
    cfg = BacktestConfig(initial_cash, 1.0, 50.0, 50.0, transaction_cost_bps)
    strategy = run_backtest(prices, signal, cfg)
    hold_fee = transaction_cost_bps / 10000
    hold_shares = initial_cash / (prices[0] * (1 + hold_fee))
    hold_curve = [round(hold_shares * p, 2) for p in prices]
    dates = history.dates[start:]
    years = max(len(prices) - 1, 1) / 252
    def cagr(final: float) -> float:
        return round(((final / initial_cash) ** (1 / years) - 1) * 100, 2)
    price_basis = ("Uses adjusted closes (splits and dividends)" if history.adjusted
                   else "Uses closes adjusted for splits only (dividend-adjusted series unavailable), so returns exclude dividends")
    return {
        "symbol": history.symbol, "currency": history.currency, "provider": history.provider, "status": "LIVE", "adjusted": history.adjusted,
        "rule": f"Hold when the close is above its {window}-day average, otherwise cash. Costs {transaction_cost_bps} bps per trade.",
        "start": dates[0], "end": dates[-1], "dates": dates,
        "strategy": {"final_equity": strategy["final_equity"], "total_return_pct": strategy["total_return_pct"], "cagr_pct": cagr(strategy["final_equity"]),
                     "max_drawdown_pct": strategy["max_drawdown_pct"], "trade_count": strategy["trade_count"], "equity_curve": strategy["equity_curve"],
                     "time_invested_pct": round(sum(1 for s in signal if s > 0) / len(signal) * 100, 1)},
        "buy_and_hold": {"final_equity": hold_curve[-1], "total_return_pct": round((hold_curve[-1] / initial_cash - 1) * 100, 2), "cagr_pct": cagr(hold_curve[-1]),
                         "max_drawdown_pct": round(_max_drawdown(hold_curve) * 100, 2), "equity_curve": hold_curve},
        "caveats": ["Past performance does not predict future results.", f"{price_basis}; ignores taxes, slippage beyond the stated cost, and dividends received while in cash.",
                    "The composite research score is not backtested because its fundamental inputs are not point-in-time."],
    }
