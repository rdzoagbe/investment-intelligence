"""G5 frontend checks: reproducible dependencies, source-level regressions, and pure-logic helpers.

The logic tests transpile the helper modules with the project's own TypeScript compiler and run them
under Node. They are skipped when Node or frontend/node_modules is not installed.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
SRC = FRONTEND / "src"


def read(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


# ---------- #25 reproducible dependencies ----------
def test_dependencies_are_pinned_and_locked() -> None:
    pkg = json.loads((FRONTEND / "package.json").read_text())
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    assert deps, "no dependencies declared"
    for name, version in deps.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"{name} must be pinned to an exact version, got {version!r}"
    for needed in ("@types/react", "@types/react-dom", "vite", "react", "react-dom"):
        assert needed in deps
    lock = json.loads((FRONTEND / "package-lock.json").read_text())
    packages = lock["packages"]
    for name, version in deps.items():
        assert packages[f"node_modules/{name}"]["version"] == version, f"lockfile out of sync for {name}"


# ---------- source-level regressions ----------
def test_account_forms_never_fall_back_to_hidden_symbol() -> None:  # #23
    for name in ("account-pages.tsx", "insight-pages.tsx", "main.tsx"):
        assert '?? "MSFT"' not in read(name), f"hidden MSFT fallback in {name}"
    main = read("main.tsx")
    # Account pages receive the unfiltered universe; only the scanner/command-center table is filtered.
    for page in ("AlertsPage", "CommitteePage", "MyPortfolioPage", "PaperTradingPage", "JournalPage", "BacktestPage"):
        m = re.search(rf"<{page} [^>]*>", main)
        assert m and "filtered" not in m.group(0), f"{page} must not receive the filtered list"


def test_modal_and_inputs_are_accessible() -> None:  # #55 #67 #54
    main = read("main.tsx")
    assert 'role="dialog"' in main and 'aria-modal="true"' in main and '"Escape"' in main
    assert 'aria-label="Filter research universe"' in main
    assert 'aria-label="Question for the research assistant"' in read("insight-pages.tsx")
    auth = read("auth-bootstrap.ts")
    for field in ("ii-name", "ii-email", "ii-password", "ii-terms"):
        assert f'for="{field}"' in auth


def test_signup_requires_terms_and_logout_revokes_token() -> None:  # C8
    auth = read("auth-bootstrap.ts")
    assert "accept_terms: true" in auth
    assert '"/api/auth/logout"' in auth
    legal = read("legal-pages.tsx")
    assert "DRAFT - not legal advice" in legal
    for phrase in ("not investment advice", "not a broker", "Yahoo Finance", "SEC EDGAR", "RSS", "Anthropic or OpenAI", "Frankfurt", "Export my data", "Delete my account"):
        assert phrase.lower() in legal.lower(), phrase


def test_no_buy_sell_recommendation_wording_in_bands() -> None:
    lib = read("lib.tsx")
    assert '"High score"' in lib and '"Low score"' in lib
    assert not re.search(r'label: "(BUY|SELL|HOLD|AVOID)"', lib)


def test_journal_due_flag_uses_local_date() -> None:  # #66
    pages = read("account-pages.tsx")
    assert "toISOString().slice(0, 10)" not in pages
    assert "localToday()" in pages


def test_dashboard_failure_does_not_force_demo() -> None:  # #21
    main = read("main.tsx")
    assert "Promise.all(" not in main
    assert '"/api/scanner?limit=100"' in main and '"/api/dashboard"' in main


# ---------- pure-logic helpers under Node ----------
NODE_SCRIPT = r"""
import assert from "node:assert/strict";
globalThis.location = { hostname: "localhost" };
const store = new Map();
globalThis.localStorage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) };
const events = [];
globalThis.window = { dispatchEvent: e => events.push(e.type) };
globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
const lib = await import("./lib.js");
const insight = await import("./insight-pages.js");

// #66 local date
assert.equal(lib.localToday(new Date(2026, 0, 5, 23, 30)), "2026-01-05");

// #32 auth response classification
assert.equal(lib.serverUnavailable(502, null), true);
assert.equal(lib.serverUnavailable(404, null), true);
assert.equal(lib.serverUnavailable(405, { detail: "Method Not Allowed" }), true);
assert.equal(lib.serverUnavailable(200, null), true);
assert.equal(lib.serverUnavailable(401, { detail: "Invalid email or password." }), false);
assert.equal(lib.serverUnavailable(400, { detail: "You must accept the Terms" }), false);
assert.equal(lib.serverUnavailable(422, { detail: [{ msg: "bad" }] }), false);
assert.equal(lib.serverUnavailable(400, {}), true);

// badges
assert.equal(lib.statusCls("PARTIAL"), "st-partial");
assert.equal(lib.statusCls("UNAVAILABLE"), "st-unavail");
assert.equal(lib.statusCls("LIVE"), "st-live");
assert.equal(lib.statusCls("DEMO"), "st-demo");
assert.equal(lib.cls(null), "");
assert.equal(lib.pct(null), "—");

// C7 citation forms
assert.deepEqual(insight.expandCitations("[E1, E2]"), ["E1", "E2"]);
assert.deepEqual(insight.expandCitations("[E1-E3]"), ["E1", "E2", "E3"]);
assert.deepEqual(insight.expandCitations("[e2]"), ["E2"]);
assert.deepEqual(insight.expandCitations("[E4–6; e9]"), ["E4", "E5", "E6", "E9"]);

// #64 a 401 on an authenticated request clears the session and re-opens sign-in
localStorage.setItem(lib.TOKEN_KEY, "tok"); localStorage.setItem(lib.USER_KEY, "{}");
globalThis.fetch = async () => new Response(JSON.stringify({ detail: "Session expired or invalid." }), { status: 401, headers: { "Content-Type": "application/json" } });
await assert.rejects(lib.api("/api/me/portfolio"), e => e instanceof lib.ApiError && e.status === 401);
assert.equal(localStorage.getItem(lib.TOKEN_KEY), null);
assert.ok(events.includes(lib.SESSION_EXPIRED_EVENT));

// #22 an aborted request rejects with AbortError (callers ignore it)
globalThis.fetch = (url, init) => new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(init.signal.reason)));
const ctrl = new AbortController();
const pending = lib.api("/api/assets/NVDA/analysis", { signal: ctrl.signal });
ctrl.abort();
await assert.rejects(pending, e => lib.isAbort(e));
console.log("ok");
"""


@pytest.mark.skipif(shutil.which("node") is None or not (FRONTEND / "node_modules" / "typescript").exists(), reason="node or frontend/node_modules not installed")
def test_frontend_logic_helpers(tmp_path: Path) -> None:
    out = FRONTEND / "node_modules" / ".cache" / "g5-test"  # inside node_modules so 'react' resolves
    shutil.rmtree(out, ignore_errors=True)
    tsc = FRONTEND / "node_modules" / ".bin" / "tsc"
    cmd = [str(tsc), "--outDir", str(out), "--jsx", "react-jsx", "--module", "esnext", "--moduleResolution", "bundler", "--target", "es2022",
           "--skipLibCheck", "--resolveJsonModule", "--types", "vite/client", "--noEmitOnError", "false",
           str(SRC / "lib.tsx"), str(SRC / "insight-pages.tsx")]
    subprocess.run(cmd, cwd=FRONTEND, capture_output=True, text=True, timeout=120)
    for name in ("lib.js", "insight-pages.js"):
        f = out / name
        assert f.exists(), f"transpile failed for {name}"
        text = f.read_text()
        text = text.replace("import.meta.env", "({})")
        text = re.sub(r'from "\./([\w-]+)"', r'from "./\1.js"', text)
        f.write_text(text)
    (out / "package.json").write_text('{"type": "module"}')
    (out / "run.mjs").write_text(NODE_SCRIPT)
    result = subprocess.run(["node", "run.mjs"], cwd=out, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "ok" in result.stdout
