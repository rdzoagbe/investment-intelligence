"""Per-user portfolio holdings, decision journal and simulated (paper) trading.

All records are scoped by user_id. Paper orders always fill at the server's current
quote, never at a client-supplied price, and every fill records whether that quote
was LIVE or DEMO.
"""
from __future__ import annotations

import json
import time
from datetime import date

from . import db
from .data import get_asset
from .engine import score_asset
from .history import price_history, statistics
from .market_data import quote_dict, quote_for_asset

JOURNAL_DECISIONS = {"RESEARCH", "WATCH", "BUY", "ADD", "TRIM", "SELL", "PASS"}
JOURNAL_OUTCOMES = {"OPEN", "THESIS_CONFIRMED", "THESIS_BROKEN", "MIXED", "CLOSED"}


class UserDataError(ValueError):
    pass


def _asset_or_error(symbol: str):
    asset = get_asset(symbol)
    if asset is None:
        raise UserDataError(f"{symbol.upper()} is not in the research universe.")
    return asset


# ---------- Holdings ----------
def list_holdings(user_id: int) -> list[dict[str, object]]:
    return db.fetch_all("SELECT id,symbol,quantity,average_cost,created_at FROM holdings WHERE user_id=? ORDER BY symbol", (user_id,))


def upsert_holding(user_id: int, symbol: str, quantity: float, average_cost: float) -> dict[str, object]:
    asset = _asset_or_error(symbol)
    if quantity <= 0 or average_cost <= 0:
        raise UserDataError("Quantity and average cost must be positive.")
    existing = db.fetch_one("SELECT id FROM holdings WHERE user_id=? AND symbol=?", (user_id, asset.symbol))
    if existing:
        db.execute("UPDATE holdings SET quantity=?, average_cost=? WHERE id=?", (quantity, average_cost, existing["id"]))
    else:
        db.insert("INSERT INTO holdings(user_id,symbol,quantity,average_cost,created_at) VALUES(?,?,?,?,?)", (user_id, asset.symbol, quantity, average_cost, int(time.time())))
    return {"symbol": asset.symbol, "quantity": quantity, "average_cost": average_cost}


def delete_holding(user_id: int, symbol: str) -> None:
    db.execute("DELETE FROM holdings WHERE user_id=? AND symbol=?", (user_id, symbol.strip().upper()))


def portfolio(user_id: int) -> dict[str, object]:
    """Value holdings at current quotes. Totals are per currency: no FX conversion is applied."""
    rows = []
    totals: dict[str, dict[str, float]] = {}
    for h in list_holdings(user_id):
        asset = _asset_or_error(str(h["symbol"]))
        q = quote_dict(quote_for_asset(asset))
        price = float(q["price"])
        currency = str(q["currency"] or asset.currency)
        value, cost = float(h["quantity"]) * price, float(h["quantity"]) * float(h["average_cost"])
        hist = price_history(asset.symbol, "2y")
        rows.append({"symbol": asset.symbol, "name": asset.name, "quantity": h["quantity"], "average_cost": h["average_cost"], "price": price,
                     "currency": currency, "price_status": q["status"], "price_source": q["provider"], "value": round(value, 2),
                     "pnl": round(value - cost, 2), "pnl_pct": round((value / cost - 1) * 100, 2) if cost else None,
                     "history": statistics(hist) if hist else None})
        t = totals.setdefault(currency, {"value": 0.0, "cost": 0.0})
        t["value"] += value
        t["cost"] += cost
    for r in rows:
        r["weight_in_currency_pct"] = round(float(r["value"]) / totals[str(r["currency"])]["value"] * 100, 2) if totals[str(r["currency"])]["value"] else None
    flags = [f"{r['symbol']} is {r['weight_in_currency_pct']}% of your {r['currency']} holdings" for r in rows if (r["weight_in_currency_pct"] or 0) > 35 and len(rows) > 1]
    return {"holdings": rows,
            "totals_by_currency": {c: {"value": round(t["value"], 2), "cost": round(t["cost"], 2), "pnl": round(t["value"] - t["cost"], 2),
                                       "return_pct": round((t["value"] / t["cost"] - 1) * 100, 2) if t["cost"] else None} for c, t in totals.items()},
            "concentration_flags": flags,
            "notes": ["Totals are shown per currency; no exchange-rate conversion is applied.", "Each price shows whether it is LIVE or a DEMO fallback."]}


# ---------- Journal ----------
def _evidence(symbol: str) -> dict[str, object]:
    asset = _asset_or_error(symbol)
    s = score_asset(asset, quote_dict(quote_for_asset(asset)))
    return {"captured_at": int(time.time()), "price": s["price"], "currency": s["currency"], "price_status": s["price_status"], "score": s["score"],
            "breakdown": s["breakdown"], "fundamentals_source": s["fundamental_inputs"]["source"], "market_inputs": {k: v for k, v in s["market_inputs"].items() if k != "history"}}


def _journal_row(row: dict[str, object]) -> dict[str, object]:
    return {**row, "evidence": json.loads(str(row["evidence"]))}


def list_journal(user_id: int) -> list[dict[str, object]]:
    return [_journal_row(r) for r in db.fetch_all("SELECT * FROM journal_entries WHERE user_id=? ORDER BY created_at DESC, id DESC", (user_id,))]


def add_journal(user_id: int, symbol: str, decision: str, thesis: str, review_on: str | None) -> dict[str, object]:
    asset = _asset_or_error(symbol)
    decision = decision.strip().upper()
    if decision not in JOURNAL_DECISIONS:
        raise UserDataError(f"Decision must be one of {sorted(JOURNAL_DECISIONS)}.")
    thesis = thesis.strip()
    if not 10 <= len(thesis) <= 4000:
        raise UserDataError("Write a thesis of 10 to 4000 characters.")
    if review_on:
        try:
            date.fromisoformat(review_on)
        except ValueError as exc:
            raise UserDataError("Review date must be YYYY-MM-DD.") from exc
    evidence = json.dumps(_evidence(asset.symbol))
    entry_id = db.insert("INSERT INTO journal_entries(user_id,symbol,decision,thesis,evidence,review_on,outcome,created_at) VALUES(?,?,?,?,?,?,?,?)",
                         (user_id, asset.symbol, decision, thesis, evidence, review_on, "OPEN", int(time.time())))
    row = db.fetch_one("SELECT * FROM journal_entries WHERE id=? AND user_id=?", (entry_id, user_id))
    assert row is not None
    return _journal_row(row)


def set_outcome(user_id: int, entry_id: int, outcome: str) -> dict[str, object]:
    outcome = outcome.strip().upper()
    if outcome not in JOURNAL_OUTCOMES:
        raise UserDataError(f"Outcome must be one of {sorted(JOURNAL_OUTCOMES)}.")
    if not db.fetch_one("SELECT id FROM journal_entries WHERE id=? AND user_id=?", (entry_id, user_id)):
        raise UserDataError("Journal entry not found.")
    db.execute("UPDATE journal_entries SET outcome=? WHERE id=? AND user_id=?", (outcome, entry_id, user_id))
    row = db.fetch_one("SELECT * FROM journal_entries WHERE id=? AND user_id=?", (entry_id, user_id))
    assert row is not None
    return _journal_row(row)


# ---------- Paper trading ----------
def _paper_state(user_id: int) -> tuple[float, dict[str, dict[str, float]], list[dict[str, object]]]:
    """Rebuild cash and positions from the order log (the log is the source of truth)."""
    orders = db.fetch_all("SELECT * FROM paper_orders WHERE user_id=? ORDER BY id", (user_id,))
    cash, pos = db.PAPER_STARTING_CASH, {}
    for o in orders:
        qty, px = float(o["quantity"]), float(o["fill_price"])
        p = pos.setdefault(str(o["symbol"]), {"quantity": 0.0, "cost": 0.0})
        if o["side"] == "BUY":
            cash -= qty * px
            p["quantity"] += qty
            p["cost"] += qty * px
        else:
            avg = p["cost"] / p["quantity"] if p["quantity"] else 0.0
            cash += qty * px
            p["quantity"] -= qty
            p["cost"] -= avg * qty
            if p["quantity"] <= 1e-9:
                pos.pop(str(o["symbol"]))
    return cash, pos, orders


def paper_account(user_id: int) -> dict[str, object]:
    cash, pos, orders = _paper_state(user_id)
    positions = []
    for symbol, p in pos.items():
        q = quote_dict(quote_for_asset(_asset_or_error(symbol)))
        positions.append({"symbol": symbol, "quantity": round(p["quantity"], 6), "average_cost": round(p["cost"] / p["quantity"], 4), "price": q["price"],
                          "price_status": q["status"], "currency": q["currency"], "value": round(p["quantity"] * float(q["price"]), 2),
                          "pnl": round(p["quantity"] * float(q["price"]) - p["cost"], 2)})
    return {"mode": "PAPER", "starting_cash": db.PAPER_STARTING_CASH, "cash": round(cash, 2), "positions": positions,
            "orders": list(reversed(orders))[:100],
            "notes": ["Simulated account. No real money and no real orders.", "Cash is a single simulated balance; positions in other currencies are not FX-converted."]}


def paper_order(user_id: int, symbol: str, side: str, quantity: float) -> dict[str, object]:
    asset = _asset_or_error(symbol)
    side = side.strip().upper()
    if side not in {"BUY", "SELL"}:
        raise UserDataError("Side must be BUY or SELL.")
    if quantity <= 0:
        raise UserDataError("Quantity must be positive.")
    q = quote_dict(quote_for_asset(asset))
    price = float(q["price"])
    cash, pos, _ = _paper_state(user_id)
    if side == "BUY" and quantity * price > cash + 1e-9:
        raise UserDataError(f"Insufficient simulated cash: order needs {quantity * price:,.2f}, available {cash:,.2f}.")
    if side == "SELL" and quantity > pos.get(asset.symbol, {}).get("quantity", 0.0) + 1e-9:
        raise UserDataError("You cannot sell more than your simulated position.")
    order_id = db.insert("INSERT INTO paper_orders(user_id,symbol,side,quantity,fill_price,price_status,created_at) VALUES(?,?,?,?,?,?,?)",
                         (user_id, asset.symbol, side, quantity, price, str(q["status"]), int(time.time())))
    return {"id": order_id, "symbol": asset.symbol, "side": side, "quantity": quantity, "fill_price": price, "price_status": q["status"], "status": "FILLED_SIMULATED"}
