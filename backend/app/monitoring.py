"""Alerts, daily score snapshots and track records.

Price-based alerts only fire on LIVE quotes: a DEMO fallback price never triggers an
alert. Snapshots record each day's scores and prices so the platform can later measure
whether higher scores were followed by better returns, instead of assuming they were.
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime, timezone

from . import db, userdata
from .data import ASSETS, get_asset
from .engine import band_label, scanner, score_asset
from .market_data import quote_dict, quote_for_asset

ALERT_KINDS = {
    "PRICE_ABOVE": "price rises above",
    "PRICE_BELOW": "price falls below",
    "SCORE_ABOVE": "model score rises above",
    "SCORE_BELOW": "model score falls below",
    "DAILY_MOVE": "daily move (up or down) of at least this many %",
}
COOLDOWN_SECONDS = 20 * 3600
MIN_FORWARD_DAYS = 5


class MonitoringError(ValueError):
    pass


# ---------- Alert rules ----------
def list_rules(user_id: int) -> list[dict[str, object]]:
    return db.fetch_all("SELECT * FROM alert_rules WHERE user_id=? ORDER BY id DESC", (user_id,))


def add_rule(user_id: int, symbol: str, kind: str, threshold: float) -> dict[str, object]:
    asset = get_asset(symbol)
    if asset is None:
        raise MonitoringError(f"{symbol.upper()} is not in the research universe.")
    kind = kind.strip().upper()
    if kind not in ALERT_KINDS:
        raise MonitoringError(f"Alert type must be one of {sorted(ALERT_KINDS)}.")
    if threshold <= 0 or (kind.startswith("SCORE") and threshold > 100):
        raise MonitoringError("Threshold must be positive (scores between 0 and 100).")
    if len(list_rules(user_id)) >= 50:
        raise MonitoringError("You can keep up to 50 alert rules.")
    rule_id = db.insert("INSERT INTO alert_rules(user_id,symbol,kind,threshold,active,last_triggered_at,created_at) VALUES(?,?,?,?,?,?,?)",
                        (user_id, asset.symbol, kind, threshold, 1, None, int(time.time())))
    return {"id": rule_id, "symbol": asset.symbol, "kind": kind, "threshold": threshold}


def delete_rule(user_id: int, rule_id: int) -> None:
    db.execute("DELETE FROM alert_rules WHERE id=? AND user_id=?", (rule_id, user_id))


def _message(kind: str, symbol: str, threshold: float, price: float, currency: str, score: float, move: float | None) -> str | None:
    if kind == "PRICE_ABOVE" and price > threshold:
        return f"{symbol} is at {price:,.2f} {currency}, above your {threshold:,.2f} alert."
    if kind == "PRICE_BELOW" and price < threshold:
        return f"{symbol} is at {price:,.2f} {currency}, below your {threshold:,.2f} alert."
    if kind == "SCORE_ABOVE" and score > threshold:
        return f"{symbol} model score is {score}, above your {threshold:g} alert."
    if kind == "SCORE_BELOW" and score < threshold:
        return f"{symbol} model score is {score}, below your {threshold:g} alert."
    if kind == "DAILY_MOVE" and move is not None and abs(move) >= threshold:
        return f"{symbol} moved {move:+.2f}% today (alert at ±{threshold:g}%)."
    return None


def evaluate_user(user_id: int) -> int:
    """Check this user's rules and due journal reviews; record new events. Returns events created."""
    now = int(time.time())
    created = 0
    cache: dict[str, dict[str, object]] = {}
    for rule in db.fetch_all("SELECT * FROM alert_rules WHERE user_id=? AND active=1", (user_id,)):
        if rule["last_triggered_at"] and now - int(rule["last_triggered_at"]) < COOLDOWN_SECONDS:
            continue
        symbol = str(rule["symbol"])
        asset = get_asset(symbol)
        if asset is None:
            continue
        if symbol not in cache:
            cache[symbol] = score_asset(asset, quote_dict(quote_for_asset(asset)))
        s = cache[symbol]
        kind = str(rule["kind"])
        if kind != "SCORE_ABOVE" and kind != "SCORE_BELOW" and s["price_status"] != "LIVE":
            continue  # never alert on a demo/fallback price
        msg = _message(kind, symbol, float(rule["threshold"]), float(s["price"]), str(s["currency"]), float(s["score"]), s["change_pct"] if isinstance(s["change_pct"], (int, float)) else None)
        if msg:
            db.insert("INSERT INTO alert_events(user_id,rule_id,symbol,message,is_read,created_at) VALUES(?,?,?,?,?,?)", (user_id, rule["id"], symbol, msg, 0, now))
            db.execute("UPDATE alert_rules SET last_triggered_at=? WHERE id=?", (now, rule["id"]))
            created += 1
    today = date.today().isoformat()
    for entry in userdata.list_journal(user_id):
        if entry["outcome"] == "OPEN" and entry["review_on"] and str(entry["review_on"]) <= today:
            marker = f"Journal review due: {entry['decision']} {entry['symbol']} (entry #{entry['id']})"
            if not db.fetch_one("SELECT id FROM alert_events WHERE user_id=? AND message LIKE ?", (user_id, marker + "%")):
                db.insert("INSERT INTO alert_events(user_id,rule_id,symbol,message,is_read,created_at) VALUES(?,?,?,?,?,?)",
                          (user_id, None, entry["symbol"], f"{marker}. Was the thesis right?", 0, now))
                created += 1
    return created


def events(user_id: int, limit: int = 50) -> list[dict[str, object]]:
    return db.fetch_all("SELECT * FROM alert_events WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))


def mark_read(user_id: int) -> None:
    db.execute("UPDATE alert_events SET is_read=1 WHERE user_id=?", (user_id,))


# ---------- Daily job ----------
def take_snapshot(snapshot_date: str | None = None) -> int:
    """Store today's score and price for every asset (idempotent per date)."""
    day = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    stored = 0
    for item in scanner(len(ASSETS)):
        if db.fetch_one("SELECT id FROM scan_snapshots WHERE snapshot_date=? AND symbol=?", (day, item["symbol"])):
            continue
        db.insert("INSERT INTO scan_snapshots(snapshot_date,symbol,score,price,price_status,currency,created_at) VALUES(?,?,?,?,?,?,?)",
                  (day, item["symbol"], item["score"], item["price"], item["price_status"], item["currency"], int(time.time())))
        stored += 1
    return stored


def run_daily_job() -> dict[str, object]:
    stored = take_snapshot()
    users = db.fetch_all("SELECT DISTINCT user_id FROM alert_rules WHERE active=1 UNION SELECT DISTINCT user_id FROM journal_entries")
    created = sum(evaluate_user(int(u["user_id"])) for u in users)
    return {"snapshots_stored": stored, "users_checked": len(users), "alerts_created": created, "ran_at": int(time.time())}


# ---------- Track records ----------
def signal_track_record() -> dict[str, object]:
    """Average forward return by score band, from stored LIVE snapshots to the latest LIVE snapshot."""
    rows = db.fetch_all("SELECT snapshot_date,symbol,score,price,price_status FROM scan_snapshots WHERE price_status='LIVE' ORDER BY snapshot_date")
    latest: dict[str, dict[str, object]] = {}
    for r in rows:
        latest[str(r["symbol"])] = r
    buckets: dict[str, list[float]] = defaultdict(list)
    dates = sorted({str(r["snapshot_date"]) for r in rows})
    for r in rows:
        end = latest[str(r["symbol"])]
        days = (date.fromisoformat(str(end["snapshot_date"])) - date.fromisoformat(str(r["snapshot_date"]))).days
        if days >= MIN_FORWARD_DAYS:
            buckets[band_label(float(r["score"]))].append((float(end["price"]) / float(r["price"]) - 1) * 100)
    observations = sum(len(v) for v in buckets.values())
    summary = [{"band": b, "observations": len(v), "average_forward_return_pct": round(sum(v) / len(v), 2), "share_positive_pct": round(sum(1 for x in v if x > 0) / len(v) * 100, 1)}
               for b, v in sorted(buckets.items(), key=lambda kv: ["High score", "Watch", "Neutral", "Low score"].index(kv[0]))]
    enough = observations >= 30 and len(dates) >= 4
    return {"snapshot_days": len(dates), "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None,
            "observations": observations, "bands": summary, "sufficient": enough,
            "notes": [f"Only LIVE prices count. A pair needs at least {MIN_FORWARD_DAYS} days between snapshot and latest price.",
                      "Returns are in each asset's own currency, ignore dividends, and overlap in time, so they are not independent.",
                      "Treat results as descriptive until there are many months of data; small samples are mostly noise."]
            + ([] if enough else ["Not enough data yet: snapshots accumulate once per day when the daily job runs."])}


def user_track_record(user_id: int) -> dict[str, object]:
    orders = db.fetch_all("SELECT * FROM paper_orders WHERE user_id=? ORDER BY id", (user_id,))
    pos: dict[str, dict[str, float]] = {}
    closed: list[float] = []
    realized = 0.0
    for o in orders:
        q, px = float(o["quantity"]), float(o["fill_price"])
        p = pos.setdefault(str(o["symbol"]), {"qty": 0.0, "cost": 0.0})
        if o["side"] == "BUY":
            p["qty"] += q
            p["cost"] += q * px
        else:
            avg = p["cost"] / p["qty"] if p["qty"] else 0.0
            gain = (px - avg) * q
            realized += gain
            closed.append(gain)
            p["qty"] -= q
            p["cost"] -= avg * q
    account = userdata.paper_account(user_id)
    unrealized = sum(float(p["pnl"]) for p in account["positions"])  # type: ignore[index]
    equity = float(account["cash"]) + sum(float(p["value"]) for p in account["positions"])  # type: ignore[index]
    journal = userdata.list_journal(user_id)
    outcomes: dict[str, int] = defaultdict(int)
    for e in journal:
        outcomes[str(e["outcome"])] += 1
    judged = outcomes["THESIS_CONFIRMED"] + outcomes["THESIS_BROKEN"]
    demo_fills = sum(1 for o in orders if o["price_status"] != "LIVE")
    return {
        "paper": {"orders": len(orders), "equity": round(equity, 2), "return_pct": round((equity / db.PAPER_STARTING_CASH - 1) * 100, 2),
                  "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2), "closed_trades": len(closed),
                  "winning_trades": sum(1 for g in closed if g > 0), "win_rate_pct": round(sum(1 for g in closed if g > 0) / len(closed) * 100, 1) if closed else None,
                  "fills_on_demo_prices": demo_fills},
        "journal": {"entries": len(journal), "by_outcome": dict(outcomes), "judged": judged,
                    "thesis_hit_rate_pct": round(outcomes["THESIS_CONFIRMED"] / judged * 100, 1) if judged else None},
        "notes": ["Paper results are simulated and mix currencies without FX conversion.",
                  "Hit rate counts only entries you marked confirmed or broken."]
                 + ([f"{demo_fills} simulated fills used DEMO prices and are not meaningful as performance."] if demo_fills else []),
    }
