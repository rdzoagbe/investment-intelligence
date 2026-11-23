"""The production entrypoint (run.py) must never serve files outside backend/static."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import run


@pytest.fixture()
def client(tmp_path, monkeypatch):
    static = tmp_path / "site" / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<html>app</html>")
    (static / "robots.txt").write_text("ok")
    (tmp_path / "site" / "secret.txt").write_text("TOP-SECRET")
    monkeypatch.setattr(run, "STATIC", static)
    return TestClient(run.app)


@pytest.mark.parametrize("path", [
    "/..%2fsecret.txt",
    "/%2e%2e/secret.txt",
    "/%2e%2e%2fsecret.txt",
    "/..%2f..%2f..%2f..%2f..%2f..%2f..%2fetc%2fpasswd",
    "/assets%2f..%2f..%2fsecret.txt",
])
def test_traversal_is_blocked(client, path):
    r = client.get(path)
    assert "TOP-SECRET" not in r.text and "root:" not in r.text


def test_files_inside_static_and_spa_routes_still_work(client):
    assert client.get("/robots.txt").text == "ok"
    assert "app" in client.get("/some/client/route").text
    assert "app" in client.get("/").text


def test_unknown_api_route_is_a_real_404(client):
    assert client.get("/api/does-not-exist").status_code == 404
