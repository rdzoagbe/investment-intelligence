from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
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
    provider: str = "none"


class BrokerGateway:
    """Broker boundary. Paper execution may be enabled; live execution remains disabled by default."""
    def __init__(self) -> None:
        self.live_enabled = os.getenv("LIVE_TRADING_ENABLED", "false").strip().lower() == "true"
        self.paper_enabled = os.getenv("PAPER_BROKER_ENABLED", "false").strip().lower() == "true"
        self.paper_url = os.getenv("PAPER_BROKER_URL", "https://paper-api.alpaca.markets").rstrip("/")

    def preview(self, symbol: str, side: str, quantity: float, order_type: str = "MARKET") -> BrokerOrder:
        if side.upper() not in {"BUY", "SELL"} or quantity <= 0: raise ValueError("invalid order")
        return BrokerOrder(str(uuid4()), symbol.upper(), side.upper(), quantity, order_type.upper(), False, self.live_enabled, "PENDING_HUMAN_APPROVAL", "alpaca" if self.paper_enabled else "none")

    def _paper_submit(self, order: BrokerOrder) -> str:
        key, secret = os.getenv("ALPACA_PAPER_API_KEY"), os.getenv("ALPACA_PAPER_API_SECRET")
        if not key or not secret: return "PAPER_CREDENTIALS_NOT_CONFIGURED"
        payload = json.dumps({"symbol": order.symbol, "qty": str(order.quantity), "side": order.side.lower(), "type": order.order_type.lower(), "time_in_force": "day"}).encode()
        request = Request(f"{self.paper_url}/v2/orders", data=payload, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=15) as response:  # noqa: S310 - fixed provider URL from configuration
                result = json.loads(response.read().decode())
            return f"PAPER_SUBMITTED:{result.get('id', 'unknown')}"
        except (HTTPError, URLError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return f"PAPER_ERROR:{type(exc).__name__}"

    def execute(self, order: BrokerOrder, human_approved: bool) -> BrokerOrder:
        if not human_approved: return BrokerOrder(order.id, order.symbol, order.side, order.quantity, order.order_type, False, self.live_enabled, "REJECTED_NO_HUMAN_APPROVAL", order.provider)
        if self.live_enabled: return BrokerOrder(order.id, order.symbol, order.side, order.quantity, order.order_type, True, True, "LIVE_BLOCKED_IN_PUBLIC_BUILD", order.provider)
        if self.paper_enabled:
            status = self._paper_submit(order)
            return BrokerOrder(order.id, order.symbol, order.side, order.quantity, order.order_type, True, False, status, "alpaca-paper")
        return BrokerOrder(order.id, order.symbol, order.side, order.quantity, order.order_type, True, False, "PAPER_BROKER_DISABLED", order.provider)


gateway = BrokerGateway()
