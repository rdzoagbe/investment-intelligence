import "./auth.css";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const tokenKey = "ii_access_token";
const userKey = "ii_user";

type User = { id: number; name: string; email: string; created_at: number };
const root = document.getElementById("root")!;
root.style.visibility = "hidden";

function api(path: string, options: RequestInit = {}) {
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    signal: AbortSignal.timeout(8000),
  });
}

function showAccount(user: User) {
  const old = document.getElementById("ii-account");
  old?.remove();
  const pill = document.createElement("div");
  pill.id = "ii-account";
  pill.innerHTML = `<span class="ii-avatar">${user.name.slice(0, 1).toUpperCase()}</span><span><b>${user.name}</b><small>${user.email}</small></span><button id="ii-logout">Log out</button>`;
  document.body.appendChild(pill);
  document.getElementById("ii-logout")!.onclick = () => {
    localStorage.removeItem(tokenKey);
    localStorage.removeItem(userKey);
    location.reload();
  };
}

function gate(message = "") {
  const backdrop = document.createElement("div");
  backdrop.id = "ii-auth-gate";
  backdrop.innerHTML = `<div class="ii-auth-card">
    <div class="ii-logo">II</div>
    <div class="ii-eyebrow">AI INVESTMENT INTELLIGENCE</div>
    <h1 id="ii-title">Welcome back</h1>
    <p id="ii-subtitle">Sign in to access your private investment workspace.</p>
    <div id="ii-error" class="ii-error">${message}</div>
    <form id="ii-form">
      <div id="ii-name-wrap" class="ii-field hidden"><label>Full name</label><input id="ii-name" autocomplete="name" /></div>
      <div class="ii-field"><label>Email</label><input id="ii-email" type="email" autocomplete="email" required /></div>
      <div class="ii-field"><label>Password</label><input id="ii-password" type="password" autocomplete="current-password" minlength="8" required /></div>
      <button class="ii-primary" type="submit" id="ii-submit">Sign in</button>
    </form>
    <button class="ii-switch" id="ii-switch">New here? Create an account</button>
    <p class="ii-footnote">Your account data is stored server-side. Never share your investment or broker credentials.</p>
  </div>`;
  document.body.appendChild(backdrop);

  let signup = false;
  const title = document.getElementById("ii-title")!;
  const subtitle = document.getElementById("ii-subtitle")!;
  const submit = document.getElementById("ii-submit")!;
  const nameWrap = document.getElementById("ii-name-wrap")!;
  const switcher = document.getElementById("ii-switch")!;
  const error = document.getElementById("ii-error")!;
  const form = document.getElementById("ii-form") as HTMLFormElement;
  const setError = (text: string) => { error.textContent = text; error.classList.toggle("show", !!text); };

  switcher.onclick = () => {
    signup = !signup;
    nameWrap.classList.toggle("hidden", !signup);
    (document.getElementById("ii-name") as HTMLInputElement).required = signup;
    title.textContent = signup ? "Create your account" : "Welcome back";
    subtitle.textContent = signup ? "Create your secure investment research workspace." : "Sign in to access your private investment workspace.";
    submit.textContent = signup ? "Create account" : "Sign in";
    switcher.textContent = signup ? "Already have an account? Sign in" : "New here? Create an account";
    setError("");
  };

  form.onsubmit = async (event) => {
    event.preventDefault();
    setError("");
    submit.setAttribute("disabled", "true");
    submit.textContent = signup ? "Creating…" : "Signing in…";
    try {
      const body = signup
        ? { name: (document.getElementById("ii-name") as HTMLInputElement).value, email: (document.getElementById("ii-email") as HTMLInputElement).value, password: (document.getElementById("ii-password") as HTMLInputElement).value }
        : { email: (document.getElementById("ii-email") as HTMLInputElement).value, password: (document.getElementById("ii-password") as HTMLInputElement).value };
      const response = await api(signup ? "/api/auth/register" : "/api/auth/login", { method: "POST", body: JSON.stringify(body) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Authentication failed.");
      localStorage.setItem(tokenKey, data.access_token);
      localStorage.setItem(userKey, JSON.stringify(data.user));
      backdrop.remove();
      root.style.visibility = "visible";
      showAccount(data.user);
    } catch (err) {
      setError(err instanceof Error && err.message.includes("Failed to fetch") ? "Account service is not connected. Configure VITE_API_BASE_URL for the deployed API." : (err instanceof Error ? err.message : "Unable to sign in."));
      submit.removeAttribute("disabled");
      submit.textContent = signup ? "Create account" : "Sign in";
    }
  };
}

async function boot() {
  const token = localStorage.getItem(tokenKey);
  if (!token) { gate(); return; }
  try {
    const response = await api("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new Error("expired");
    const user = await response.json() as User;
    localStorage.setItem(userKey, JSON.stringify(user));
    root.style.visibility = "visible";
    showAccount(user);
  } catch {
    localStorage.removeItem(tokenKey);
    localStorage.removeItem(userKey);
    gate();
  }
}

void boot();
