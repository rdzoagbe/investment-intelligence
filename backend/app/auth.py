from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from . import db

JWT_SECRET = os.getenv("AUTH_SECRET") or secrets.token_hex(32)
TOKEN_TTL = 60 * 60 * 24 * 7


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
    payload = _b64(json.dumps({"sub": user_id, "exp": int(time.time()) + TOKEN_TTL}, separators=(",", ":")).encode())
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
        return db.fetch_one("SELECT id,name,email,created_at FROM users WHERE id=?", (int(data["sub"]),))
    except Exception:
        return None


def create_user(name: str, email: str, password: str) -> tuple[dict | None, str | None]:
    name, email = name.strip(), email.strip().lower()
    password_hash, salt = _hash_password(password)
    created_at = int(time.time())
    try:
        user_id = db.insert("INSERT INTO users(name,email,password_hash,salt,created_at) VALUES(?,?,?,?,?)", (name, email, password_hash, salt, created_at))
    except Exception as exc:
        if db.is_unique_violation(exc):
            return None, "An account with this email already exists."
        raise
    return {"id": user_id, "name": name, "email": email, "created_at": created_at}, None


def authenticate(email: str, password: str) -> dict | None:
    row = db.fetch_one("SELECT * FROM users WHERE email=?", (email.strip().lower(),))
    if not row or not _verify(password, row["password_hash"], row["salt"]):
        return None
    return {"id": row["id"], "name": row["name"], "email": row["email"], "created_at": row["created_at"]}
