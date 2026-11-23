from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_register_login_and_session_round_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    from app import auth, main
    importlib.reload(auth)
    importlib.reload(main)
    client = TestClient(main.app)

    reg = client.post("/api/auth/register", json={"name": "Test User", "email": "Test@Example.com", "password": "long-enough-1", "accept_terms": True})
    assert reg.status_code == 200, reg.text
    token = reg.json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["email"] == "test@example.com"

    assert client.post("/api/auth/register", json={"name": "Test User", "email": "test@example.com", "password": "long-enough-1", "accept_terms": True}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "test@example.com", "password": "wrong-password"}).status_code == 401
    login = client.post("/api/auth/login", json={"email": "test@example.com", "password": "long-enough-1"})
    assert login.status_code == 200, login.text
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer tampered." + login.json()["access_token"]}).status_code == 401


def test_register_requires_accepting_terms():
    from app import main
    client = TestClient(main.app)
    for body in ({}, {"accept_terms": False}):
        r = client.post("/api/auth/register", json={"name": "No Terms", "email": "noterms@example.com", "password": "long-enough-1", **body})
        assert r.status_code == 400, r.text
    ok = client.post("/api/auth/register", json={"name": "Terms", "email": "terms@example.com", "password": "long-enough-1", "accept_terms": True})
    assert ok.status_code == 200
    from app import db
    row = db.fetch_one("SELECT terms_accepted_at FROM users WHERE email=?", ("terms@example.com",))
    assert row["terms_accepted_at"] and row["terms_accepted_at"] > 0
    assert "token_version" not in ok.json()["user"]


def test_register_rejects_malformed_email():
    from app import main
    r = TestClient(main.app).post("/api/auth/register", json={"name": "Bad", "email": "not-an-email", "password": "long-enough-1", "accept_terms": True})
    assert r.status_code == 422
