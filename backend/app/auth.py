from __future__ import annotations

import base64
import binascii
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


def issue_token(user_id: int, token_version: int = 0) -> str:
    header = _b64(b'{"alg":"HS256","typ":"JWT"}')
    claims = {"sub": user_id, "exp": int(time.time()) + TOKEN_TTL, "ver": int(token_version)}
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    return f"{header}.{payload}.{_sign(header + '.' + payload)}"


def _token_claims(token: str) -> tuple[int, int] | None:
    """(user_id, token_version) from a well-formed, correctly signed, unexpired token."""
    try:
        header, payload, signature = token.split(".")
        if not hmac.compare_digest(signature, _sign(header + "." + payload)):
            return None
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        data = json.loads(raw)
        if int(data["exp"]) < int(time.time()):
            return None
        return int(data["sub"]), int(data.get("ver", 0))
    except (ValueError, KeyError, TypeError, AttributeError, binascii.Error):  # json.JSONDecodeError is a ValueError
        return None


def user_from_token(token: str) -> dict | None:
    """The signed-in user, or None for an invalid/expired/revoked token.

    Database errors are NOT swallowed: they propagate so the API can answer 503 instead of
    telling the client that its (valid) session expired.
    """
    claims = _token_claims(token)
    if claims is None:
        return None
    user_id, version = claims
    row = db.fetch_one("SELECT id,name,email,created_at,token_version FROM users WHERE id=?", (user_id,))
    if not row or int(row.get("token_version") or 0) != version:
        return None
    return {"id": row["id"], "name": row["name"], "email": row["email"], "created_at": row["created_at"], "token_version": int(row.get("token_version") or 0)}


def public_user(user: dict) -> dict:
    return {"id": user["id"], "name": user["name"], "email": user["email"], "created_at": user["created_at"]}


def revoke_tokens(user_id: int) -> None:
    """Invalidate every token issued so far for this user (logout everywhere)."""
    db.execute("UPDATE users SET token_version = token_version + 1 WHERE id=?", (user_id,))


def create_user(name: str, email: str, password: str, terms_accepted_at: int | None = None) -> tuple[dict | None, str | None]:
    name, email = name.strip(), email.strip().lower()
    password_hash, salt = _hash_password(password)
    created_at = int(time.time())
    try:
        user_id = db.insert(
            "INSERT INTO users(name,email,password_hash,salt,created_at,token_version,terms_accepted_at) VALUES(?,?,?,?,?,?,?)",
            (name, email, password_hash, salt, created_at, 0, terms_accepted_at),
        )
    except Exception as exc:
        if db.is_unique_violation(exc):
            # Trade-off: without email verification a sign-up must either fail or hand out a
            # session, so it cannot hide that the address is taken. The message stays generic
            # and registration is rate limited per IP to stop bulk enumeration.
            return None, "This email cannot be used to create an account. If it is yours, sign in instead."
        raise
    return {"id": user_id, "name": name, "email": email, "created_at": created_at, "token_version": 0}, None


# Used when the email is unknown so a failed login costs the same PBKDF2 work either way
# (no timing difference that reveals which emails have accounts).
_DUMMY_SALT = base64.urlsafe_b64encode(b"\x00" * 16).decode()
_DUMMY_HASH = _hash_password(secrets.token_urlsafe(16), b"\x00" * 16)[0]


def authenticate(email: str, password: str) -> dict | None:
    row = db.fetch_one("SELECT * FROM users WHERE email=?", (email.strip().lower(),))
    if not row:
        _verify(password, _DUMMY_HASH, _DUMMY_SALT)
        return None
    if not _verify(password, row["password_hash"], row["salt"]):
        return None
    return {"id": row["id"], "name": row["name"], "email": row["email"], "created_at": row["created_at"], "token_version": int(row.get("token_version") or 0)}


def verify_user_password(user_id: int, password: str) -> bool:
    row = db.fetch_one("SELECT password_hash,salt FROM users WHERE id=?", (user_id,))
    if not row:
        _verify(password, _DUMMY_HASH, _DUMMY_SALT)
        return False
    return _verify(password, row["password_hash"], row["salt"])


def account_record(user_id: int) -> dict:
    """Stored account fields included in a data export (never the password hash or salt)."""
    row = db.fetch_one("SELECT terms_accepted_at FROM users WHERE id=?", (user_id,))
    return {"terms_accepted_at": row.get("terms_accepted_at") if row else None}


def delete_user(user_id: int) -> None:
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
