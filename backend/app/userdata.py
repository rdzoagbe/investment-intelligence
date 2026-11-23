"""Per-user portfolio holdings, decision journal and simulated (paper) trading.

All records are scoped by user_id. Paper orders always fill at the server's current
quote, never at a client-supplied price, and every fill records whether that quote
was LIVE or DEMO.

Writes that check state before inserting (paper orders, journal caps, alert claims) run
inside user_transaction(): a per-user process lock plus a database-level lock
(pg_advisory_xact_lock on PostgreSQL, BEGIN IMMEDIATE on SQLite), so concurrent requests
cannot overdraw simulated cash or create duplicates.
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import date
from typing import Any, Iterator

from . import db
from .data import get_asset
from .engine import score_asset
from .history import price_history, statistics
from .market_data import fx_rate, quote_dict, quote_for_asset

JOURNAL_DECISIONS = {"RESEARCH", "WATCH", "BUY", "ADD", "TRIM", "SELL", "PASS"}
JOURNAL_OUTCOMES = {"OPEN", "THESIS_CONFIRMED", "THESIS_BROKEN", "MIXED", "CLOSED"}
# Per-user storage caps (keep one account from filling the shared database) and list paging.
MAX_JOURNAL_ENTRIES = 2000
MAX_PAPER_ORDERS = 5000
DEFAULT_PAGE = 200
MAX_PAGE = 1000
REPORTING_CURRENCY = "USD"
# Namespace for per-user PostgreSQL advisory locks (high 32 bits of the bigint key).
_USER_LOCK_NAMESPACE = 0x1A7E


class UserDataError(ValueError):
    pass


def _asset_or_error(symbol: str):
    asset = get_asset(symbol)
    if asset is None:
        raise UserDataError(f"{symbol.upper()} is not in the research universe.")
    return asset


def _page(limit: int | None, offset: int | None) -> tuple[int, int]:
    lim = DEFAULT_PAGE if limit is None else int(limit)
    return max(1, min(lim, MAX_PAGE)), max(0, int(offset or 0))


_user_locks: dict[int, threading.Lock] = {}
_user_locks_guard = threading.Lock()


def _user_lock(user_id: int) -> threading.Lock:
    with _user_locks_guard:
        return _user_locks.setdefault(int(user_id), threading.Lock())


@contextmanager
def user_transaction(user_id: int) -> Iterator[Any]:
    """One serialised transaction per user: process lock + DB lock, committed on exit."""
    with _user_lock(user_id):
        with db.connection() as conn:
            if db.is_postgres():
                conn.execute("SELECT pg_advisory_xact_lock(%s::bigint)", ((_USER_LOCK_NAMESPACE << 32) | (int(user_id) & 0xFFFFFFFF),))
            else:
                if conn.in_transaction:
                    conn.commit()
                conn.execute("BEGIN IMMEDIATE")
            yield conn


def tx_fetch_all(conn: Any, query: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(db._sql(query), params).fetchall()]  # noqa: SLF001 - shared placeholder translation


def tx_execute(conn: Any, query: str, params: tuple = ()) -> int:
    """Run a statement on an open connection and return the affected row count."""
    return int(conn.execute(db._sql(query), params).rowcount or 0)  # noqa: SLF001


def tx_insert(conn: Any, query: str, params: tuple = ()) -> int:
    if db.is_postgres():
        return int(conn.execute(db._sql(query) + " RETURNING id", params).fetchone()["id"])  # noqa: SLF001
    return int(conn.execute(query, params).lastrowid)


# ---------- Holdings ----------
def list_holdings(user_id: int) -> list[dict[str, object]]:
    return db.fetch_all("SELECT id,symbol,quantity,average_cost,created_at FROM holdings WHERE user_id=? ORDER BY symbol", (user_id,))


def upsert_holding(user_id: int, symbol: str, quantity: float, average_cost: float) -> dict[str, object]:
    asset = _asset_or_error(symbol)
    if quantity <= 0 or average_cost <= 0:
        raise UserDataError("Quantity and average cost must be positive.")
    # Single atomic upsert (SQLite >= 3.24 and PostgreSQL): a double-submitted form cannot race
    # the UNIQUE(user_id, symbol) constraint.
    db.execute("INSERT INTO holdings(user_id,symbol,quantity,average_cost,created_at) VALUES(?,?,?,?,?) "
               "ON CONFLICT(user_id, symbol) DO UPDATE SET quantity=excluded.quantity, average_cost=excluded.average_cost",
               (user_id, asset.symbol, quantity, average_cost, int(time.time())))
    return {"symbol": asset.symbol, "quantity": quantity, "average_cost": average_cost}


def delete_holding(user_id: int, symbol: str) -> None:
    db.execute("DELETE FROM holdings WHERE user_id=? AND symbol=?", (user_id, symbol.strip().upper()))


def _converted(totals: dict[str, dict[str, float]], demo_count: int) -> dict[str, object] | None:
    """Convert per-currency totals to USD at current provider FX rates; None if any rate is missing."""
    if not totals:
        return None
    rates: dict[str, dict[str, object]] = {}
    value = cost = 0.0
    for currency, t in totals.items():
        fx = fx_rate(currency, REPORTING_CURRENCY)
        rate = fx.get("rate")
        if not isinstance(rate, (int, float)) or rate <= 0:
            return None  # never assume 1:1
        rates[currency] = {"rate": rate, "status": fx.get("status"), "source": fx.get("source")}
        value += t["value"] * float(rate)
        cost += t["cost"] * float(rate)
    note = (f"Converted to {REPORTING_CURRENCY} at current exchange rates. Cost is converted at today's rate, not the rate when you bought, "
            "so profit and loss here includes currency moves only approximately.")
    if demo_count:
        note += f" {demo_count} holding(s) are valued at DEMO fallback prices, so this total is not a live valuation."
    return {"currency": REPORTING_CURRENCY, "value": round(value, 2), "cost": round(cost, 2), "pnl": round(value - cost, 2),
            "return_pct": round((value / cost - 1) * 100, 2) if cost else None, "rates": rates, "complete": demo_count == 0, "note": note}


def portfolio(user_id: int) -> dict[str, object]:
    """Value holdings at current quotes. Totals are per currency, plus a USD conversion when every
    needed FX rate is available from the provider (otherwise "converted" is null)."""
    rows = []
    totals: dict[str, dict[str, float]] = {}
    demo_by_currency: dict[str, int] = {}
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
        demo_by_currency[currency] = demo_by_currency.get(currency, 0) + (0 if q["status"] == "LIVE" else 1)
    for r in rows:
        r["weight_in_currency_pct"] = round(float(r["value"]) / totals[str(r["currency"])]["value"] * 100, 2) if totals[str(r["currency"])]["value"] else None
    flags = [f"{r['symbol']} is {r['weight_in_currency_pct']}% of your {r['currency']} holdings" for r in rows if (r["weight_in_currency_pct"] or 0) > 35 and len(rows) > 1]
    demo_total = sum(demo_by_currency.values())
    converted = _converted(totals, demo_total)
    notes = ["Totals are shown per currency in each asset's trading currency.",
             "Each price shows whether it is LIVE or a DEMO fallback."]
    notes.append("A USD total is shown using current provider exchange rates." if converted else
                 "No USD total: at least one exchange rate is unavailable, and no rate is assumed." if totals else "No holdings yet.")
    if demo_total:
        notes.append(f"{demo_total} holding(s) are valued at DEMO fallback prices; totals that include them are not live valuations.")
    return {"holdings": rows,
            "totals_by_currency": {c: {"value": round(t["value"], 2), "cost": round(t["cost"], 2), "pnl": round(t["value"] - t["cost"], 2),
                                       "return_pct": round((t["value"] / t["cost"] - 1) * 100, 2) if t["cost"] else None,
                                       "demo_priced_holdings": demo_by_currency.get(c, 0)} for c, t in totals.items()},
            "converted": converted,
            "concentration_flags": flags,
            "notes": notes}


# ---------- Journal ----------
def _evidence(symbol: str) -> dict[str, object]:
    asset = _asset_or_error(symbol)
    s = score_asset(asset, quote_dict(quote_for_asset(asset)))
    return {"captured_at": int(time.time()), "price": s["price"], "currency": s["currency"], "price_status": s["price_status"], "score": s["score"],
            "breakdown": s["breakdown"], "fundamentals_source": s["fundamental_inputs"]["source"], "market_inputs": {k: v for k, v in s["market_inputs"].items() if k != "history"}}


def _journal_row(row: dict[str, object]) -> dict[str, object]:
    return {**row, "evidence": json.loads(str(row["evidence"]))}


def list_journal(user_id: int, limit: int | None = None, offset: int | None = None) -> list[dict[str, object]]:
    """Newest first, paginated (default 200, max 1000 per page)."""
    lim, off = _page(limit, offset)
    return [_journal_row(r) for r in db.fetch_all("SELECT * FROM journal_entries WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                                                  (user_id, lim, off))]


def journal_outcome_counts(user_id: int) -> dict[str, int]:
    return {str(r["outcome"]): int(r["n"]) for r in db.fetch_all("SELECT outcome, COUNT(*) AS n FROM journal_entries WHERE user_id=? GROUP BY outcome", (user_id,))}


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
    with user_transaction(user_id) as conn:
        count = int(tx_fetch_all(conn, "SELECT COUNT(*) AS n FROM journal_entries WHERE user_id=?", (user_id,))[0]["n"])
        if count >= MAX_JOURNAL_ENTRIES:
            raise UserDataError(f"You can keep up to {MAX_JOURNAL_ENTRIES} journal entries. Export your data and delete old entries first.")
        entry_id = tx_insert(conn, "INSERT INTO journal_entries(user_id,symbol,decision,thesis,evidence,review_on,outcome,created_at) VALUES(?,?,?,?,?,?,?,?)",
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
def _paper_state(user_id: int, conn: Any | None = None) -> tuple[float, dict[str, dict[str, float]], list[dict[str, object]]]:
    """Rebuild cash and positions from the order log (the log is the source of truth).

    The log is bounded by MAX_PAPER_ORDERS per user, so the replay stays cheap."""
    query, params = "SELECT * FROM paper_orders WHERE user_id=? ORDER BY id", (user_id,)
    orders = tx_fetch_all(conn, query, params) if conn is not None else db.fetch_all(query, params)
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


def paper_account(user_id: int, order_limit: int | None = None, order_offset: int | None = None) -> dict[str, object]:
    cash, pos, orders = _paper_state(user_id)
    lim, off = _page(order_limit, order_offset)
    positions = []
    for symbol, p in pos.items():
        q = quote_dict(quote_for_asset(_asset_or_error(symbol)))
        positions.append({"symbol": symbol, "quantity": round(p["quantity"], 6), "average_cost": round(p["cost"] / p["quantity"], 4), "price": q["price"],
                          "price_status": q["status"], "currency": q["currency"], "value": round(p["quantity"] * float(q["price"]), 2),
                          "pnl": round(p["quantity"] * float(q["price"]) - p["cost"], 2)})
    demo_priced = sum(1 for p in positions if p["price_status"] != "LIVE")
    notes = ["Simulated account. No real money and no real orders.", "Cash is a single simulated balance; positions in other currencies are not FX-converted."]
    if demo_priced:
        notes.append(f"{demo_priced} position(s) are valued at DEMO fallback prices, so equity, value and P&L for them are not live.")
    return {"mode": "PAPER", "starting_cash": db.PAPER_STARTING_CASH, "cash": round(cash, 2), "positions": positions,
            "demo_priced_positions": demo_priced, "order_count": len(orders),
            "orders": list(reversed(orders))[off:off + lim],
            "notes": notes}


def paper_order(user_id: int, symbol: str, side: str, quantity: float) -> dict[str, object]:
    asset = _asset_or_error(symbol)
    side = side.strip().upper()
    if side not in {"BUY", "SELL"}:
        raise UserDataError("Side must be BUY or SELL.")
    if quantity <= 0:
        raise UserDataError("Quantity must be positive.")
    q = quote_dict(quote_for_asset(asset))  # network call happens before any lock is taken
    price = float(q["price"])
    with user_transaction(user_id) as conn:  # state check and insert are one serialised transaction
        cash, pos, orders = _paper_state(user_id, conn)
        if len(orders) >= MAX_PAPER_ORDERS:
            raise UserDataError(f"This simulated account has reached {MAX_PAPER_ORDERS} orders.")
        if side == "BUY" and quantity * price > cash + 1e-9:
            raise UserDataError(f"Insufficient simulated cash: order needs {quantity * price:,.2f}, available {cash:,.2f}.")
        if side == "SELL" and quantity > pos.get(asset.symbol, {}).get("quantity", 0.0) + 1e-9:
            raise UserDataError("You cannot sell more than your simulated position.")
        order_id = tx_insert(conn, "INSERT INTO paper_orders(user_id,symbol,side,quantity,fill_price,price_status,created_at) VALUES(?,?,?,?,?,?,?)",
                             (user_id, asset.symbol, side, quantity, price, str(q["status"]), int(time.time())))
    return {"id": order_id, "symbol": asset.symbol, "side": side, "quantity": quantity, "fill_price": price, "price_status": q["status"], "status": "FILLED_SIMULATED"}


# ---------- Data rights: export and delete ----------
_USER_TABLES = ("holdings", "journal_entries", "paper_orders", "alert_rules", "alert_events", "assistant_queries")


def export_user_data(user_id: int) -> dict[str, object]:
    """Everything stored for this user, as JSON-serialisable lists (no pagination)."""
    journal = [_journal_row(r) for r in db.fetch_all("SELECT * FROM journal_entries WHERE user_id=? ORDER BY id", (user_id,))]
    return {"holdings": db.fetch_all("SELECT * FROM holdings WHERE user_id=? ORDER BY id", (user_id,)),
            "journal": journal,
            "paper_orders": db.fetch_all("SELECT * FROM paper_orders WHERE user_id=? ORDER BY id", (user_id,)),
            "alert_rules": db.fetch_all("SELECT * FROM alert_rules WHERE user_id=? ORDER BY id", (user_id,)),
            "alert_events": db.fetch_all("SELECT * FROM alert_events WHERE user_id=? ORDER BY id", (user_id,)),
            "assistant_history": db.fetch_all("SELECT * FROM assistant_queries WHERE user_id=? ORDER BY id", (user_id,))}


def delete_user_data(user_id: int) -> None:
    """Delete every per-user row in one transaction (the users row is deleted by the caller)."""
    with user_transaction(user_id) as conn:
        for table in _USER_TABLES:
            tx_execute(conn, f"DELETE FROM {table} WHERE user_id=?", (user_id,))  # noqa: S608 - fixed table names
