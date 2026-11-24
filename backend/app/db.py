"""Shared database access: PostgreSQL when DATABASE_URL is set, SQLite otherwise.

Queries are written with `?` placeholders and translated for PostgreSQL.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_SCHEMA = {
    "users": """CREATE TABLE IF NOT EXISTS users (
        id {pk}, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, salt TEXT NOT NULL, created_at {int} NOT NULL,
        token_version INTEGER NOT NULL DEFAULT 0, terms_accepted_at {int})""",
    "holdings": """CREATE TABLE IF NOT EXISTS holdings (
        id {pk}, user_id {int} NOT NULL, symbol TEXT NOT NULL, quantity {real} NOT NULL,
        average_cost {real} NOT NULL, created_at {int} NOT NULL, UNIQUE(user_id, symbol))""",
    "journal_entries": """CREATE TABLE IF NOT EXISTS journal_entries (
        id {pk}, user_id {int} NOT NULL, symbol TEXT NOT NULL, decision TEXT NOT NULL,
        thesis TEXT NOT NULL, evidence TEXT NOT NULL, review_on TEXT, outcome TEXT,
        created_at {int} NOT NULL)""",
    "paper_orders": """CREATE TABLE IF NOT EXISTS paper_orders (
        id {pk}, user_id {int} NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
        quantity {real} NOT NULL, fill_price {real} NOT NULL, price_status TEXT NOT NULL,
        created_at {int} NOT NULL)""",
    "assistant_queries": """CREATE TABLE IF NOT EXISTS assistant_queries (
        id {pk}, user_id {int} NOT NULL, question TEXT NOT NULL, response TEXT NOT NULL,
        provider TEXT NOT NULL, created_at {int} NOT NULL)""",
    "alert_rules": """CREATE TABLE IF NOT EXISTS alert_rules (
        id {pk}, user_id {int} NOT NULL, symbol TEXT NOT NULL, kind TEXT NOT NULL,
        threshold {real} NOT NULL, active {int} NOT NULL, last_triggered_at {int},
        created_at {int} NOT NULL)""",
    "alert_events": """CREATE TABLE IF NOT EXISTS alert_events (
        id {pk}, user_id {int} NOT NULL, rule_id {int}, symbol TEXT NOT NULL,
        message TEXT NOT NULL, is_read {int} NOT NULL, created_at {int} NOT NULL)""",
    "scan_snapshots": """CREATE TABLE IF NOT EXISTS scan_snapshots (
        id {pk}, snapshot_date TEXT NOT NULL, symbol TEXT NOT NULL, score {real} NOT NULL,
        price {real} NOT NULL, price_status TEXT NOT NULL, currency TEXT NOT NULL,
        created_at {int} NOT NULL, UNIQUE(snapshot_date, symbol))""",
    # Responses from licensed data providers (e.g. Tiingo daily history), kept so a restart of
    # a free server does not spend the provider's small hourly request allowance again.
    "provider_cache": """CREATE TABLE IF NOT EXISTS provider_cache (
        cache_key TEXT PRIMARY KEY, fetched_at {int} NOT NULL, payload TEXT NOT NULL)""",
}
PAPER_STARTING_CASH = 100_000.0


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def is_postgres() -> bool:
    return bool(database_url())


def _sqlite_path() -> Path:
    return Path(os.getenv("AUTH_DB_PATH", str(Path(__file__).resolve().parent.parent / "investment.db")))


_initialised: set[str] = set()
_init_lock = threading.Lock()
# Arbitrary constant key for pg_advisory_xact_lock: serialises schema bootstrap across
# processes/instances that start at the same time.
_SCHEMA_LOCK_KEY = 72_410_118

# Columns that hold money or quantities. They used to be REAL, which is a 4-byte float4 on
# PostgreSQL (0.7 is stored as 0.699999988). New tables use DOUBLE PRECISION; existing
# deployments are migrated in place by _migrate(). Values already stored as float4 keep
# their rounding after the migration.
_FLOAT_COLUMNS = {
    "holdings": ("quantity", "average_cost"),
    "paper_orders": ("quantity", "fill_price"),
    "alert_rules": ("threshold",),
    "scan_snapshots": ("score", "price"),
}
# Columns added after the first deployment: (table, column, definition per engine).
_ADDED_COLUMNS = (
    ("users", "token_version", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "terms_accepted_at", "{int}"),
    # Currency the price was quoted in when the row was written. Older rows have NULL and are
    # read with userdata.LEGACY_CURRENCY (ASML/SAP used to be priced from their USD ADRs).
    ("holdings", "currency", "TEXT"),
    ("paper_orders", "currency", "TEXT"),
)
_INDEXES = (
    ("idx_holdings_user", "holdings"),
    ("idx_journal_entries_user", "journal_entries"),
    ("idx_paper_orders_user", "paper_orders"),
    ("idx_assistant_queries_user", "assistant_queries"),
    ("idx_alert_rules_user", "alert_rules"),
    ("idx_alert_events_user", "alert_events"),
)


def engine() -> str:
    return "postgresql" if is_postgres() else "sqlite"


def _migrate(conn: Any, postgres: bool, integer: str) -> None:
    """Idempotent in-place upgrades for databases created by earlier versions."""
    if postgres:
        # Check the catalogue first: ALTER TABLE / CREATE INDEX take table locks even when they
        # turn out to be no-ops, so on an up-to-date database this path must not issue them.
        present = {(r["table_name"], r["column_name"]) for r in conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema()").fetchall()}
        for table, column, definition in _ADDED_COLUMNS:
            if (table, column) not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition.format(int=integer)}")
        indexes = {r["indexname"] for r in conn.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()").fetchall()}
        for name, table in _INDEXES:
            if name not in indexes:
                conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}(user_id)")
        rows = conn.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND data_type = 'real'"
        ).fetchall()
        real_columns = {(r["table_name"], r["column_name"]) for r in rows}
        for table, columns in _FLOAT_COLUMNS.items():
            for column in columns:
                if (table, column) in real_columns:
                    conn.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE DOUBLE PRECISION")
    else:
        # SQLite: REAL is already an 8-byte double, so only missing columns are added.
        for table, column, definition in _ADDED_COLUMNS:
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition.format(int=integer)}")
        for name, table in _INDEXES:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}(user_id)")


def _bootstrap(conn: Any, postgres: bool, pk: str, integer: str) -> None:
    if postgres:
        # Fail fast instead of queueing every request behind a migration that waits on a lock
        # (e.g. a pg_dump in progress); the next connection retries the bootstrap.
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute("SET LOCAL statement_timeout = '60s'")
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,))
    real = "DOUBLE PRECISION" if postgres else "REAL"
    for ddl in _SCHEMA.values():
        conn.execute(ddl.format(pk=pk, int=integer, real=real))
    _migrate(conn, postgres, integer)
    conn.commit()


def _connect() -> Any:
    postgres = is_postgres()
    if postgres:
        import psycopg
        from psycopg.rows import dict_row
        url = database_url()
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        conn = psycopg.connect(url, row_factory=dict_row)
        key, pk, integer = url, "BIGSERIAL PRIMARY KEY", "BIGINT"
    else:
        path = _sqlite_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        key, pk, integer = str(path), "INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER"
    if key not in _initialised:
        try:
            with _init_lock:
                if key not in _initialised:
                    _bootstrap(conn, postgres, pk, integer)
                    _initialised.add(key)
        except BaseException:
            try:
                conn.rollback()
            finally:
                conn.close()
            raise
    return conn


def ping() -> bool:
    """True when a trivial query succeeds. Never raises and never exposes connection details."""
    try:
        with connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False


@contextmanager
def connection() -> Iterator[Any]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sql(query: str) -> str:
    return query.replace("?", "%s") if is_postgres() else query


def fetch_all(query: str, params: tuple = ()) -> list[dict[str, Any]]:
    with connection() as conn:
        return [dict(row) for row in conn.execute(_sql(query), params).fetchall()]


def fetch_one(query: str, params: tuple = ()) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(_sql(query), params).fetchone()
        return dict(row) if row else None


def execute(query: str, params: tuple = ()) -> None:
    with connection() as conn:
        conn.execute(_sql(query), params)


def insert(query: str, params: tuple = ()) -> int:
    """Run an INSERT and return the new row id on both engines."""
    with connection() as conn:
        if is_postgres():
            row = conn.execute(_sql(query) + " RETURNING id", params).fetchone()
            return int(row["id"])
        return int(conn.execute(query, params).lastrowid)


def is_unique_violation(exc: Exception) -> bool:
    return isinstance(exc, sqlite3.IntegrityError) or exc.__class__.__name__ == "UniqueViolation"
