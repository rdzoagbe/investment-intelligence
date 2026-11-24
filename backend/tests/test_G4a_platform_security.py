"""G4a: auth/session hardening, rate limiting, schema migration, broker, status and dashboard."""
from __future__ import annotations

import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from app import auth, broker, db, main, ratelimit, userdata

PASSWORD = "long-enough-1"


@pytest.fixture()
def client():
    return TestClient(main.app)


def _register(client, email="member@example.com"):
    r = client.post("/api/auth/register", json={"name": "Member", "email": email, "password": PASSWORD, "accept_terms": True})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------- sessions ----------
def test_logout_revokes_existing_tokens(client):
    headers = _register(client)
    second = client.post("/api/auth/login", json={"email": "member@example.com", "password": PASSWORD}).json()["access_token"]
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {second}"}).status_code == 401
    fresh = client.post("/api/auth/login", json={"email": "member@example.com", "password": PASSWORD}).json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {fresh}"}).status_code == 200


def test_logout_requires_authentication(client):
    assert client.post("/api/auth/logout").status_code == 401


def test_database_error_during_session_lookup_is_503_not_401(client, monkeypatch):
    headers = _register(client)

    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(db, "fetch_one", broken)
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 503
    assert "database" in r.json()["detail"].lower()


def test_malformed_tokens_are_401(client):
    for token in ("garbage", "a.b.c", "a.b", ""):
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_unknown_email_login_runs_the_same_pbkdf2_work(monkeypatch):
    calls = []
    real = auth._hash_password
    monkeypatch.setattr(auth, "_hash_password", lambda pw, salt=None: calls.append(1) or real(pw, salt))
    assert auth.authenticate("nobody@example.com", "whatever-password") is None
    assert len(calls) == 1


def test_duplicate_registration_message_is_generic(client):
    _register(client)
    r = client.post("/api/auth/register", json={"name": "Again", "email": "member@example.com", "password": PASSWORD, "accept_terms": True})
    assert r.status_code == 409
    assert "already exists" not in r.json()["detail"]


# ---------- rate limiting ----------
def test_login_is_rate_limited_per_email_and_ip(client):
    _register(client)
    codes = [client.post("/api/auth/login", json={"email": "member@example.com", "password": "wrong-password"}).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429
    r = client.post("/api/auth/login", json={"email": "member@example.com", "password": PASSWORD})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_registration_is_rate_limited_per_ip(client):
    for i in range(5):
        _register(client, f"user{i}@example.com")
    r = client.post("/api/auth/register", json={"name": "Six", "email": "six@example.com", "password": PASSWORD, "accept_terms": True})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_forwarded_for_is_used_only_on_render(client, monkeypatch):
    for i in range(5):
        _register(client, f"a{i}@example.com")
    # Without RENDER the header is ignored: still the same client.
    assert client.post("/api/auth/register", headers={"X-Forwarded-For": "203.0.113.9"}, json={"name": "Xavier", "email": "x1@example.com", "password": PASSWORD, "accept_terms": True}).status_code == 429
    monkeypatch.setenv("RENDER", "true")
    r = client.post("/api/auth/register", headers={"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}, json={"name": "Xavier", "email": "x2@example.com", "password": PASSWORD, "accept_terms": True})
    assert r.status_code == 200


def test_sliding_window_expires():
    assert ratelimit.hit("k", 2, 10, now=0.0) is None
    assert ratelimit.hit("k", 2, 10, now=1.0) is None
    assert ratelimit.hit("k", 2, 10, now=2.0) == 8
    assert ratelimit.hit("k", 2, 10, now=10.5) is None


def test_assistant_is_rate_limited_per_user(client, monkeypatch):
    headers = _register(client)
    from app import assistant
    monkeypatch.setattr(assistant, "ask", lambda question, user_id: {"answer": "ok"})
    codes = [client.post("/api/assistant/ask", headers=headers, json={"question": "What is MSFT?"}).status_code for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[6] == 429


def test_assistant_global_daily_ceiling(client, monkeypatch):
    monkeypatch.setenv("ASSISTANT_GLOBAL_DAILY_LIMIT", "2")
    from app import assistant
    monkeypatch.setattr(assistant, "ask", lambda question, user_id: {"answer": "ok"})
    a, b = _register(client, "a@example.com"), _register(client, "b@example.com")
    assert client.post("/api/assistant/ask", headers=a, json={"question": "q one"}).status_code == 200
    assert client.post("/api/assistant/ask", headers=b, json={"question": "q two"}).status_code == 200
    assert client.post("/api/assistant/ask", headers=b, json={"question": "q three"}).status_code == 429


# ---------- schema ----------
OLD_SCHEMA = [
    "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, salt TEXT NOT NULL, created_at INTEGER NOT NULL)",
    "CREATE TABLE holdings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, symbol TEXT NOT NULL, quantity REAL NOT NULL, average_cost REAL NOT NULL, created_at INTEGER NOT NULL, UNIQUE(user_id, symbol))",
]


def test_existing_sqlite_database_is_migrated_without_data_loss(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    for ddl in OLD_SCHEMA:
        conn.execute(ddl)
    salt_hash, salt = auth._hash_password(PASSWORD)
    conn.execute("INSERT INTO users(name,email,password_hash,salt,created_at) VALUES('Old','old@example.com',?,?,1)", (salt_hash, salt))
    conn.execute("INSERT INTO holdings(user_id,symbol,quantity,average_cost,created_at) VALUES(1,'MSFT',0.7,187.43,1)")
    conn.commit(); conn.close()
    monkeypatch.setenv("AUTH_DB_PATH", str(path))
    row = db.fetch_one("SELECT * FROM users WHERE email='old@example.com'")
    assert row["token_version"] == 0 and row["terms_accepted_at"] is None
    assert db.fetch_one("SELECT quantity FROM holdings")["quantity"] == 0.7
    indexes = {r["name"] for r in db.fetch_all("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_holdings_user", "idx_paper_orders_user", "idx_journal_entries_user"} <= indexes
    # Old accounts can still sign in; running the migration again is a no-op.
    db._initialised.clear()
    assert auth.authenticate("old@example.com", PASSWORD)["id"] == 1


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakePg:
    def __init__(self, real_columns, present_columns=None, indexes=()):
        self.sql: list[str] = []
        self.real_columns = real_columns
        self.present_columns = present_columns if present_columns is not None else set(real_columns)
        self.indexes = set(indexes)
        self.closed = False

    def execute(self, query, params=None):
        self.sql.append(query)
        if "information_schema.columns" in query and "data_type = 'real'" in query:
            return _FakeResult([{"table_name": t, "column_name": c} for t, c in self.real_columns])
        if "information_schema.columns" in query:
            return _FakeResult([{"table_name": t, "column_name": c} for t, c in self.present_columns])
        if "pg_indexes" in query:
            return _FakeResult([{"indexname": n} for n in self.indexes])
        return _FakeResult([])

    def commit(self):
        pass


def test_postgres_bootstrap_uses_double_precision_and_migrates_real_columns():
    conn = _FakePg({("holdings", "quantity"), ("paper_orders", "fill_price"), ("scan_snapshots", "price")})
    db._bootstrap(conn, True, "BIGSERIAL PRIMARY KEY", "BIGINT")
    joined = "\n".join(conn.sql)
    assert conn.sql[0] == "SET LOCAL lock_timeout = '5s'"
    assert any("pg_advisory_xact_lock" in q for q in conn.sql[:3])
    assert " REAL " not in joined and "DOUBLE PRECISION NOT NULL" in joined
    assert "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0" in joined
    assert "ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at BIGINT" in joined
    alters = [q for q in conn.sql if "ALTER COLUMN" in q]
    assert sorted(alters) == sorted([
        "ALTER TABLE holdings ALTER COLUMN quantity TYPE DOUBLE PRECISION",
        "ALTER TABLE paper_orders ALTER COLUMN fill_price TYPE DOUBLE PRECISION",
        "ALTER TABLE scan_snapshots ALTER COLUMN price TYPE DOUBLE PRECISION",
    ])
    assert any("CREATE INDEX IF NOT EXISTS idx_alert_events_user ON alert_events(user_id)" == q for q in conn.sql)
    # Already migrated: no ALTER TABLE or CREATE INDEX at all (they take table locks even as no-ops).
    present = {(t, c) for t, c, _ in db._ADDED_COLUMNS}
    again = _FakePg(set(), present_columns=present, indexes=[n for n, _ in db._INDEXES])
    db._bootstrap(again, True, "BIGSERIAL PRIMARY KEY", "BIGINT")
    assert not [q for q in again.sql if q.startswith("ALTER TABLE") or q.startswith("CREATE INDEX")]


def test_failed_bootstrap_closes_connection_and_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "fail.db"))
    closed = []
    real_connect = sqlite3.connect

    class Conn:
        def __init__(self, *a, **k):
            self._c = real_connect(*a, **k)

        def __getattr__(self, name):
            return getattr(self._c, name)

        def __setattr__(self, name, value):
            if name == "_c":
                object.__setattr__(self, name, value)
            else:
                setattr(self._c, name, value)

        def close(self):
            closed.append(1)
            self._c.close()

    monkeypatch.setattr(db.sqlite3, "connect", Conn)
    monkeypatch.setattr(db, "_bootstrap", lambda *a: (_ for _ in ()).throw(RuntimeError("ddl failed")))
    with pytest.raises(RuntimeError):
        db.fetch_one("SELECT 1")
    assert closed == [1]
    assert str(tmp_path / "fail.db") not in db._initialised


def test_bootstrap_runs_once_under_concurrency(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "race.db"))
    count = []
    real = db._bootstrap
    monkeypatch.setattr(db, "_bootstrap", lambda *a: count.append(1) or real(*a))
    threads = [threading.Thread(target=lambda: db.fetch_one("SELECT 1")) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert count == [1]


# ---------- account data rights ----------
def test_export_and_delete_account(client, monkeypatch):
    headers = _register(client)
    exported, deleted = [], []
    monkeypatch.setattr(userdata, "export_user_data", lambda uid: exported.append(uid) or {"holdings": [], "journal": []}, raising=False)
    real_delete = userdata.delete_user_data
    monkeypatch.setattr(userdata, "delete_user_data", lambda uid, delete_account=False: deleted.append(uid) or real_delete(uid, delete_account=delete_account), raising=False)
    r = client.get("/api/me/export", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.json()["account"]["email"] == "member@example.com" and r.json()["holdings"] == []
    assert client.request("DELETE", "/api/me/account", headers=headers, json={"password": "wrong-password"}).status_code == 403
    assert deleted == []
    r = client.request("DELETE", "/api/me/account", headers=headers, json={"password": PASSWORD})
    assert r.status_code == 200
    assert deleted == exported == [1]
    assert db.fetch_one("SELECT id FROM users WHERE email='member@example.com'") is None
    assert client.get("/api/auth/me", headers=headers).status_code == 401


# ---------- broker ----------
def test_broker_routes_require_authentication(client):
    assert client.post("/api/broker/preview", json={"symbol": "MSFT", "side": "BUY", "quantity": 1}).status_code == 401
    assert client.post("/api/broker/execute", json={"preview_id": "x", "human_approved": True}).status_code == 401


def test_broker_execute_is_bound_to_the_users_stored_preview(client, monkeypatch):
    monkeypatch.setattr(main, "gateway", broker.BrokerGateway())
    alice, bob = _register(client, "alice@example.com"), _register(client, "bob@example.com")
    preview = client.post("/api/broker/preview", headers=alice, json={"symbol": "msft", "side": "buy", "quantity": 2})
    assert preview.status_code == 200 and preview.json()["status"] == "PENDING_HUMAN_APPROVAL"
    pid = preview.json()["id"]
    assert client.post("/api/broker/execute", headers=bob, json={"preview_id": pid, "human_approved": True}).status_code == 404
    done = client.post("/api/broker/execute", headers=alice, json={"preview_id": pid, "human_approved": True})
    assert done.status_code == 200 and done.json()["status"] == "PAPER_BROKER_DISABLED" and done.json()["symbol"] == "MSFT"
    # A preview can be used once.
    assert client.post("/api/broker/execute", headers=alice, json={"preview_id": pid, "human_approved": True}).status_code == 404


def test_broker_paper_execution_restricted_to_operator(client, monkeypatch):
    monkeypatch.setenv("PAPER_BROKER_ENABLED", "true")
    monkeypatch.setattr(main, "gateway", broker.BrokerGateway())
    headers = _register(client)
    pid = client.post("/api/broker/preview", headers=headers, json={"symbol": "MSFT", "side": "BUY", "quantity": 1}).json()["id"]
    assert client.post("/api/broker/execute", headers=headers, json={"preview_id": pid, "human_approved": True}).status_code == 403


@pytest.mark.parametrize("body", [
    {"symbol": "MSFT", "side": "BUY", "quantity": 100_000},
    {"symbol": "MSFT", "side": "BUY", "quantity": 1, "order_type": "STOP"},
    {"symbol": "MSFT", "side": "BUY", "quantity": 1, "order_type": "LIMIT"},
    {"symbol": "../x", "side": "BUY", "quantity": 1},
    {"symbol": "MSFT", "side": "HOLD", "quantity": 1},
])
def test_broker_preview_validates_orders(client, body):
    headers = _register(client)
    assert client.post("/api/broker/preview", headers=headers, json=body).status_code in {400, 422}


# ---------- input bounds ----------
def test_backtest_input_is_bounded(client):
    assert client.post("/api/backtest", json={"prices": [1.0] * 5001, "scores": [50.0] * 5001}).status_code in {413, 422}
    assert client.post("/api/backtest", json={"prices": [100.0, 101.0], "scores": [50.0, 50.0, 50.0]}).status_code == 422
    assert client.post("/api/backtest", json={"prices": [100.0, 101.0, 102.0], "scores": [90.0, 90.0, 50.0]}).status_code == 200


def test_oversized_body_is_rejected(client):
    big = "[" + ",".join(["1.0"] * 100_000) + "]"
    r = client.post("/api/backtest", content=f'{{"prices": {big}, "scores": [1,2]}}', headers={"Content-Type": "application/json"})
    assert r.status_code == 413


# ---------- health / status ----------
def test_health_reports_database(client, monkeypatch):
    assert client.get("/api/health").json()["database"] == "ok"
    monkeypatch.setattr(db, "ping", lambda: False)
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json()["database"] == "unreachable"


def test_status_database_never_leaks_connection_string(client, monkeypatch):
    monkeypatch.setattr(db, "ping", lambda: False)
    monkeypatch.setattr(db, "engine", lambda: "postgresql")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:hunter2@db.internal/app")
    monkeypatch.setenv("SEC_USER_AGENT", "Jane Doe jane@example.com")
    monkeypatch.setenv("JOB_TOKEN", "x" * 30)
    body = client.get("/api/status").json()
    assert body["database"] == {"ok": False, "engine": "postgresql"}
    assert body["config"] == {"anthropic_api_key": "missing", "sec_user_agent": "set", "job_token": "set", "tiingo_api_key": "missing"}
    assert "hunter2" not in str(body) and "jane@example.com" not in str(body)


def test_db_ping_never_raises(monkeypatch):
    monkeypatch.setattr(db, "_connect", lambda: (_ for _ in ()).throw(OSError("down")))
    assert db.ping() is False


# ---------- dashboard snapshot hook ----------
def test_dashboard_triggers_daily_snapshot_in_background(client, monkeypatch):
    from app import monitoring
    called = threading.Event()
    monkeypatch.setenv("DASHBOARD_DAILY_SNAPSHOT", "true")
    monkeypatch.setattr(monitoring, "maybe_run_daily_snapshot", lambda now_utc=None: called.set(), raising=False)
    assert client.get("/api/dashboard").status_code == 200
    assert called.wait(5)


def test_dashboard_survives_snapshot_failure(client, monkeypatch):
    from app import monitoring
    monkeypatch.setenv("DASHBOARD_DAILY_SNAPSHOT", "true")

    def boom(now_utc=None):
        raise RuntimeError("snapshot failed")
    monkeypatch.setattr(monitoring, "maybe_run_daily_snapshot", boom, raising=False)
    assert client.get("/api/dashboard").status_code == 200
