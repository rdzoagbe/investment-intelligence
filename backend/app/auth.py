from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_PATH = Path(os.getenv("AUTH_DB_PATH", str(Path(__file__).resolve().parent.parent / "investment.db")))
JWT_SECRET = os.getenv("AUTH_SECRET") or secrets.token_hex(32)
TOKEN_TTL = 60 * 60 * 24 * 7


def _is_postgres() -> bool:
    return bool(DATABASE_URL)


def _db():
    """Use PostgreSQL in hosted environments and SQLite locally/tests."""
    if _is_postgres():
        import psycopg
        from psycopg.rows import dict_row
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        conn = psycopg.connect(url, row_factory=dict_row)
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at BIGINT NOT NULL
        )""")
        conn.commit()
        return conn

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""")
    conn.commit()
    return conn


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return base64.urlsafe_b64encode(digest).decode(), base64.urlsafe_b64encode(salt).decode()


def _verify(password: str, password_hash: str, salt: str) -> bool:
    digest, _ = _hash_password(password, base64.urlsafe_b64decode(salt.encode()))
    return hmac.compare_digest(digest, password_hash)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _sign(value: str) -> str:
    return _b64(hmac.new(JWT_SECRET.encode(), value.encode(), hashlib.sha256).digest())


def issue_token(user_id: int) -> str:
    header = _b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64((f'{"sub":{user_id},"exp":{int(time.time()) + TOKEN_TTL}}').encode())
    return f"{header}.{payload}.{_sign(header + '.' + payload)}"


def user_from_token(token: str) -> dict | None:
    try:
        header, payload, signature = token.split(".")
        if not hmac.compare_digest(signature, _sign(header + "." + payload)):
            return None
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        data = json.loads(raw)
        if int(data["exp"]) < int(time.time()):
            return None
        user_id = int(data["sub"])
        placeholder = "%s" if _is_postgres() else "?"
        with _db() as conn:
            row = conn.execute(f"SELECT id,name,email,created_at FROM users WHERE id={placeholder}", (user_id,)).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def create_user(name: str, email: str, password: str) -> tuple[dict | None, str | None]:
    name, email = name.strip(), email.strip().lower()
    password_hash, salt = _hash_password(password)
    created_at = int(time.time())
    try:
        with _db() as conn:
            if _is_postgres():
                row = conn.execute(
                    "INSERT INTO users(name,email,password_hash,salt,created_at) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                    (name, email, password_hash, salt, created_at),
                ).fetchone()
                user_id = int(row["id"])
            else:
                cur = conn.execute(
                    "INSERT INTO users(name,email,password_hash,salt,created_at) VALUES(?,?,?,?,?)",
                    (name, email, password_hash, salt, created_at),
                )
                user_id = int(cur.lastrowid)
        return {"id": user_id, "name": name, "email": email, "created_at": created_at}, None
    except sqlite3.IntegrityError:
        return None, "An account with this email already exists."
    except Exception as exc:
        if _is_postgres() and exc.__class__.__name__ == "UniqueViolation":
            return None, "An account with this email already exists."
        raise


def authenticate(email: str, password: str) -> dict | None:
    placeholder = "%s" if _is_postgres() else "?"
    with _db() as conn:
        row = conn.execute(f"SELECT * FROM users WHERE email={placeholder}", (email.strip().lower(),)).fetchone()
    if not row or not _verify(password, row["password_hash"], row["salt"]):
        return None
    return {"id": row["id"], "name": row["name"], "email": row["email"], "created_at": row["created_at"]}
