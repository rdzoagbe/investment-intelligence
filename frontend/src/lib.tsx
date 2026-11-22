import type { ReactNode } from "react";

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
// A static host (GitHub Pages) has no API server unless one is configured explicitly.
export const STATIC_HOST = !API_BASE && location.hostname.endsWith("github.io");
export const TOKEN_KEY = "ii_access_token";

export type Mode = { kind: "loading" } | { kind: "api" } | { kind: "demo"; reason: string };
export const signedIn = () => { try { return !!localStorage.getItem(TOKEN_KEY); } catch { return false; } };

export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }

/** Fetch JSON from the API, sending the session token when present and surfacing the server's error text. */
export async function api<T>(path: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const { timeoutMs = 25000, headers, ...rest } = init;
  let token: string | null = null;
  try { token = localStorage.getItem(TOKEN_KEY); } catch { /* storage unavailable */ }
  const response = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: { ...(rest.body ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(headers || {}) },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { const body = await response.json(); if (typeof body.detail === "string") detail = body.detail; else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join("; "); } catch { /* not JSON */ }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function money(v: number | null | undefined, c = "USD") {
  if (v == null || !Number.isFinite(v)) return "—";
  try { return new Intl.NumberFormat("en-GB", { style: "currency", currency: c || "USD", maximumFractionDigits: 2 }).format(v); }
  catch { return v.toFixed(2); }
}
export const num = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("en-GB", { maximumFractionDigits: d }));
export const pct = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`);
export const cls = (v: number | null | undefined) => ((v ?? 0) < 0 ? "down" : "up");
export const when = (epoch: number) => new Date(epoch * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

// Neutral score bands instead of BUY/SELL wording: this is a research tool, not a recommendation service.
export function band(score: number) {
  if (score >= 85) return { label: "High score", cls: "b-high" };
  if (score >= 72) return { label: "Watch", cls: "b-watch" };
  if (score >= 60) return { label: "Neutral", cls: "b-neutral" };
  return { label: "Low score", cls: "b-low" };
}
export const statusCls = (s: string) => (s === "LIVE" ? "st-live" : s === "DEMO" ? "st-demo" : "st-off");

export function Kpi({ title, value, sub }: { title: string; value: string; sub: string }) {
  return <div className="card kpi"><span>{title}</span><strong>{value}</strong><small>{sub}</small></div>;
}
export function Header({ title, eyebrow }: { title: string; eyebrow?: string }) {
  return <div className="card-header">{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h3>{title}</h3></div>;
}
export function Notice({ children }: { children: ReactNode }) {
  return <section className="card pad notbuilt"><p>{children}</p></section>;
}

/** Small SVG line chart. Each series must have the same length as `labels`. */
export function LineChartSvg({ series, labels, height = 220 }: { series: { name: string; values: number[]; color: string }[]; labels: string[]; height?: number }) {
  const all = series.flatMap(s => s.values).filter(Number.isFinite);
  if (all.length < 2) return null;
  const w = 720, h = height, pad = 34;
  const min = Math.min(...all), max = Math.max(...all), span = max - min || 1;
  const n = series[0].values.length;
  const x = (i: number) => pad + (i / Math.max(n - 1, 1)) * (w - pad - 8);
  const y = (v: number) => 8 + (1 - (v - min) / span) * (h - 30);
  const ticks = [0, Math.floor(n / 2), n - 1];
  return <figure className="chartfig">
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={series.map(s => s.name).join(" vs ")}>
      {[0, 0.5, 1].map(f => <g key={f}><line x1={pad} x2={w - 8} y1={8 + f * (h - 30)} y2={8 + f * (h - 30)} className="grid" /><text x={2} y={12 + f * (h - 30)} className="axis">{num(max - f * span, 0)}</text></g>)}
      {series.map(s => <polyline key={s.name} fill="none" stroke={s.color} strokeWidth={2} points={s.values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} />)}
      {ticks.map(i => <text key={i} x={Math.min(x(i), w - 70)} y={h - 4} className="axis">{labels[i]}</text>)}
    </svg>
    {series.length > 1 && <figcaption>{series.map(s => <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>)}</figcaption>}
  </figure>;
}
