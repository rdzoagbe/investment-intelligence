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

    reg = client.post("/api/auth/register", json={"name": "Test User", "email": "Test@Example.com", "password": "long-enough-1"})
    assert reg.status_code == 200, reg.text
    token = reg.json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["email"] == "test@example.com"

    assert client.post("/api/auth/register", json={"name": "Test User", "email": "test@example.com", "password": "long-enough-1"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "test@example.com", "password": "wrong-password"}).status_code == 401
    login = client.post("/api/auth/login", json={"email": "test@example.com", "password": "long-enough-1"})
    assert login.status_code == 200, login.text
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer tampered." + login.json()["access_token"]}).status_code == 401
