from __future__ import annotations

import json
import os
import re
import threading
import time
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


SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
# Only market orders: the paper payload carries no limit price, so a LIMIT order would be malformed.
ORDER_TYPES = {"MARKET"}
MAX_QUANTITY = 10_000.0
PREVIEW_TTL_SECONDS = 10 * 60


class BrokerGateway:
    """Broker boundary. Paper execution may be enabled; live execution remains disabled by default.

    Approval is bound to a server-side preview: execution re-reads the stored order for the
    same user instead of rebuilding it from the request body.
    """
    def __init__(self) -> None:
        self.live_enabled = os.getenv("LIVE_TRADING_ENABLED", "false").strip().lower() == "true"
        self.paper_enabled = os.getenv("PAPER_BROKER_ENABLED", "false").strip().lower() == "true"
        self.paper_url = os.getenv("PAPER_BROKER_URL", "https://paper-api.alpaca.markets").rstrip("/")
        self._pending: dict[str, tuple[int, BrokerOrder, float]] = {}
        self._lock = threading.Lock()

    def preview(self, symbol: str, side: str, quantity: float, order_type: str = "MARKET", user_id: int | None = None) -> BrokerOrder:
        symbol, side, order_type = symbol.strip().upper(), side.strip().upper(), order_type.strip().upper()
        if side not in {"BUY", "SELL"} or not (0 < quantity <= MAX_QUANTITY): raise ValueError("invalid order: side must be BUY or SELL and quantity between 0 and 10,000")
        if not SYMBOL_PATTERN.match(symbol): raise ValueError("invalid order: unsupported symbol format")
        if order_type not in ORDER_TYPES: raise ValueError("invalid order: only MARKET orders are supported")
        order = BrokerOrder(str(uuid4()), symbol, side, quantity, order_type, False, self.live_enabled, "PENDING_HUMAN_APPROVAL", "alpaca" if self.paper_enabled else "none")
        if user_id is not None:
            now = time.time()
            with self._lock:
                for key in [k for k, (_, _, exp) in self._pending.items() if exp < now]:
                    del self._pending[key]
                self._pending[order.id] = (int(user_id), order, now + PREVIEW_TTL_SECONDS)
        return order

    def take_preview(self, preview_id: str, user_id: int) -> BrokerOrder | None:
        """Consume a stored preview created by the same user. None if unknown, expired or someone else's."""
        with self._lock:
            entry = self._pending.get(preview_id)
            if entry is None or entry[0] != int(user_id):
                return None
            del self._pending[preview_id]
        return entry[1] if entry[2] >= time.time() else None

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
