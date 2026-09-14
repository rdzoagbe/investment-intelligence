from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass
class PaperAccount:
    cash: float = 100000.0
    positions: dict[str, float] = field(default_factory=dict)
    average_cost: dict[str, float] = field(default_factory=dict)
    orders: list[dict[str, object]] = field(default_factory=list)

    def submit(self, symbol: str, side: str, quantity: float, price: float) -> dict[str, object]:
        side = side.upper()
        symbol = symbol.upper()
        if side not in {"BUY", "SELL"} or quantity <= 0 or price <= 0:
            raise ValueError("side must be BUY/SELL and quantity/price must be positive")
        notional = quantity * price
        if side == "BUY":
            if notional > self.cash:
                raise ValueError("insufficient paper cash")
            old_qty = self.positions.get(symbol, 0.0)
            old_cost = self.average_cost.get(symbol, 0.0)
            self.cash -= notional
            self.positions[symbol] = old_qty + quantity
            self.average_cost[symbol] = (old_qty * old_cost + notional) / self.positions[symbol]
        else:
            if quantity > self.positions.get(symbol, 0.0):
                raise ValueError("insufficient paper position")
            self.cash += notional
            self.positions[symbol] = self.positions.get(symbol, 0.0) - quantity
            if self.positions[symbol] <= 1e-12:
                self.positions.pop(symbol, None)
                self.average_cost.pop(symbol, None)
        order = {"id": str(uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "side": side, "quantity": quantity, "fill_price": price, "notional": notional, "status": "FILLED", "account": "PAPER"}
        self.orders.append(order)
        return order

    def snapshot(self, prices: dict[str, float]) -> dict[str, object]:
        market_value = sum(qty * prices.get(symbol, self.average_cost.get(symbol, 0.0)) for symbol, qty in self.positions.items())
        return {"cash": round(self.cash, 2), "market_value": round(market_value, 2), "equity": round(self.cash + market_value, 2), "positions": [{"symbol": s, "quantity": q, "average_cost": self.average_cost[s], "price": prices.get(s, self.average_cost[s]), "value": q * prices.get(s, self.average_cost[s])} for s, q in self.positions.items()], "orders": self.orders[-100:]}


paper_account = PaperAccount()
