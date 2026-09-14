from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class BrokerOrder:
    id: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    approved_by_human: bool
    live_enabled: bool
    status: str


class BrokerGateway:
    """Safety boundary for future broker adapters. Live execution is opt-in and approval-gated."""
    def __init__(self) -> None:
        self.live_enabled = os.getenv("LIVE_TRADING_ENABLED", "false").strip().lower() == "true"

    def preview(self, symbol: str, side: str, quantity: float, order_type: str = "MARKET") -> BrokerOrder:
        if side.upper() not in {"BUY", "SELL"} or quantity <= 0:
            raise ValueError("invalid order")
        return BrokerOrder(str(uuid4()), symbol.upper(), side.upper(), quantity, order_type.upper(), False, self.live_enabled, "PENDING_HUMAN_APPROVAL")

    def execute(self, order: BrokerOrder, human_approved: bool) -> BrokerOrder:
        if not human_approved:
            return BrokerOrder(order.id, order.symbol, order.side, order.quantity, order.order_type, False, self.live_enabled, "REJECTED_NO_HUMAN_APPROVAL")
        if not self.live_enabled:
            return BrokerOrder(order.id, order.symbol, order.side, order.quantity, order.order_type, True, False, "BLOCKED_LIVE_TRADING_DISABLED")
        # Deliberately no live broker implementation is shipped in the public demo.
        return BrokerOrder(order.id, order.symbol, order.side, order.quantity, order.order_type, True, True, "ADAPTER_NOT_CONFIGURED")


gateway = BrokerGateway()
