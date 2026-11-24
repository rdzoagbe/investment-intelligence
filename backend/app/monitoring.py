"""Alerts, daily score snapshots and track records.

Price-based alerts only fire on LIVE quotes: a DEMO fallback price never triggers an
alert. Score alerts may fire on demo/seed inputs but say so in the message. Snapshots
record each day's scores and prices so the platform can later measure whether higher
scores were followed by better returns, instead of assuming they were.
"""
from __future__ import annotations

import bisect
import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from . import db, tiingo, userdata
from .data import ASSETS, get_asset
from .engine import band_label, scanner, score_asset
from .history import price_history
from .market_data import quote_dict, quote_for_asset

log = logging.getLogger(__name__)

ALERT_KINDS = {
    "PRICE_ABOVE": "price rises above",
    "PRICE_BELOW": "price falls below",
    "SCORE_ABOVE": "model score rises above",
    "SCORE_BELOW": "model score falls below",
    "DAILY_MOVE": "daily move (up or down) of at least this many %",
}
COOLDOWN_SECONDS = 20 * 3600
MIN_FORWARD_DAYS = 5
# Fallback guard when no adjusted history is available: a snapshot-to-latest price ratio
# outside this band most likely reflects a stock split (or reverse split), not a return.
SPLIT_SUSPECT_LOW, SPLIT_SUSPECT_HIGH = 0.4, 2.5
# Common split factors: a raw price ratio within 3% of one of these (or its inverse) is treated
# as a likely split when no provider split data covers the window.
_SPLIT_FACTORS = (2.0, 3.0, 1.5, 4.0, 5.0, 10.0, 20.0)


def _looks_like_split(ratio: float) -> bool:
    if not SPLIT_SUSPECT_LOW <= ratio <= SPLIT_SUSPECT_HIGH:
        return True
    return any(abs(ratio * f - 1) <= 0.03 or abs(ratio / f - 1) <= 0.03 for f in _SPLIT_FACTORS)
# The automatic daily snapshot runs after the US close (16:00 ET is 20:00/21:00 UTC).
SNAPSHOT_AFTER_UTC = (21, 30)


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
    with userdata.user_transaction(user_id) as conn:
        rule_id = userdata.tx_insert(conn, "INSERT INTO alert_rules(user_id,symbol,kind,threshold,active,last_triggered_at,created_at) VALUES(?,?,?,?,?,?,?)",
                                     (user_id, asset.symbol, kind, threshold, 1, None, int(time.time())))
    return {"id": rule_id, "symbol": asset.symbol, "kind": kind, "threshold": threshold}


def delete_rule(user_id: int, rule_id: int) -> None:
    db.execute("DELETE FROM alert_rules WHERE id=? AND user_id=?", (rule_id, user_id))


def _score_data_note(s: dict[str, object]) -> str:
    """Suffix for score alerts that explains when the score rests on demo/seed inputs."""
    fundamentals = s.get("fundamental_inputs") or {}
    f_status = str(fundamentals.get("status", "DEMO")) if isinstance(fundamentals, dict) else "DEMO"
    if s.get("price_status") != "LIVE" or f_status not in {"LIVE", "PARTIAL"}:
        return " Based on demo/seed data, not live data."
    if f_status == "PARTIAL":
        return " Some fundamentals are demo/seed data, not live."
    return ""


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


def _claim_and_record(user_id: int, rule_id: int, symbol: str, msg: str, now: int) -> bool:
    """Atomically claim the rule's cooldown slot, then record the event. False if another request won."""
    with userdata.user_transaction(user_id) as conn:
        claimed = userdata.tx_execute(conn, "UPDATE alert_rules SET last_triggered_at=? WHERE id=? AND user_id=? AND active=1 "
                                            "AND (last_triggered_at IS NULL OR last_triggered_at <= ?)", (now, rule_id, user_id, now - COOLDOWN_SECONDS))
        if claimed != 1:
            return False
        userdata.tx_insert(conn, "INSERT INTO alert_events(user_id,rule_id,symbol,message,is_read,created_at) VALUES(?,?,?,?,?,?)", (user_id, rule_id, symbol, msg, 0, now))
    return True


def evaluate_user(user_id: int) -> int:
    """Check this user's rules and due journal reviews; record new events. Returns events created.

    Safe to call concurrently (page load + badge fetch + daily job): each rule is claimed with a
    conditional UPDATE and journal reviews are deduplicated inside a per-user transaction."""
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
        if msg and kind.startswith("SCORE"):
            msg += _score_data_note(s)
        if msg and _claim_and_record(user_id, int(rule["id"]), symbol, msg, now):
            created += 1
    today = date.today().isoformat()
    due = db.fetch_all("SELECT id,symbol,decision FROM journal_entries WHERE user_id=? AND outcome='OPEN' AND review_on IS NOT NULL AND review_on <> '' AND review_on <= ? ORDER BY id",
                       (user_id, today))
    for entry in due:
        marker = f"Journal review due: {entry['decision']} {entry['symbol']} (entry #{entry['id']})"
        with userdata.user_transaction(user_id) as conn:
            if userdata.tx_fetch_all(conn, "SELECT id FROM alert_events WHERE user_id=? AND rule_id IS NULL AND message LIKE ?", (user_id, marker + "%")):
                continue
            userdata.tx_insert(conn, "INSERT INTO alert_events(user_id,rule_id,symbol,message,is_read,created_at) VALUES(?,?,?,?,?,?)",
                               (user_id, None, entry["symbol"], f"{marker}. Was the thesis right?", 0, now))
        created += 1
    return created


def events(user_id: int, limit: int = 50) -> list[dict[str, object]]:
    return db.fetch_all("SELECT * FROM alert_events WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))


def mark_read(user_id: int) -> None:
    db.execute("UPDATE alert_events SET is_read=1 WHERE user_id=?", (user_id,))


# ---------- Daily job ----------
def take_snapshot(snapshot_date: str | None = None) -> int:
    """Store today's score and price for every asset (idempotent per date, safe when runs overlap)."""
    day = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    items = scanner(len(ASSETS))
    stored = 0
    now = int(time.time())
    with db.connection() as conn:
        for item in items:
            # ON CONFLICT DO NOTHING works on SQLite >= 3.24 and PostgreSQL.
            stored += userdata.tx_execute(conn, "INSERT INTO scan_snapshots(snapshot_date,symbol,score,price,price_status,currency,created_at) VALUES(?,?,?,?,?,?,?) "
                                                "ON CONFLICT(snapshot_date, symbol) DO NOTHING",
                                          (day, item["symbol"], item["score"], item["price"], item["price_status"], item["currency"], now))
    return stored


_snapshot_lock = threading.Lock()
_snapshot_done: set[str] = set()


def maybe_run_daily_snapshot(now_utc: datetime | None = None) -> dict[str, object] | None:
    """Opportunistic daily snapshot (called fire-and-forget from the dashboard).

    Runs at most once per UTC date, only on weekdays after 21:30 UTC, and only when no
    snapshot exists yet for that date. Concurrent callers are serialised by a process lock
    (losers return None) and the insert itself is idempotent. Never raises.
    """
    try:
        now = now_utc or datetime.now(timezone.utc)
        now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
        if now.weekday() >= 5 or (now.hour, now.minute) < SNAPSHOT_AFTER_UTC:
            return None
        day = now.date().isoformat()
        key = f"{db.engine()}:{db.database_url() or db._sqlite_path()}:{day}"  # noqa: SLF001 - per-database memo
        if key in _snapshot_done or not _snapshot_lock.acquire(blocking=False):
            return None
        try:
            if key in _snapshot_done:
                return None
            if db.fetch_one("SELECT id FROM scan_snapshots WHERE snapshot_date=? LIMIT 1", (day,)):
                _snapshot_done.add(key)
                return None
            stored = take_snapshot(day)
            _snapshot_done.add(key)
            return {"snapshot_date": day, "snapshots_stored": stored, "ran_at": int(time.time())}
        finally:
            _snapshot_lock.release()
    except Exception:  # noqa: BLE001 - background helper must never raise
        log.exception("automatic daily snapshot failed")
        return None


def run_daily_job() -> dict[str, object]:
    stored = take_snapshot()
    users = db.fetch_all("SELECT DISTINCT user_id FROM alert_rules WHERE active=1 UNION SELECT DISTINCT user_id FROM journal_entries")
    owners = tiingo.owner_ids()
    if owners:
        # Private mode: data is licensed for the owners only, so alerts (which quote prices) are
        # not generated for other accounts that existed before the site was made private.
        users = [u for u in users if str(u["user_id"]) in owners]
    created = sum(evaluate_user(int(u["user_id"])) for u in users)
    return {"snapshots_stored": stored, "users_checked": len(users), "alerts_created": created, "ran_at": int(time.time())}


# ---------- Track records ----------
def _close_on_or_before(dates: list[str], closes: list[float], day: str) -> float | None:
    i = bisect.bisect_right(dates, day) - 1
    if i < 0:
        return None
    if (date.fromisoformat(day) - date.fromisoformat(dates[i])).days > 5:
        return None  # history does not really cover that date
    return closes[i]


def _histories(symbols: set[str], first_day: str) -> dict[str, object]:
    """Provider history per symbol (split-adjusted; dividend-adjusted when adjclose exists). Never raises."""
    span = (date.today() - date.fromisoformat(first_day)).days
    range_ = "2y" if span < 700 else "5y" if span < 1800 else "10y"

    def fetch(sym: str) -> object:
        try:
            return price_history(sym, range_)
        except Exception:  # noqa: BLE001 - a provider failure only means "fallback"
            return None
    if not symbols:
        return {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(sorted(symbols), pool.map(fetch, sorted(symbols))))


def signal_track_record() -> dict[str, object]:
    """Average forward return by score band, from stored LIVE snapshots to the latest LIVE snapshot.

    Both ends of a pair must be LIVE. Forward returns use the provider's adjusted daily history
    between the two dates when it covers them (so splits are not counted as losses); otherwise the
    stored snapshot prices are used and pairs whose ratio implies a likely split are excluded.
    """
    rows = db.fetch_all("SELECT snapshot_date,symbol,score,price,price_status,currency FROM scan_snapshots WHERE price_status='LIVE' ORDER BY snapshot_date")
    # Pairs are only formed within one currency: a listing change (e.g. ASML moved from the USD
    # ADR to the EUR home listing) must never be read as a return.
    latest: dict[tuple[str, str], dict[str, object]] = {}
    for r in rows:
        latest[(str(r["symbol"]), str(r.get("currency") or ""))] = r
    pairs = []
    for r in rows:
        end = latest[(str(r["symbol"]), str(r.get("currency") or ""))]
        days = (date.fromisoformat(str(end["snapshot_date"])) - date.fromisoformat(str(r["snapshot_date"]))).days
        if days >= MIN_FORWARD_DAYS and float(r["price"]) > 0 and float(end["price"]) > 0:
            pairs.append((r, end))
    histories = _histories({str(r["symbol"]) for r, _ in pairs}, min(str(r["snapshot_date"]) for r, _ in pairs)) if pairs else {}
    buckets: dict[str, list[float]] = defaultdict(list)
    dates = sorted({str(r["snapshot_date"]) for r in rows})
    from_history = excluded_splits = 0
    for r, end in pairs:
        ratio = None
        hist = histories.get(str(r["symbol"]))
        if hist is not None:
            start_px = _close_on_or_before(hist.dates, hist.closes, str(r["snapshot_date"]))  # type: ignore[attr-defined]
            end_px = _close_on_or_before(hist.dates, hist.closes, str(end["snapshot_date"]))  # type: ignore[attr-defined]
            if start_px and end_px:
                ratio = end_px / start_px
                from_history += 1
        if ratio is None:
            ratio = float(end["price"]) / float(r["price"])
            split_in_window = bool(hist is not None and any(str(r["snapshot_date"]) < d <= str(end["snapshot_date"]) for d, _ in getattr(hist, "splits", ())))
            if split_in_window or _looks_like_split(ratio):
                excluded_splits += 1
                continue
        buckets[band_label(float(r["score"]))].append((ratio - 1) * 100)
    observations = sum(len(v) for v in buckets.values())
    summary = [{"band": b, "observations": len(v), "average_forward_return_pct": round(sum(v) / len(v), 2), "share_positive_pct": round(sum(1 for x in v if x > 0) / len(v) * 100, 1)}
               for b, v in sorted(buckets.items(), key=lambda kv: ["High score", "Watch", "Neutral", "Low score"].index(kv[0]))]
    enough = observations >= 30 and len(dates) >= 4
    return {"snapshot_days": len(dates), "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None,
            "observations": observations, "bands": summary, "sufficient": enough,
            "returns_from_adjusted_history": from_history, "returns_from_snapshot_prices": observations - from_history,
            "excluded_suspected_splits": excluded_splits,
            "notes": [f"Only pairs where both prices are LIVE count. A pair needs at least {MIN_FORWARD_DAYS} days between snapshot and latest price.",
                      "Where provider history is available, returns use split-adjusted (and, where offered, dividend-adjusted) daily closes. "
                      f"Otherwise raw snapshot prices are used, ignore dividends, and pairs that span a reported split, or whose price ratio is "
                      f"below {SPLIT_SUSPECT_LOW}, above {SPLIT_SUSPECT_HIGH} or close to a common split factor (2:1, 3:2, 3:1 ...), are excluded.",
                      "Pairs are only formed within one trading currency.",
                      "Returns are in each asset's own currency and overlap in time, so they are not independent.",
                      "Treat results as descriptive until there are many months of data; small samples are mostly noise."]
            + ([f"{excluded_splits} pair(s) were excluded as likely stock splits."] if excluded_splits else [])
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
    # Positions whose P&L cannot be computed (cost currency differs from today's listing and no
    # rate is available) are reported separately instead of crashing or being counted as zero.
    known = [float(p["pnl"]) for p in account["positions"] if p.get("pnl") is not None]  # type: ignore[union-attr]
    pnl_unavailable = len(account["positions"]) - len(known)  # type: ignore[arg-type]
    unrealized = sum(known)
    equity = float(account["cash"]) + sum(float(p["value"]) for p in account["positions"])  # type: ignore[index]
    demo_valued = int(account.get("demo_priced_positions", 0))  # type: ignore[arg-type]
    outcomes: dict[str, int] = defaultdict(int, userdata.journal_outcome_counts(user_id))
    entries = sum(outcomes.values())
    judged = outcomes["THESIS_CONFIRMED"] + outcomes["THESIS_BROKEN"]
    demo_fills = sum(1 for o in orders if o["price_status"] != "LIVE")
    return {
        "paper": {"orders": len(orders), "equity": round(equity, 2), "return_pct": round((equity / db.PAPER_STARTING_CASH - 1) * 100, 2),
                  "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2), "closed_trades": len(closed),
                  "winning_trades": sum(1 for g in closed if g > 0), "win_rate_pct": round(sum(1 for g in closed if g > 0) / len(closed) * 100, 1) if closed else None,
                  "fills_on_demo_prices": demo_fills, "positions_valued_on_demo_prices": demo_valued,
                  "demo_priced_positions": demo_valued, "positions_without_pnl": pnl_unavailable},
        "journal": {"entries": entries, "by_outcome": dict(outcomes), "judged": judged,
                    "thesis_hit_rate_pct": round(outcomes["THESIS_CONFIRMED"] / judged * 100, 1) if judged else None},
        "notes": ["Paper results are simulated and mix currencies without FX conversion.",
                  "Hit rate counts only entries you marked confirmed or broken."]
                 + ([f"{demo_fills} simulated fills used DEMO prices and are not meaningful as performance."] if demo_fills else [])
                 + ([f"{demo_valued} open position(s) are valued at DEMO fallback prices, so equity, return and unrealised P&L are not live."] if demo_valued else []),
    }
