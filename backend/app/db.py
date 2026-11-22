"""Shared database access: PostgreSQL when DATABASE_URL is set, SQLite otherwise.

Queries are written with `?` placeholders and translated for PostgreSQL.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_SCHEMA = {
    "users": """CREATE TABLE IF NOT EXISTS users (
        id {pk}, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, salt TEXT NOT NULL, created_at {int} NOT NULL)""",
    "holdings": """CREATE TABLE IF NOT EXISTS holdings (
        id {pk}, user_id {int} NOT NULL, symbol TEXT NOT NULL, quantity REAL NOT NULL,
        average_cost REAL NOT NULL, created_at {int} NOT NULL, UNIQUE(user_id, symbol))""",
    "journal_entries": """CREATE TABLE IF NOT EXISTS journal_entries (
        id {pk}, user_id {int} NOT NULL, symbol TEXT NOT NULL, decision TEXT NOT NULL,
        thesis TEXT NOT NULL, evidence TEXT NOT NULL, review_on TEXT, outcome TEXT,
        created_at {int} NOT NULL)""",
    "paper_orders": """CREATE TABLE IF NOT EXISTS paper_orders (
        id {pk}, user_id {int} NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
        quantity REAL NOT NULL, fill_price REAL NOT NULL, price_status TEXT NOT NULL,
        created_at {int} NOT NULL)""",
}
PAPER_STARTING_CASH = 100_000.0


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def is_postgres() -> bool:
    return bool(database_url())


def _sqlite_path() -> Path:
    return Path(os.getenv("AUTH_DB_PATH", str(Path(__file__).resolve().parent.parent / "investment.db")))


_initialised: set[str] = set()


def _connect() -> Any:
    if is_postgres():
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
        for ddl in _SCHEMA.values():
            conn.execute(ddl.format(pk=pk, int=integer))
        conn.commit()
        _initialised.add(key)
    return conn


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
