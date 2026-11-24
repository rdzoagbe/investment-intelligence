import { StrictMode, useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { Bell, BookOpen, BrainCircuit, Sparkles, Trophy, CircleDollarSign, Database, Home, LineChart, Newspaper, Search, Settings as SettingsIcon, ShieldAlert, Users, WalletCards, X } from "lucide-react";
import demoSnapshot from "./demo-snapshot.json";
import { AlertsPage, AssistantPage, TrackRecordPage } from "./insight-pages";
import { BacktestPage, JournalPage, MyPortfolioPage, PaperTradingPage, PriceHistoryPanel, SaveToJournal } from "./account-pages";
import { API_BASE, AUTH_CHANGED_EVENT, SAVED_VIEW_KEY, STATIC_HOST, api, band, clearSession, cls, describeError, download, Header, isAbort, Kpi, money, num, pct, signedIn, statusCls, when, type Mode } from "./lib";
import { LegalPage } from "./legal-pages";
import "./styles.css";

// ---------- Types (mirror the FastAPI payloads) ----------
type ScanItem = {
  symbol: string; name: string; market: string; currency: string; price: number | null; change_pct: number | null;
  score: number; verdict: string; band?: string; breakdown: Record<string, number>;
  fundamental_inputs: { revenue_growth_pct: number; operating_margin_pct: number; free_cash_flow_margin_pct: number; source: string; status: string; field_sources?: Record<string, string> };
  macro_sensitivity: string; price_source: string; price_status: string;
  market_inputs?: { pe_ratio: number; pe_source: string; momentum_source: string; sentiment_source: string; balance_sheet_source?: string };
};
type Scenario = { label: string; growth_pct: number; multiple: number; fair_value: number; upside_pct: number };
type Analysis = ScanItem & {
  thesis: { bull: string[]; bear: string[]; invalidation: string; market_question: string };
  valuation: { scenarios: Scenario[] };
  risk: { risk_budget: number; shares: number; position_value: number; position_weight_pct: number; model_account_value: number; stop_loss_pct: number; note: string };
  data_status: string;
};
type Committee = { symbol: string; score: number; confidence: number; bull_case: string[]; bear_case: string[]; approval_state: string; execution: string; decision_question: string; timestamp: string; analysis?: string; model_provider?: string };
type Macro = { regime: string; label?: string; status?: string; drivers: { name: string; direction: string; impact: string; note: string }[]; disclaimer: string };
type MarketRow = { name: string; symbol: string; value: number | null; change_pct: number | null; status: string };
type Portfolio = { value: number; invested: number; cash: number; cash_pct: number; pnl: number; return_pct: number; allocation: { symbol: string; value: number; weight_pct: number; pnl_pct: number }[]; risk_flags: string[]; source: string; notice: string };
type Risk = { volatility_pct: number | null; sharpe: number | null; max_drawdown_pct: number | null; source: string; notice: string };
type NewsItem = { title: string; summary: string; source: string };
type Status = Record<string, Record<string, unknown>>;
type Dashboard = { markets: MarketRow[]; macro: Macro; data_status?: string };
type Page = "Command Center" | "AI Assistant" | "Alerts" | "Track Record" | "Opportunity Scanner" | "Investment Committee" | "Portfolio" | "Market Intelligence" | "Investment Journal" | "Backtesting" | "Paper Trading" | "Broker Integration" | "Settings" | "Terms" | "Privacy" | "Risk disclosure";

const snapshot = demoSnapshot as unknown as { notice: string; scanner: ScanItem[]; analyses: Record<string, { analysis: Analysis; committee: Committee }>; macro: Macro; portfolio: Portfolio; risk: Risk };
// ---------- App ----------
function App() {
  const [mode, setMode] = useState<Mode>({ kind: "loading" });
  const [page, setPage] = useState<Page>("Command Center");
  const [scan, setScan] = useState<ScanItem[]>([]);
  const [markets, setMarkets] = useState<MarketRow[] | null>(null);
  const [macro, setMacro] = useState<Macro | null>(null);
  const [dash, setDash] = useState<{ status?: string; error?: string }>({});
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [unread, setUnread] = useState(0);
  const [authTick, setAuthTick] = useState(0);
  const probeId = useRef(0);
  // Last successful view, kept in this browser so the page is usable while a free server wakes up.
  const [saved] = useState<SavedView | null>(readSavedView);

  // Sign-in, sign-out and session expiry (auth-bootstrap.ts / lib.api) re-render account-dependent views.
  useEffect(() => {
    const onAuth = () => setAuthTick(t => t + 1);
    window.addEventListener(AUTH_CHANGED_EVENT, onAuth);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, onAuth);
  }, []);

  useEffect(() => {
    if (mode.kind !== "api" || !signedIn()) { setUnread(0); return; }
    const ctrl = new AbortController();
    api<{ events: { is_read: number }[] }>("/api/me/alerts", { signal: ctrl.signal }).then(d => setUnread(d.events.filter(e => !e.is_read).length)).catch(() => undefined);
    return () => ctrl.abort();
  }, [mode.kind, authTick]);

  const probe = useCallback(() => {
    const id = ++probeId.current;
    const current = () => id === probeId.current;
    const useDemo = (reason: string) => { if (!current()) return; setScan(snapshot.scanner); setMacro(snapshot.macro); setMarkets(null); setDash({}); setMode({ kind: "demo", reason }); };
    if (STATIC_HOST) { useDemo("This static site has no API server attached."); return; }
    // The scanner alone decides API vs demo mode; benchmarks (/api/dashboard) load separately so their
    // failure only marks benchmarks unavailable instead of hiding the working API and account features.
    api<{ items: ScanItem[] }>("/api/scanner?limit=100", { timeoutMs: 60000 })
      .then(s => {
        if (!current()) return;
        setScan(s.items); setMode({ kind: "api" });
        writeSavedView({ saved_at: Date.now(), scan: s.items });
        api<Dashboard>("/api/dashboard", { timeoutMs: 60000 })
          .then(d => { if (current()) { setMarkets(d.markets); setMacro(d.macro); setDash({ status: d.data_status }); } })
          .catch(e => {
            if (!current()) return;
            setMarkets(null); setDash({ error: describeError(e) });
            api<Macro>("/api/intelligence/macro").then(m => { if (current()) setMacro(m); }).catch(() => undefined);
          });
      })
      .catch(e => useDemo(`The research API could not be used: ${describeError(e)}`));
  }, []);
  useEffect(probe, [probe]);
  // A successful sign-in after a failed first probe (e.g. a server cold start) re-detects API mode.
  useEffect(() => { if (authTick > 0 && mode.kind === "demo" && !STATIC_HOST) probe(); }, [authTick]);

  const filtered = useMemo(() => scan.filter(a => `${a.symbol} ${a.name} ${a.market}`.toLowerCase().includes(search.trim().toLowerCase())), [scan, search]);
  const nav = (x: Page, icon: ReactNode, badge = 0) => <button className={`nav-item ${page === x ? "active" : ""}`} aria-current={page === x ? "page" : undefined} onClick={() => setPage(x)}>{icon}<span>{x}</span>{badge > 0 && <em className="count" aria-label={`${badge} unread`}>{badge}</em>}</button>;
  const legalLink = (x: Page, label: string) => <button type="button" className="linklike" onClick={() => { setPage(x); window.scrollTo(0, 0); }}>{label}</button>;

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><BrainCircuit size={28} aria-hidden="true" /><div><strong>INVESTMENT INTELLIGENCE</strong><span>Research. Challenge. Decide.</span></div></div>
      <nav>{nav("Command Center", <Home size={16} />)}{nav("AI Assistant", <Sparkles size={16} />)}{nav("Alerts", <Bell size={16} />, unread)}{nav("Opportunity Scanner", <Search size={16} />)}{nav("Investment Committee", <Users size={16} />)}{nav("Portfolio", <WalletCards size={16} />)}{nav("Market Intelligence", <Newspaper size={16} />)}{nav("Investment Journal", <BookOpen size={16} />)}{nav("Track Record", <Trophy size={16} />)}</nav>
      <div className="tools"><span>TOOLS</span>{nav("Backtesting", <LineChart size={16} />)}{nav("Paper Trading", <CircleDollarSign size={16} />)}{nav("Broker Integration", <ShieldAlert size={16} />)}{nav("Settings", <SettingsIcon size={16} />)}</div>
    </aside>
    <main className="main">
      <header className="topbar">
        <div className="searchbox"><Search size={16} aria-hidden="true" /><input aria-label="Filter research universe" value={search} onChange={e => { setSearch(e.target.value); if (page !== "Opportunity Scanner" && page !== "Command Center") setPage("Opportunity Scanner"); }} placeholder="Filter the research universe by name, ticker or market…" /></div>
      </header>
      <ModeBanner mode={mode} dash={dash} />
      <div className="workspace">
        <div className="primary">
          <div className="page-heading"><h1>{page}</h1><span className="today">{new Date().toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" })}</span></div>
          {mode.kind === "loading" && !LEGAL_PAGES.includes(page) ? <>
            <div className="card pad">Connecting to the research API… A free-tier server can take up to a minute to wake up.</div>
            {saved && (page === "Command Center" || page === "Opportunity Scanner") && <SavedViewPanel saved={saved} search={search} />}
          </> :
            <PageBody key={authTick} page={page} mode={mode} universe={scan} filtered={filtered} search={search} markets={markets} dashError={dash.error} macro={macro} onOpen={setSelected} onUnread={setUnread} onNavigate={setPage} />}
        </div>
        <aside className="rightbar"><SourcesPanel mode={mode} scan={scan} /><MacroPanel macro={macro} /><Disclaimer /></aside>
      </div>
      <footer className="footer">Research and education tool. Not investment advice, not a broker, and no orders are placed from this site. Scores are model outputs from stated inputs and can be wrong.
        <nav className="legal-links" aria-label="Legal">{legalLink("Terms", "Terms")} · {legalLink("Privacy", "Privacy notice")} · {legalLink("Risk disclosure", "Risk disclosure")} <span className="tiny">(drafts)</span></nav>
      </footer>
    </main>
    {selected && <AssetModal symbol={selected} mode={mode} onClose={() => setSelected(null)} />}
  </div>;
}

const LEGAL_PAGES: Page[] = ["Terms", "Privacy", "Risk disclosure"];

// ---------- Saved copy shown while the server wakes up ----------
type SavedView = { saved_at: number; scan: ScanItem[] };
const SAVED_MAX_AGE_MS = 24 * 3600 * 1000;
function readSavedView(): SavedView | null {
  if (!signedIn()) return null;
  try {
    const v = JSON.parse(localStorage.getItem(SAVED_VIEW_KEY) || "null") as SavedView | null;
    if (!v || typeof v.saved_at !== "number" || !Array.isArray(v.scan) || !v.scan.length) return null;
    return Date.now() - v.saved_at < SAVED_MAX_AGE_MS ? v : null;
  } catch { return null; }
}
function writeSavedView(v: SavedView) {
  // Only for signed-in users, and cleared on sign-out (lib.clearSession).
  if (!signedIn()) return;
  try { localStorage.setItem(SAVED_VIEW_KEY, JSON.stringify(v)); } catch { /* storage unavailable or full */ }
}
function SavedViewPanel({ saved, search }: { saved: SavedView; search: string }) {
  const q = search.trim().toLowerCase();
  const rows = saved.scan.filter(a => `${a.symbol} ${a.name} ${a.market}`.toLowerCase().includes(q));
  return <section className="card pad">
    <div className="banner warn inline"><Database size={15} aria-hidden="true" /> <span><b>Saved copy from {when(Math.floor(saved.saved_at / 1000))} — not current.</b> Shown from this browser while the server wakes up. It is replaced automatically by fresh figures; do not use it for decisions.</span></div>
    <Scanner scan={rows} total={saved.scan.length} onOpen={() => undefined} />
  </section>;
}

/** Accessible modal: dialog semantics, focus moved in and trapped, Escape closes, focus returns to the opener. */
function AssetModal({ symbol, mode, onClose }: { symbol: string; mode: Mode; onClose: () => void }) {
  const card = useRef<HTMLDivElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const titleId = `asset-modal-title-${symbol.replace(/[^A-Za-z0-9_-]/g, "_")}`;
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  // Runs once per opening (not on every parent render) so focus is not stolen back to the close button.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeBtn.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      // The sign-in gate (session expired) sits above the modal: leave its keyboard handling alone.
      if (document.getElementById("ii-auth-gate")) return;
      if (e.key === "Escape") { e.preventDefault(); closeRef.current(); return; }
      if (e.key !== "Tab" || !card.current) return;
      const items = [...card.current.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter(el => el.offsetParent !== null || el === document.activeElement);
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (!card.current.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
      else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); if (opener && document.contains(opener)) opener.focus(); };
  }, []);
  return <div className="modal" onClick={onClose}>
    <div className="modal-card" ref={card} role="dialog" aria-modal="true" aria-labelledby={titleId} onClick={e => e.stopPropagation()}>
      <button ref={closeBtn} className="modal-close" aria-label="Close asset details" onClick={onClose}><X aria-hidden="true" /></button>
      <AssetDetail symbol={symbol} mode={mode} titleId={titleId} />
    </div>
  </div>;
}

function ModeBanner({ mode, dash }: { mode: Mode; dash: { status?: string; error?: string } }) {
  if (mode.kind === "api") return <>
    <div className="banner ok"><Database size={15} aria-hidden="true" /> Connected to the research API. Each figure shows its source and whether it is LIVE or DEMO.</div>
    {dash.status === "PARTIAL_LIVE" && <div className="banner warn"><Database size={15} aria-hidden="true" /> <span><b>Partly live.</b> Some quotes could not be retrieved live; those assets use labelled DEMO values. Check each status badge.</span></div>}
    {dash.status === "DEMO_DATASET" && <div className="banner warn"><Database size={15} aria-hidden="true" /> <span><b>No live quotes right now.</b> Prices shown are labelled DEMO values and must not be used for decisions.</span></div>}
    {dash.error && <div className="banner warn"><Database size={15} aria-hidden="true" /> <span><b>Benchmarks unavailable.</b> {dash.error}</span></div>}
  </>;
  if (mode.kind === "demo") return <div className="banner warn"><Database size={15} aria-hidden="true" /> <span><b>Demo dataset.</b> {mode.reason} You are viewing bundled illustrative data: prices, ratios and scores are <b>not live</b> and must not be used for decisions.</span></div>;
  return null;
}

type BodyProps = { page: Page; mode: Mode; universe: ScanItem[]; filtered: ScanItem[]; search: string; markets: MarketRow[] | null; dashError?: string; macro: Macro | null; onOpen: (s: string) => void; onUnread: (n: number) => void; onNavigate: (p: Page) => void };
function PageBody({ page, mode, universe, filtered, search, markets, dashError, macro, onOpen, onUnread, onNavigate }: BodyProps) {
  // Only the scanner and the Command Center table follow the top-bar filter. Account forms always get the
  // full universe so a search can never hide or substitute the asset being submitted.
  switch (page) {
    case "AI Assistant": return <AssistantPage mode={mode} />;
    case "Alerts": return <AlertsPage mode={mode} assets={universe} onUnread={onUnread} />;
    case "Track Record": return <TrackRecordPage mode={mode} />;
    case "Command Center": return <CommandCenter mode={mode} universe={universe} rows={filtered} search={search} markets={markets} dashError={dashError} onOpen={onOpen} />;
    case "Opportunity Scanner": return <Scanner scan={filtered} total={universe.length} onOpen={onOpen} />;
    case "Investment Committee": return <CommitteePage mode={mode} scan={universe} />;
    case "Portfolio": return mode.kind === "api" && signedIn() ? <MyPortfolioPage assets={universe} /> : <PortfolioPage mode={mode} />;
    case "Market Intelligence": return <IntelligencePage mode={mode} macro={macro} />;
    case "Paper Trading": return <PaperTradingPage mode={mode} assets={universe} />;
    case "Settings": return <SettingsPage mode={mode} onNavigate={onNavigate} />;
    case "Investment Journal": return <JournalPage mode={mode} assets={universe} />;
    case "Backtesting": return <BacktestPage mode={mode} assets={universe} />;
    case "Terms": return <LegalPage doc="terms" />;
    case "Privacy": return <LegalPage doc="privacy" />;
    case "Risk disclosure": return <LegalPage doc="risk" />;
    case "Broker Integration": return <NotBuilt title="Broker Integration" text="Live trading is disabled. An optional Alpaca paper-trading (simulated) connection exists in the API and every order requires explicit human approval. Real-money execution would require a licensed broker and legal review." />;
  }
}

// ---------- Command Center ----------
function CommandCenter({ mode, universe, rows, search, markets, dashError, onOpen }: { mode: Mode; universe: ScanItem[]; rows: ScanItem[]; search: string; markets: MarketRow[] | null; dashError?: string; onOpen: (s: string) => void }) {
  // KPIs describe the whole research universe; only the ranked table follows the top-bar filter.
  const live = universe.filter(a => a.price_status === "LIVE").length;
  const best = [...universe].sort((a, b) => b.score - a.score)[0];
  const top = [...rows].sort((a, b) => b.score - a.score);
  const filtering = search.trim() !== "";
  return <>
    <section className="kpis">
      <Kpi title="Research universe" value={`${universe.length} assets`} sub="US, European and Ghana equities" />
      <Kpi title="Live price coverage" value={`${live} / ${universe.length}`} sub={live ? "Quotes from Yahoo Finance" : "No live quotes in this view"} />
      <Kpi title="Highest model score" value={best ? `${best.score}` : "—"} sub={best ? `${best.name} (${best.symbol})` : ""} />
      <Kpi title="Data mode" value={mode.kind === "api" ? "API" : "DEMO"} sub={mode.kind === "api" ? "Server-side calculations" : "Bundled illustrative snapshot"} />
    </section>
    <section className="card pad">
      <Header title="Market benchmarks" eyebrow="LIVE WHEN AVAILABLE · NO FALLBACK VALUES" />
      {markets ? <div className="ticker-row">{markets.map(m => <div className="ticker" key={m.symbol}><span>{m.name}</span><strong>{m.value == null ? "Unavailable" : num(m.value)}</strong><em className={cls(m.change_pct)}>{pct(m.change_pct)}</em></div>)}</div>
        : <p className="muted">{mode.kind === "api" ? `Benchmarks unavailable${dashError ? `: ${dashError}` : " right now"}. No fallback values are shown.` : "Benchmark quotes are only shown when the API retrieves them live. None are displayed in demo mode."}</p>}
    </section>
    <section className="card pad">
      <Header title="Highest-scoring assets" eyebrow={filtering ? `FILTERED: ${rows.length} OF ${universe.length} ASSETS MATCH "${search.trim().toUpperCase()}"` : "RANKED BY THE TRANSPARENT FACTOR MODEL"} />
      <ScanTable rows={top.slice(0, 8)} onOpen={onOpen} />
    </section>
    {top[0] && <section className="card pad"><AssetDetail symbol={top[0].symbol} mode={mode} /></section>}
  </>;
}

function ScanTable({ rows, onOpen }: { rows: ScanItem[]; onOpen: (s: string) => void }) {
  if (!rows.length) return <p className="muted">No assets match this filter.</p>;
  return <div className="table-wrap"><table className="table">
    <thead><tr><th>Asset</th><th>Market</th><th className="r">Price</th><th className="r">Day</th><th className="r">Score</th><th>Band</th><th>Price data</th></tr></thead>
    <tbody>{rows.map(a => { const b = band(a.score); return <tr key={a.symbol} onClick={() => onOpen(a.symbol)} tabIndex={0} aria-label={`Open ${a.name} (${a.symbol}) details`} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(a.symbol); } }}>
      <td><b>{a.name}</b><small>{a.symbol}</small></td><td>{a.market}</td><td className="r">{money(a.price, a.currency)}</td>
      <td className={`r ${cls(a.change_pct)}`}>{pct(a.change_pct)}</td><td className="r"><b>{a.score.toFixed(1)}</b></td>
      <td><span className={`badge ${b.cls}`}>{a.band ?? b.label}</span></td><td><span className={`badge ${statusCls(a.price_status)}`}>{a.price_status}</span></td></tr>; })}</tbody>
  </table></div>;
}

// ---------- Asset detail ----------
function useAnalysis(symbol: string, mode: Mode) {
  const [state, setState] = useState<{ symbol?: string; data?: Analysis; error?: string }>({});
  useEffect(() => {
    setState({});
    if (mode.kind !== "api") { const hit = snapshot.analyses[symbol]; setState(hit ? { symbol, data: hit.analysis } : { symbol, error: "Not in the demo dataset." }); return; }
    // Abort on symbol change so a slower response for a previous asset can never replace this one.
    const ctrl = new AbortController();
    api<Analysis>(`/api/assets/${encodeURIComponent(symbol)}/analysis`, { signal: ctrl.signal })
      .then(data => { if (!ctrl.signal.aborted) setState({ symbol, data }); })
      .catch(e => { if (!ctrl.signal.aborted && !isAbort(e)) setState({ symbol, error: describeError(e) }); });
    return () => ctrl.abort();
  }, [symbol, mode.kind]);
  return state.symbol === symbol ? state : {};
}

const FIELD_LABELS: Record<string, string> = { revenue_growth_pct: "Revenue growth", operating_margin_pct: "Operating margin", free_cash_flow_margin_pct: "FCF margin" };

function AssetDetail({ symbol, mode, titleId }: { symbol: string; mode: Mode; titleId?: string }) {
  const { data: a, error } = useAnalysis(symbol, mode);
  if (error) return <p className="muted" id={titleId}>Analysis unavailable for {symbol}: {error}</p>;
  if (!a) return <p className="muted" id={titleId}>Loading analysis for {symbol}…</p>;
  const b = band(a.score);
  const fieldSources = a.fundamental_inputs.field_sources;
  return <div className="detail">
    <div className="detail-head">
      <div><span className="eyebrow">ASSET RESEARCH</span><h2 id={titleId}>{a.name} <small>({a.symbol})</small></h2><p className="muted">{a.market} · {a.currency} · macro sensitivity {a.macro_sensitivity}</p></div>
      <div className="price"><strong>{money(a.price, a.currency)}</strong><em className={cls(a.change_pct)}>{a.change_pct == null ? "Day change unavailable" : pct(a.change_pct)}</em><span className={`badge ${statusCls(a.price_status)}`}>{a.price_status}</span><small>{a.price_source}</small></div>
    </div>
    <div className="detail-grid">
      <div className="box">
        <h4>Model score</h4>
        <div className="score"><b>{a.score.toFixed(1)}</b><span>/100</span></div>
        <span className={`badge ${b.cls}`}>{a.band ?? b.label}</span>
        <div className="bars">{Object.entries(a.breakdown).map(([k, v]) => <div key={k}><span>{k.replace(/_/g, " ")}</span><i><em style={{ width: `${v}%` }} /></i><b>{v}</b></div>)}</div>
        <p className="tiny">Weights: fundamental 24%, growth 18%, cash flow 16%, valuation 14%, balance sheet 12%, momentum 9%, sentiment 7%.</p>
        <ul className="inputs">
          <li><span>Fundamentals</span><b>{a.fundamental_inputs.source}</b> <span className={`badge ${statusCls(a.fundamental_inputs.status)}`}>{a.fundamental_inputs.status}</span></li>
          {fieldSources && Object.entries(fieldSources).map(([k, v]) => <li key={k} className="sub"><span>{FIELD_LABELS[k] ?? k.replace(/_/g, " ")}</span><b>{v}</b></li>)}
          {a.market_inputs && <><li><span>P/E {num(a.market_inputs.pe_ratio, 1)}</span><b>{a.market_inputs.pe_source}</b></li>
          <li><span>Momentum</span><b>{a.market_inputs.momentum_source}</b></li><li><span>Sentiment</span><b>{a.market_inputs.sentiment_source}</b></li>
          {a.market_inputs.balance_sheet_source && <li><span>Balance sheet</span><b>{a.market_inputs.balance_sheet_source}</b></li>}</>}
        </ul>
      </div>
      <div className="box">
        <h4>Bull case</h4><ul className="list good">{a.thesis.bull.map(x => <li key={x}>{x}</li>)}</ul>
        <h4>Bear case</h4><ul className="list bad">{a.thesis.bear.map(x => <li key={x}>{x}</li>)}</ul>
        <h4>What would invalidate it</h4><p className="small">{a.thesis.invalidation}</p>
        <p className="question">“{a.thesis.market_question}”</p>
      </div>
      <div className="box">
        <h4>Valuation scenarios</h4>
        <table className="table compact"><thead><tr><th>Case</th><th className="r">Growth</th><th className="r">Multiple</th><th className="r">Value</th><th className="r">vs price</th></tr></thead>
          <tbody>{a.valuation.scenarios.map(s => <tr key={s.label}><td>{s.label}</td><td className="r">{s.growth_pct}%</td><td className="r">{s.multiple}x</td><td className="r">{money(s.fair_value, a.currency)}</td><td className={`r ${cls(s.upside_pct)}`}>{pct(s.upside_pct)}</td></tr>)}</tbody></table>
        <p className="tiny">Simple scenario scaffold from the stated growth and P/E inputs. It is not a price target.</p>
        <h4>Position-sizing illustration</h4>
        <p className="small">On a {money(a.risk.model_account_value, a.currency)} model account risking 1% with an {a.risk.stop_loss_pct}% stop: about {num(a.risk.shares, 2)} shares ({num(a.risk.position_weight_pct, 1)}% of the account).</p>
        <p className="tiny">{a.risk.note}</p>
      </div>
      <PriceHistoryPanel symbol={a.symbol} mode={mode} />
    </div>
    <SaveToJournal symbol={a.symbol} mode={mode} />
  </div>;
}

// ---------- Pages ----------
function Scanner({ scan, total, onOpen }: { scan: ScanItem[]; total: number; onOpen: (s: string) => void }) {
  const [market, setMarket] = useState(""); const [min, setMin] = useState(0);
  const markets = [...new Set(scan.map(a => a.market))].sort();
  const rows = scan.filter(a => (!market || a.market === market) && a.score >= min).sort((a, b) => b.score - a.score);
  return <section className="card pad">
    <div className="filters">
      <label>Market <select value={market} onChange={e => setMarket(e.target.value)}><option value="">All markets</option>{markets.map(m => <option key={m}>{m}</option>)}</select></label>
      <label>Minimum score <input type="number" min={0} max={100} value={min} onChange={e => setMin(Number(e.target.value) || 0)} /></label>
      <span className="muted">{rows.length} of {total} assets</span>
    </div>
    <ScanTable rows={rows} onOpen={onOpen} />
  </section>;
}

function CommitteePage({ mode, scan }: { mode: Mode; scan: ScanItem[] }) {
  const [picked, setSymbol] = useState(scan[0]?.symbol ?? "");
  // Never fall back to a hidden default symbol: use the selection only if it is in the list.
  const symbol = scan.some(a => a.symbol === picked) ? picked : (scan[0]?.symbol ?? "");
  const [c, setC] = useState<{ symbol?: string; data?: Committee; error?: string }>({});
  useEffect(() => {
    setC({});
    if (!symbol) return;
    if (mode.kind !== "api") { const hit = snapshot.analyses[symbol]; setC(hit ? { symbol, data: hit.committee } : { symbol, error: "Not in the demo dataset." }); return; }
    const ctrl = new AbortController();
    api<Committee>(`/api/assets/${encodeURIComponent(symbol)}/committee`, { signal: ctrl.signal })
      .then(data => { if (!ctrl.signal.aborted) setC({ symbol, data }); })
      .catch(e => { if (!ctrl.signal.aborted && !isAbort(e)) setC({ symbol, error: describeError(e) }); });
    return () => ctrl.abort();
  }, [symbol, mode.kind]);
  const cur = c.symbol === symbol ? c : {};
  if (!scan.length) return <section className="card pad muted">No assets are available to review.</section>;
  return <section className="card pad">
    <div className="filters"><label>Asset <select value={symbol} onChange={e => setSymbol(e.target.value)}>{[...scan].sort((a, b) => a.name.localeCompare(b.name)).map(a => <option key={a.symbol} value={a.symbol}>{a.name} ({a.symbol})</option>)}</select></label></div>
    {cur.error && <p className="muted">Committee packet unavailable: {cur.error}</p>}
    {!cur.data && !cur.error && <p className="muted">Loading…</p>}
    {cur.data && <div className="committee">
      <div className="kpis three"><Kpi title="Model score" value={cur.data.score.toFixed(1)} sub={band(cur.data.score).label} /><Kpi title="Signal strength (heuristic)" value={`${cur.data.confidence}`} sub="Distance of the score from neutral, not a probability" /><Kpi title="Decision state" value="Human decision" sub="No automatic execution" /></div>
      {cur.data.analysis ? <div className="box"><h4>AI synthesis ({cur.data.model_provider})</h4><p className="small pre">{cur.data.analysis}</p></div> :
        <div className="two"><div className="box"><h4>Arguments for</h4><ul className="list good">{cur.data.bull_case.map(x => <li key={x}>{x}</li>)}</ul></div><div className="box"><h4>Arguments against</h4><ul className="list bad">{cur.data.bear_case.map(x => <li key={x}>{x}</li>)}</ul></div></div>}
      <p className="question">Challenge: “{cur.data.decision_question}”</p>
      <p className="tiny">Generated {new Date(cur.data.timestamp).toLocaleString("en-GB")}. {cur.data.analysis ? "Model-written text is a synthesis of the supplied facts only." : "Rule-based packet."}</p>
    </div>}
  </section>;
}

function useEndpoint<T>(path: string, mode: Mode, demo?: T) {
  const [s, setS] = useState<{ data?: T; error?: string }>({});
  useEffect(() => {
    if (mode.kind !== "api") { setS(demo ? { data: demo } : { error: "Requires the API server (not available on the static demo)." }); return; }
    const ctrl = new AbortController();
    setS({});
    api<T>(path, { signal: ctrl.signal })
      .then(data => { if (!ctrl.signal.aborted) setS({ data }); })
      .catch(e => { if (!ctrl.signal.aborted && !isAbort(e)) setS({ error: describeError(e) }); });
    return () => ctrl.abort();
  }, [path, mode.kind]);
  return s;
}

function PortfolioPage({ mode }: { mode: Mode }) {
  const p = useEndpoint<Portfolio>("/api/portfolio", mode, snapshot.portfolio);
  const r = useEndpoint<Risk>("/api/risk", mode, snapshot.risk);
  if (!p.data) return <section className="card pad muted">{p.error ?? "Loading…"}</section>;
  return <section className="card pad">
    <div className="banner warn inline"><b>Sample portfolio.</b> {p.data.notice} {mode.kind === "api" ? "Sign in to track your own holdings." : ""}</div>
    <div className="kpis"><Kpi title="Value" value={num(p.data.value)} sub="Mixed currencies, unconverted" /><Kpi title="P&L" value={num(p.data.pnl)} sub={pct(p.data.return_pct)} /><Kpi title="Cash" value={`${p.data.cash_pct}%`} sub={num(p.data.cash)} /><Kpi title="Risk flags" value={p.data.risk_flags.length ? p.data.risk_flags.join(", ") : "None"} sub="Concentration > 35%, cash < 5%" /></div>
    <h4>Allocation</h4>
    <div className="bars wide">{p.data.allocation.map(x => <div key={x.symbol}><span>{x.symbol}</span><i><em style={{ width: `${x.weight_pct}%` }} /></i><b>{x.weight_pct}%</b></div>)}</div>
    {r.data && <><h4>Risk metrics</h4><p className="small">Volatility {num(r.data.volatility_pct)}% · Sharpe {num(r.data.sharpe)} · Max drawdown {num(r.data.max_drawdown_pct)}%</p><p className="tiny">{r.data.notice}</p></>}
  </section>;
}

function IntelligencePage({ mode, macro }: { mode: Mode; macro: Macro | null }) {
  const n = useEndpoint<{ items: NewsItem[]; status: string }>("/api/intelligence/news", mode);
  return <>
    <section className="card pad"><Header title="Headlines" eyebrow="RSS FEEDS · SOURCE LINKED" />
      {n.error && <p className="muted">{n.error}</p>}{!n.data && !n.error && <p className="muted">Loading…</p>}
      {n.data && (n.data.items.length ? <ul className="news">{n.data.items.map(i => <li key={i.title + i.source}><a href={i.source.startsWith("http") ? i.source : undefined} target="_blank" rel="noreferrer noopener">{i.title}</a>{i.summary && <p>{i.summary}</p>}</li>)}</ul> : <p className="muted">No headlines could be retrieved from the feeds right now.</p>)}
    </section>
    {macro && <section className="card pad"><Header title={macro.label ?? "Macro context notes"} eyebrow="STATIC NOTES · NOT COMPUTED FROM DATA" /><MacroList macro={macro} /></section>}
  </>;
}

const CONFIG_LABELS: Record<string, string> = { anthropic_api_key: "AI assistant key (ANTHROPIC_API_KEY)", sec_user_agent: "SEC EDGAR identity (SEC_USER_AGENT)", job_token: "Daily job token (JOB_TOKEN)", tiingo_api_key: "US market data key (TIINGO_API_KEY)" };

function SettingsPage({ mode, onNavigate }: { mode: Mode; onNavigate: (p: Page) => void }) {
  const s = useEndpoint<Status>("/api/status", mode);
  const db = s.data?.database as { ok?: boolean; engine?: string } | undefined;
  const config = s.data?.config as Record<string, string> | undefined;
  const rest = s.data ? Object.entries(s.data).filter(([k]) => k !== "database" && k !== "config") : [];
  return <>
    {mode.kind === "api" && signedIn() && <AccountData />}
    <section className="card pad"><Header title="Server status" eyebrow="NO SECRET VALUES ARE EVER SHOWN" />
      <p className="small">API base: <code>{API_BASE || (STATIC_HOST ? "none (static site)" : "same origin")}</code></p>
      {s.error && <p className="muted">{s.error}</p>}
      {db && <p className="small">Database: <span className={`badge ${db.ok ? "st-live" : "st-unavail"}`}>{db.ok ? "REACHABLE" : "UNREACHABLE"}</span> {db.engine ?? "unknown engine"}</p>}
      {config && <ul className="inputs">{Object.entries(config).map(([k, v]) => <li key={k}><span>{CONFIG_LABELS[k] ?? k}</span><span className={`badge ${v === "set" ? "st-live" : "st-off"}`}>{v.toUpperCase()}</span></li>)}</ul>}
      {rest.length > 0 && <table className="table compact"><tbody>{rest.map(([k, v]) => <tr key={k}><td><b>{k.replace(/_/g, " ")}</b></td><td>{v && typeof v === "object" ? Object.entries(v).map(([kk, vv]) => `${kk}: ${String(vv)}`).join(" · ") : String(v)}</td></tr>)}</tbody></table>}
    </section>
    <section className="card pad"><Header title="Legal documents" eyebrow="DRAFTS · NOT LEGAL ADVICE" />
      <div className="row"><button className="btn small" onClick={() => onNavigate("Terms")}>Terms</button><button className="btn small" onClick={() => onNavigate("Privacy")}>Privacy notice</button><button className="btn small" onClick={() => onNavigate("Risk disclosure")}>Risk disclosure</button></div>
    </section>
  </>;
}

/** Export and delete personal data (GDPR-style rights described in the privacy notice). */
function AccountData() {
  const [exportState, setExportState] = useState<{ busy?: boolean; msg?: string; err?: string }>({});
  const [password, setPassword] = useState(""); const [confirm, setConfirm] = useState(false);
  const [del, setDel] = useState<{ busy?: boolean; err?: string }>({});
  const [accountId, setAccountId] = useState<number | null>(null);
  useEffect(() => {
    const ctrl = new AbortController();
    api<{ id: number }>("/api/auth/me", { signal: ctrl.signal }).then(u => setAccountId(u.id)).catch(() => undefined);
    return () => ctrl.abort();
  }, []);
  const doExport = async () => {
    setExportState({ busy: true });
    try { await download("/api/me/export", "investment-intelligence-export.json"); setExportState({ msg: "Your data export has been downloaded." }); }
    catch (e) { setExportState({ err: describeError(e) }); }
  };
  const doDelete = async (e: FormEvent) => {
    e.preventDefault(); setDel({ busy: true });
    try {
      await api("/api/me/account", { method: "DELETE", body: JSON.stringify({ password }) });
      clearSession();
      location.reload();
    } catch (e2) { setDel({ err: describeError(e2) }); }
  };
  return <section className="card pad"><Header title="My data" eyebrow="PRIVATE TO YOUR ACCOUNT" />
    {accountId != null && <p className="small">Your account id: <code>{accountId}</code> <span className="tiny">(the owner of a private deployment puts this in OWNER_USER_IDS on the server)</span></p>}
    <div className="row"><button className="btn" onClick={doExport} disabled={exportState.busy}>{exportState.busy ? "Preparing…" : "Export my data"}</button><span className="tiny">Downloads your account, holdings, journal, paper orders, alerts and assistant history as JSON.</span></div>
    {exportState.msg && <p className="ok-text">{exportState.msg}</p>}{exportState.err && <p className="error">{exportState.err}</p>}
    <form className="form box danger" onSubmit={doDelete}>
      <h4>Delete my account</h4>
      <p className="small">This permanently deletes your account and all of its data. It cannot be undone. Export your data first if you want a copy.</p>
      <div className="filters">
        <label>Confirm with your password <input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></label>
        <label className="inline"><input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)} required /> I understand this cannot be undone</label>
      </div>
      {del.err && <p className="error">{del.err}</p>}
      <div className="row"><button className="btn danger" disabled={del.busy || !confirm || !password}>{del.busy ? "Deleting…" : "Delete my account"}</button></div>
    </form>
  </section>;
}

function NotBuilt({ title, text }: { title: string; text: string }) {
  return <section className="card pad notbuilt"><span className="badge st-off">NOT AVAILABLE YET</span><h2>{title}</h2><p>{text}</p></section>;
}

// ---------- Side panels ----------
function SourcesPanel({ mode, scan }: { mode: Mode; scan: ScanItem[] }) {
  const live = scan.filter(a => a.price_status === "LIVE").length;
  const sec = scan.filter(a => a.fundamental_inputs.status === "LIVE").length;
  const partial = scan.filter(a => a.fundamental_inputs.status === "PARTIAL").length;
  return <div className="side card pad"><Header title="Data sources" />
    <ul className="sources">
      <li><span className={`dot ${live === scan.length && live ? "st-live" : live ? "st-partial" : "st-demo"}`} />Prices: {live ? `${live} of ${scan.length} live (Yahoo Finance)` : "demo values"}</li>
      <li><span className={`dot ${sec ? "st-live" : partial ? "st-partial" : "st-demo"}`} />Fundamentals: {sec || partial ? `${sec} fully${partial ? `, ${partial} partly` : ""} from SEC EDGAR` : "demo values"}</li>
      <li><span className={`dot ${scan.some(a => a.market_inputs?.momentum_source.startsWith("12-1")) ? "st-live" : "st-demo"}`} />Momentum: {scan.some(a => a.market_inputs?.momentum_source.startsWith("12-1")) ? "from live price history" : "seed values"}</li>
      <li><span className="dot st-demo" />Sentiment: seed values (no live source yet)</li>
      <li><span className="dot st-off" />Ghana (GSE): no live feed yet</li>
      <li><span className="dot st-off" />Live trading: disabled</li>
    </ul>
    {mode.kind === "demo" && <p className="tiny">All figures on this page come from the bundled demo dataset.</p>}
  </div>;
}
function MacroList({ macro }: { macro: Macro }) {
  return <><ul className="sources">{macro.drivers.map(d => <li key={d.name}><b>{d.name}</b> · {d.impact} impact<br /><span className="tiny">{d.note}</span></li>)}</ul><p className="tiny">{macro.disclaimer}</p></>;
}
function MacroPanel({ macro }: { macro: Macro | null }) {
  if (!macro) return null;
  return <div className="side card pad"><Header title="Macro context" eyebrow="STATIC NOTES · NOT COMPUTED" /><MacroList macro={macro} /></div>;
}
function Disclaimer() {
  return <div className="side card pad"><Header title="How to read this" /><p className="tiny">Scores combine stated inputs with fixed weights. They describe the data, not the future. Always check the source and status badge of each figure, and consult a licensed adviser before investing.</p></div>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
