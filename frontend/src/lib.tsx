import type { ReactNode } from "react";

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
// A static build (GitHub Pages, or any host built with VITE_STATIC_DEMO=true) has no API server
// unless one is configured explicitly. The github.io check is kept as a fallback for older builds.
export const STATIC_HOST = !API_BASE && (import.meta.env.VITE_STATIC_DEMO === "true" || location.hostname.endsWith("github.io"));
export const TOKEN_KEY = "ii_access_token";
export const USER_KEY = "ii_user";
/** Fired on window when the stored session changes (sign-in, sign-out, expiry). */
export const AUTH_CHANGED_EVENT = "ii-auth-changed";
/** Fired on window when an authenticated request is rejected with 401: the sign-in gate re-opens. */
export const SESSION_EXPIRED_EVENT = "ii-session-expired";

export type Mode = { kind: "loading" } | { kind: "api" } | { kind: "demo"; reason: string };
export const signedIn = () => { try { return !!localStorage.getItem(TOKEN_KEY); } catch { return false; } };
export function clearSession() {
  try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); } catch { /* storage unavailable */ }
}
function readToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }

/** Human-readable reason for a failed request (timeout, HTTP status, network). */
export function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.message}${/^HTTP \d+$/.test(e.message) || e.status < 400 ? "" : ` (HTTP ${e.status})`}`;
  if (e instanceof DOMException && e.name === "TimeoutError") return "The request timed out.";
  if (e instanceof DOMException && e.name === "AbortError") return "The request was cancelled.";
  if (e instanceof TypeError) return "The server could not be reached (network error).";
  return e instanceof Error ? e.message : String(e);
}
/** True when an auth response means "no usable account API here" (proxy error page, static host, server
 *  error, wake-up) rather than "your input was wrong". Only 4xx responses with a JSON `detail` are user errors. */
export function serverUnavailable(status: number, body: Record<string, unknown> | null) {
  return status >= 500 || status === 404 || status === 405 || body === null || (status >= 400 && typeof body.detail !== "string" && !Array.isArray(body.detail));
}
export const isAbort = (e: unknown) => e instanceof DOMException && e.name === "AbortError";

function combineSignals(timeoutMs: number, signal?: AbortSignal | null): AbortSignal {
  const timeout = AbortSignal.timeout(timeoutMs);
  if (!signal) return timeout;
  if (typeof AbortSignal.any === "function") return AbortSignal.any([timeout, signal]);
  const ctrl = new AbortController();
  const forward = (s: AbortSignal) => () => ctrl.abort(s.reason);
  timeout.addEventListener("abort", forward(timeout)); signal.addEventListener("abort", forward(signal));
  if (signal.aborted) ctrl.abort(signal.reason);
  return ctrl.signal;
}

/** A 401 on a request that carried a token means the session ended: clear it and re-open sign-in. */
function handleUnauthorized(sentToken: string | null) {
  if (!sentToken || readToken() !== sentToken) return;
  clearSession();
  window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
  window.dispatchEvent(new CustomEvent(AUTH_CHANGED_EVENT));
}

async function request(path: string, init: RequestInit & { timeoutMs?: number }): Promise<Response> {
  const { timeoutMs = 25000, headers, signal, ...rest } = init;
  const token = readToken();
  const response = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: { ...(rest.body ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(headers || {}) },
    signal: combineSignals(timeoutMs, signal),
  });
  if (!response.ok) {
    if (response.status === 401) handleUnauthorized(token);
    let detail = `HTTP ${response.status}`;
    try { const body = await response.json(); if (typeof body.detail === "string") detail = body.detail; else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join("; "); } catch { /* not JSON */ }
    throw new ApiError(response.status, detail);
  }
  return response;
}

/** Fetch JSON from the API, sending the session token when present and surfacing the server's error text. */
export async function api<T>(path: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const response = await request(path, init);
  if (response.status === 204) return undefined as T;
  try { return await response.json() as T; }
  catch { throw new ApiError(response.status, "The server did not return API data (no research API is reachable at this address)"); }
}

/** Download an authenticated API response as a file (e.g. the personal data export). */
export async function download(path: string, fallbackName: string) {
  const response = await request(path, { timeoutMs: 60000 });
  const blob = await response.blob();
  const match = /filename="?([^";]+)"?/i.exec(response.headers.get("Content-Disposition") || "");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = match?.[1] || fallbackName;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function money(v: number | null | undefined, c = "USD") {
  if (v == null || !Number.isFinite(v)) return "—";
  try { return new Intl.NumberFormat("en-GB", { style: "currency", currency: c || "USD", maximumFractionDigits: 2 }).format(v); }
  catch { return v.toFixed(2); }
}
export const num = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("en-GB", { maximumFractionDigits: d }));
export const pct = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`);
/** Up/down colour class; null/undefined values get no colour. */
export const cls = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "" : v < 0 ? "down" : "up");
export const when = (epoch: number) => new Date(epoch * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
/** Today's date in the viewer's local time zone, as YYYY-MM-DD (comparable with <input type="date"> values). */
export function localToday(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// Neutral score bands instead of BUY/SELL wording: this is a research tool, not a recommendation service.
export function band(score: number) {
  if (score >= 85) return { label: "High score", cls: "b-high" };
  if (score >= 72) return { label: "Watch", cls: "b-watch" };
  if (score >= 60) return { label: "Neutral", cls: "b-neutral" };
  return { label: "Low score", cls: "b-low" };
}
export const statusCls = (s: string | null | undefined) => {
  switch ((s || "").toUpperCase()) {
    case "LIVE": return "st-live";
    case "DEMO": case "SEED": return "st-demo";
    case "PARTIAL": case "PARTIAL_LIVE": return "st-partial";
    case "UNAVAILABLE": return "st-unavail";
    case "USER": case "IDENTITY": return "st-user";
    default: return "st-off";
  }
};

export function Kpi({ title, value, sub }: { title: string; value: string; sub: string }) {
  return <div className="card kpi"><span>{title}</span><strong>{value}</strong><small>{sub}</small></div>;
}
export function Header({ title, eyebrow }: { title: string; eyebrow?: string }) {
  return <div className="card-header">{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h3>{title}</h3></div>;
}
export function Notice({ children }: { children: ReactNode }) {
  return <section className="card pad notbuilt"><p>{children}</p></section>;
}

export type ChartSeries = { name: string; values: (number | null)[]; color: string; dash?: string; width?: number; legend?: boolean };
export type ChartLevel = { value: number; label: string; color: string };
export type ChartBand = { upper: (number | null)[]; lower: (number | null)[]; color: string; name: string };

/** SVG line chart. Series may contain nulls (gaps, e.g. before a moving average starts).
 *  Optional horizontal levels (support/resistance) and a shaded band (trend channel). */
export function LineChartSvg({ series, labels, height = 220, levels = [], band }: { series: ChartSeries[]; labels: string[]; height?: number; levels?: ChartLevel[]; band?: ChartBand }) {
  const finite = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);
  const all = [...series.flatMap(s => s.values), ...levels.map(l => l.value), ...(band ? [...band.upper, ...band.lower] : [])].filter(finite);
  if (all.length < 2) return null;
  const w = 720, h = height, pad = 44, right = 64;
  const min = Math.min(...all), max = Math.max(...all), span = max - min || 1;
  const n = series[0].values.length;
  const x = (i: number) => pad + (i / Math.max(n - 1, 1)) * (w - pad - right);
  const y = (v: number) => 8 + (1 - (v - min) / span) * (h - 30);
  const segments = (vals: (number | null)[]) => {
    const out: string[] = []; let cur: string[] = [];
    vals.forEach((v, i) => { if (finite(v)) cur.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`); else if (cur.length) { out.push(cur.join(" ")); cur = []; } });
    if (cur.length) out.push(cur.join(" "));
    return out;
  };
  const bandPath = band ? (() => {
    const idx = band.upper.map((u, i) => (finite(u) && finite(band.lower[i]) ? i : -1)).filter(i => i >= 0);
    if (idx.length < 2) return null;
    return `M${idx.map(i => `${x(i).toFixed(1)},${y(band.upper[i] as number).toFixed(1)}`).join(" L")} L${[...idx].reverse().map(i => `${x(i).toFixed(1)},${y(band.lower[i] as number).toFixed(1)}`).join(" L")} Z`;
  })() : null;
  const ticks = [0, Math.floor(n / 2), n - 1];
  const legendItems = [...series.filter(s => s.legend !== false), ...(band ? [{ name: band.name, color: band.color, dash: undefined }] : [])];
  return <figure className="chartfig">
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Chart: ${series.map(s => s.name).join(", ")}${levels.length ? `; levels ${levels.map(l => l.label).join(", ")}` : ""}`}>
      {[0, 0.5, 1].map(f => <g key={f}><line x1={pad} x2={w - right} y1={8 + f * (h - 30)} y2={8 + f * (h - 30)} className="grid" /><text x={2} y={12 + f * (h - 30)} className="axis">{num(max - f * span, max - min < 10 ? 2 : 0)}</text></g>)}
      {bandPath && <path d={bandPath} fill={band!.color} opacity={0.07} stroke="none" />}
      {levels.map(l => <g key={l.label}><line x1={pad} x2={w - right} y1={y(l.value)} y2={y(l.value)} stroke={l.color} strokeWidth={1.4} strokeDasharray="6 4" /><text x={w - right + 4} y={y(l.value) + 4} className="axis" fill={l.color}>{num(l.value, 2)}</text></g>)}
      {series.map(s => segments(s.values).map((pts, k) => <polyline key={`${s.name}-${k}`} fill="none" stroke={s.color} strokeWidth={s.width ?? 2} strokeDasharray={s.dash} points={pts} />))}
      {ticks.map(i => <text key={i} x={Math.min(x(i), w - right - 60)} y={h - 4} className="axis">{labels[i]}</text>)}
    </svg>
    {(legendItems.length > 1 || levels.length > 0) && <figcaption>
      {legendItems.map(s => <span key={s.name}><i style={{ background: s.color }} className={s.dash ? "dashed" : ""} />{s.name}</span>)}
      {levels.some(l => l.label.startsWith("Support")) && <span><i className="dashed" style={{ background: "#22e0aa" }} />Support</span>}
      {levels.some(l => l.label.startsWith("Resistance")) && <span><i className="dashed" style={{ background: "#ff6b7a" }} />Resistance</span>}
    </figcaption>}
  </figure>;
}
