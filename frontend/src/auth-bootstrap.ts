import "./auth.css";
import { API_BASE, AUTH_CHANGED_EVENT, SAVED_VIEW_KEY, SERVER_READY_EVENT, SESSION_EXPIRED_EVENT, STATIC_HOST, TOKEN_KEY as tokenKey, USER_KEY as userKey, clearSession, serverUnavailable } from "./lib";
import { LEGAL, LEGAL_DRAFT_NOTICE, type LegalKey } from "./legal-pages";

type User = { id: number; name: string; email: string; created_at: number };
const root = document.getElementById("root")!;
// A static build has no account server: show the labelled demo directly.
if (!STATIC_HOST) root.style.visibility = "hidden";

const UNAVAILABLE = "The account server is not reachable right now (a free server can take a minute to wake up). Try again, or continue with demo data.";

function api(path: string, options: RequestInit = {}, timeoutMs = 60000) {
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
    signal: AbortSignal.timeout(timeoutMs),
  });
}

/** Parse a response body as JSON; null when it is not JSON (e.g. an HTML error page from a proxy or static host). */
async function jsonOrNull(response: Response): Promise<Record<string, unknown> | null> {
  try { const text = await response.text(); const v = JSON.parse(text); return v && typeof v === "object" ? v as Record<string, unknown> : null; } catch { return null; }
}

function detailText(body: Record<string, unknown> | null, fallback: string) {
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map(x => (x && typeof x === "object" && "msg" in x ? String((x as { msg: unknown }).msg) : "")).filter(Boolean).join("; ") || fallback;
  return fallback;
}

function showAccount(user: User) {
  document.getElementById("ii-account")?.remove();
  const pill = document.createElement("div");
  pill.id = "ii-account";
  // Built with textContent so a user-chosen name can never inject HTML.
  const avatar = document.createElement("span"); avatar.className = "ii-avatar"; avatar.textContent = user.name.slice(0, 1).toUpperCase(); avatar.setAttribute("aria-hidden", "true");
  const info = document.createElement("span");
  const nameEl = document.createElement("b"); nameEl.textContent = user.name;
  const emailEl = document.createElement("small"); emailEl.textContent = user.email;
  info.append(nameEl, emailEl);
  const logout = document.createElement("button"); logout.id = "ii-logout"; logout.type = "button"; logout.textContent = "Log out";
  pill.append(avatar, info, logout);
  document.body.appendChild(pill);
  logout.onclick = async () => {
    logout.disabled = true; logout.textContent = "Logging out…";
    let token: string | null = null;
    try { token = localStorage.getItem(tokenKey); } catch { /* storage unavailable */ }
    // Revoke the token on the server first so a copied token stops working; clear locally either way.
    if (token) await api("/api/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${token}` } }, 10000).catch(() => undefined);
    clearSession();
    location.reload();
  };
}

function legalText(key: LegalKey) {
  const wrap = document.createElement("div");
  const note = document.createElement("p"); note.className = "ii-draft"; note.textContent = LEGAL_DRAFT_NOTICE;
  const h = document.createElement("h2"); h.textContent = LEGAL[key].title;
  wrap.append(note, h);
  for (const s of LEGAL[key].sections) {
    const sh = document.createElement("h3"); sh.textContent = s.heading; wrap.append(sh);
    for (const p of s.paragraphs) { const el = document.createElement("p"); el.textContent = p; wrap.append(el); }
  }
  return wrap;
}

/** Public landing page shown to visitors without a session. Static copy only (no user data). */
function landing() {
  if (document.getElementById("ii-landing")) return;
  const page = document.createElement("main");
  page.id = "ii-landing";
  page.innerHTML = `
    <header class="ii-land-nav">
      <div class="ii-land-brand"><span class="ii-logo" aria-hidden="true">II</span><b>Investment Intelligence</b></div>
      <button type="button" class="ii-land-link" data-go="signin">Sign in</button>
    </header>
    <section class="ii-land-hero">
      <div class="ii-eyebrow">RESEARCH · CHALLENGE · DECIDE</div>
      <h1>Investment research you can check, not just trust.</h1>
      <p class="ii-land-lead">Scores, price history, trend and support/resistance lines, an AI research assistant that cites its evidence, and a decision journal. Every figure shows where it comes from and whether it is live.</p>
      <div class="ii-land-cta">
        <button type="button" class="ii-primary ii-land-start" data-go="signup">Start now. It's free</button>
        <button type="button" class="ii-land-link" data-go="signin">I already have an account</button>
      </div>
      <p class="ii-land-fine">Research and education tool. Not investment advice, not a broker, and no real orders are ever placed.</p>
    </section>
    <section class="ii-land-grid" aria-label="Features">
      <article><h3>Transparent scores</h3><p>A factor model over growth, margins, cash flow, valuation and momentum, with every input's source shown: SEC filings, live prices, or a clearly labelled fallback.</p></article>
      <article><h3>Charts with context</h3><p>Price history with a trend line, 50/200-day averages and support/resistance levels, each explained. These describe past prices, not forecasts.</p></article>
      <article><h3>AI that shows its work</h3><p>Ask questions and get answers built only from the platform's evidence, with clickable citations. Unsupported claims are flagged.</p></article>
      <article><h3>Practice before risking money</h3><p>A simulated 100,000 account, backtests on real history, alerts and a journal that measures how your decisions actually turned out.</p></article>
    </section>
    <section class="ii-land-steps">
      <h2>How it works</h2>
      <ol><li><b>Create a free account.</b> Your holdings, journal and practice trades stay private to you.</li><li><b>Research.</b> Compare assets, read the evidence, check the chart levels.</li><li><b>Decide and record.</b> Write down your thesis, practise with simulated trades, and review the outcome later.</li></ol>
      <button type="button" class="ii-primary ii-land-start" data-go="signup">Start now</button>
    </section>
    <footer class="ii-land-foot">
      <span>Drafts pending legal review:</span>
      <button type="button" class="ii-land-link" data-legal-page="terms">Terms</button>
      <button type="button" class="ii-land-link" data-legal-page="privacy">Privacy notice</button>
      <button type="button" class="ii-land-link" data-legal-page="risk">Risk disclosure</button>
    </footer>
    <div id="ii-land-legal" class="ii-legal hidden" role="document"><button type="button" id="ii-land-legal-close" class="ii-switch">Close</button><div id="ii-land-legal-body"></div></div>`;
  document.body.appendChild(page);
  page.querySelectorAll<HTMLButtonElement>("[data-go]").forEach(b => {
    b.onclick = () => { page.remove(); gate("", false, b.dataset.go === "signup"); };
  });
  const legalBox = document.getElementById("ii-land-legal")!, legalBody = document.getElementById("ii-land-legal-body")!;
  page.querySelectorAll<HTMLButtonElement>("[data-legal-page]").forEach(b => {
    b.onclick = () => { legalBody.replaceChildren(legalText(b.dataset.legalPage as LegalKey)); legalBox.classList.remove("hidden"); document.getElementById("ii-land-legal-close")!.focus(); legalBox.scrollIntoView({ behavior: "smooth" }); };
  });
  document.getElementById("ii-land-legal-close")!.onclick = () => legalBox.classList.add("hidden");
  (page.querySelector(".ii-land-start") as HTMLButtonElement).focus();
}

function gate(message = "", showDemo = !!message, startInSignup = false) {
  if (document.getElementById("ii-auth-gate")) return;
  const backdrop = document.createElement("div");
  backdrop.id = "ii-auth-gate";
  backdrop.setAttribute("role", "dialog");
  backdrop.setAttribute("aria-modal", "true");
  backdrop.setAttribute("aria-labelledby", "ii-title");
  backdrop.innerHTML = `<div class="ii-auth-card">
    <div class="ii-logo" aria-hidden="true">II</div>
    <div class="ii-eyebrow">AI INVESTMENT INTELLIGENCE</div>
    <h1 id="ii-title">Welcome back</h1>
    <p id="ii-subtitle">Sign in to access your private investment workspace.</p>
    <div id="ii-error" class="ii-error" role="alert"></div>
    <form id="ii-form">
      <div id="ii-name-wrap" class="ii-field hidden"><label for="ii-name">Full name</label><input id="ii-name" autocomplete="name" /></div>
      <div class="ii-field"><label for="ii-email">Email</label><input id="ii-email" type="email" autocomplete="email" required /></div>
      <div class="ii-field"><label for="ii-password">Password</label><input id="ii-password" type="password" autocomplete="current-password" minlength="8" required /></div>
      <div id="ii-terms-wrap" class="ii-terms hidden">
        <label for="ii-terms"><input id="ii-terms" type="checkbox" /> I have read the Terms, Privacy notice and Risk disclosure</label>
        <div class="ii-legal-links">Read: <button type="button" data-legal="terms">Terms</button> · <button type="button" data-legal="privacy">Privacy notice</button> · <button type="button" data-legal="risk">Risk disclosure</button></div>
      </div>
      <button class="ii-primary" type="submit" id="ii-submit">Sign in</button>
    </form>
    <button class="ii-switch" id="ii-switch" type="button">New here? Create an account</button>
    <button class="ii-switch hidden" id="ii-demo" type="button">Continue with demo data (no account)</button>
    <p class="ii-footnote">Research and education tool, not investment advice. Your account data is stored server-side. Never share your investment or broker credentials.</p>
    <div id="ii-legal" class="ii-legal hidden" role="document"><button type="button" id="ii-legal-close" class="ii-switch">Back to sign-in</button><div id="ii-legal-body"></div></div>
  </div>`;
  document.body.appendChild(backdrop);

  let signup = false;
  const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
  const title = $("ii-title"), subtitle = $("ii-subtitle"), submit = $<HTMLButtonElement>("ii-submit"), nameWrap = $("ii-name-wrap");
  const termsWrap = $("ii-terms-wrap"), terms = $<HTMLInputElement>("ii-terms"), switcher = $("ii-switch"), error = $("ii-error");
  const form = $<HTMLFormElement>("ii-form"), demo = $("ii-demo"), legal = $("ii-legal"), legalBody = $("ii-legal-body");
  const setError = (text: string) => { error.textContent = text; error.classList.toggle("show", !!text); };
  const showDemoButton = () => demo.classList.remove("hidden");
  setError(message);
  if (showDemo) showDemoButton();

  switcher.onclick = () => {
    signup = !signup;
    nameWrap.classList.toggle("hidden", !signup);
    termsWrap.classList.toggle("hidden", !signup);
    $<HTMLInputElement>("ii-name").required = signup;
    terms.required = signup;
    $<HTMLInputElement>("ii-password").autocomplete = signup ? "new-password" : "current-password";
    title.textContent = signup ? "Create your account" : "Welcome back";
    subtitle.textContent = signup ? "Create your secure investment research workspace." : "Sign in to access your private investment workspace.";
    submit.textContent = signup ? "Create account" : "Sign in";
    switcher.textContent = signup ? "Already have an account? Sign in" : "New here? Create an account";
    setError("");
  };

  if (startInSignup) switcher.click();
  $<HTMLInputElement>(startInSignup ? "ii-name" : "ii-email").focus();

  backdrop.querySelectorAll<HTMLButtonElement>("[data-legal]").forEach(b => {
    b.onclick = () => { legalBody.replaceChildren(legalText(b.dataset.legal as LegalKey)); legal.classList.remove("hidden"); $("ii-legal-close").focus(); };
  });
  $("ii-legal-close").onclick = () => { legal.classList.add("hidden"); terms.focus(); };

  demo.onclick = () => { backdrop.remove(); root.style.visibility = "visible"; };

  // Probe the API so a host without one (static deploy, wrong proxy) offers the demo instead of a dead form.
  if (!showDemo) {
    api("/api/health", {}, 60000).then(async r => {
      const body = await jsonOrNull(r);
      if (!r.ok || body === null) { if (!error.textContent) setError(UNAVAILABLE); showDemoButton(); }
    }).catch(() => { if (!error.textContent) setError(UNAVAILABLE); showDemoButton(); });
  }

  form.onsubmit = async (event) => {
    event.preventDefault();
    setError("");
    if (signup && !terms.checked) { setError("Please confirm that you have read the Terms, Privacy notice and Risk disclosure."); terms.focus(); return; }
    submit.disabled = true;
    submit.textContent = signup ? "Creating…" : "Signing in…";
    const reset = () => { submit.disabled = false; submit.textContent = signup ? "Create account" : "Sign in"; };
    try {
      const email = $<HTMLInputElement>("ii-email").value, password = $<HTMLInputElement>("ii-password").value;
      const body = signup ? { name: $<HTMLInputElement>("ii-name").value, email, password, accept_terms: true } : { email, password };
      const response = await api(signup ? "/api/auth/register" : "/api/auth/login", { method: "POST", body: JSON.stringify(body) });
      const data = await jsonOrNull(response);
      if (!response.ok) {
        if (response.status === 429) {
          const retry = Number(response.headers.get("Retry-After"));
          setError(`${detailText(data, "Too many attempts.")}${Number.isFinite(retry) && retry > 0 ? ` Try again in about ${Math.ceil(retry / 60)} minute${retry > 60 ? "s" : ""}.` : ""}`);
        } else if (serverUnavailable(response.status, data)) {
          setError(UNAVAILABLE); showDemoButton();
        } else {
          setError(detailText(data, "Authentication failed."));
        }
        reset(); return;
      }
      if (!data || typeof data.access_token !== "string" || !data.user) { setError(UNAVAILABLE); showDemoButton(); reset(); return; }
      // A new sign-in never inherits another session's saved research view.
      try { localStorage.removeItem(SAVED_VIEW_KEY); } catch { /* storage unavailable */ }
      localStorage.setItem(tokenKey, data.access_token);
      localStorage.setItem(userKey, JSON.stringify(data.user));
      backdrop.remove();
      root.style.visibility = "visible";
      showAccount(data.user as User);
      // Lets the app re-detect API mode and reload per-user data without a page reload.
      window.dispatchEvent(new CustomEvent(AUTH_CHANGED_EVENT));
    } catch {
      setError(UNAVAILABLE); showDemoButton(); reset();
    }
  };
}

// Any authenticated request that returns 401 (expired or revoked token) re-opens the sign-in gate.
window.addEventListener(SESSION_EXPIRED_EVENT, () => {
  document.getElementById("ii-account")?.remove();
  gate("Your session has expired or was signed out. Please sign in again.", false);
});

async function boot() {
  if (STATIC_HOST) return;
  let token: string | null = null;
  try { token = localStorage.getItem(tokenKey); } catch { /* storage unavailable */ }
  if (!token) { landing(); return; }
  // With a stored session, show the app at once (it says it is connecting and may show this
  // account's labelled saved copy) while the server, which can take a minute to wake, confirms it.
  let stored: User | null = null;
  try { stored = JSON.parse(localStorage.getItem(userKey) || "null") as User | null; } catch { stored = null; }
  const optimistic = !!stored && typeof stored.id === "number";
  if (optimistic) { root.style.visibility = "visible"; showAccount(stored as User); }
  // Confirm the session. With an optimistic start, a server that is still waking (timeout, 5xx)
  // is retried; once it answers, AUTH_CHANGED makes the app re-detect API mode, and a 401 at any
  // point still ends in the sign-in gate.
  // Stop as soon as the stored session is no longer the one this check started with (signed out,
  // expired elsewhere, or a new sign-in): acting on the old token could undo a newer session.
  const stillCurrent = () => { try { return localStorage.getItem(tokenKey) === token; } catch { return false; } };
  for (let attempt = 0; ; attempt++) {
    if (!stillCurrent()) return;
    try {
      const response = await api("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } });
      if (!stillCurrent()) return;
      if (response.status === 401) { clearSession(); document.getElementById("ii-account")?.remove(); root.style.visibility = "hidden"; gate(); return; }
      const user = await jsonOrNull(response);
      if (response.ok && user) {
        if (optimistic && (user as unknown as User).id !== stored!.id) {
          try { localStorage.removeItem(SAVED_VIEW_KEY); } catch { /* storage unavailable */ }
        }
        localStorage.setItem(userKey, JSON.stringify(user));
        root.style.visibility = "visible";
        showAccount(user as unknown as User);
        if (optimistic && (user as unknown as User).id !== stored!.id) window.dispatchEvent(new CustomEvent(AUTH_CHANGED_EVENT));
        else if (attempt > 0) window.dispatchEvent(new CustomEvent(SERVER_READY_EVENT));
        return;
      }
      if (!optimistic) { gate("The account server returned an error. Try again later or continue with demo data."); return; }
    } catch {
      if (!optimistic) { gate("The account server is not reachable right now. A free server can take a minute to wake up."); return; }
    }
    if (attempt >= 20) return;  // ~5 minutes of retries; the app shows its own connection status meanwhile
    await new Promise(resolve => setTimeout(resolve, 15000));
  }
}

void boot();
