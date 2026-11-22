import { StrictMode, useEffect, useMemo, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BookOpen, BrainCircuit, CircleDollarSign, Database, Home, LineChart, Newspaper, Search, Settings as SettingsIcon, ShieldAlert, Users, WalletCards, X } from "lucide-react";
import demoSnapshot from "./demo-snapshot.json";
import "./styles.css";

// ---------- Types (mirror the FastAPI payloads) ----------
type ScanItem = {
  symbol: string; name: string; market: string; currency: string; price: number; change_pct: number | null;
  score: number; verdict: string; breakdown: Record<string, number>;
  fundamental_inputs: { revenue_growth_pct: number; operating_margin_pct: number; free_cash_flow_margin_pct: number; source: string; status: string };
  macro_sensitivity: string; price_source: string; price_status: string;
};
type Scenario = { label: string; growth_pct: number; multiple: number; fair_value: number; upside_pct: number };
type Analysis = ScanItem & {
  thesis: { bull: string[]; bear: string[]; invalidation: string; market_question: string };
  valuation: { scenarios: Scenario[] };
  risk: { risk_budget: number; shares: number; position_value: number; position_weight_pct: number; model_account_value: number; stop_loss_pct: number; note: string };
  data_status: string;
};
type Committee = { symbol: string; score: number; confidence: number; bull_case: string[]; bear_case: string[]; approval_state: string; execution: string; decision_question: string; timestamp: string; analysis?: string; model_provider?: string };
type Macro = { regime: string; drivers: { name: string; direction: string; impact: string; note: string }[]; disclaimer: string };
type MarketRow = { name: string; symbol: string; value: number | null; change_pct: number | null; status: string };
type Portfolio = { value: number; invested: number; cash: number; cash_pct: number; pnl: number; return_pct: number; allocation: { symbol: string; value: number; weight_pct: number; pnl_pct: number }[]; risk_flags: string[]; source: string; notice: string };
type Risk = { volatility_pct: number | null; sharpe: number | null; max_drawdown_pct: number | null; source: string; notice: string };
type NewsItem = { title: string; summary: string; source: string };
type Status = Record<string, Record<string, unknown>>;
type Page = "Command Center" | "Opportunity Scanner" | "Investment Committee" | "Portfolio" | "Market Intelligence" | "Investment Journal" | "Backtesting" | "Paper Trading" | "Broker Integration" | "Settings";
type Mode = { kind: "loading" } | { kind: "api" } | { kind: "demo"; reason: string };

const snapshot = demoSnapshot as unknown as { notice: string; scanner: ScanItem[]; analyses: Record<string, { analysis: Analysis; committee: Committee }>; macro: Macro; portfolio: Portfolio; risk: Risk };
const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
// A static host (GitHub Pages) has no API server unless one is configured explicitly.
const STATIC_HOST = !API_BASE && location.hostname.endsWith("github.io");

async function api<T>(path: string, timeoutMs = 25000): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal: AbortSignal.timeout(timeoutMs) });
  if (!response.ok) throw new Error(`${path} → HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

// ---------- Formatting ----------
function money(v: number | null | undefined, c = "USD") {
  if (v == null || !Number.isFinite(v)) return "—";
  try { return new Intl.NumberFormat("en-GB", { style: "currency", currency: c || "USD", maximumFractionDigits: 2 }).format(v); }
  catch { return v.toFixed(2); }
}
const num = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("en-GB", { maximumFractionDigits: d }));
const pct = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`);
// Neutral score bands instead of BUY/SELL wording: this is a research tool, not a recommendation service.
function band(score: number) {
  if (score >= 85) return { label: "High score", cls: "b-high" };
  if (score >= 72) return { label: "Watch", cls: "b-watch" };
  if (score >= 60) return { label: "Neutral", cls: "b-neutral" };
  return { label: "Low score", cls: "b-low" };
}
const statusCls = (s: string) => (s === "LIVE" ? "st-live" : s === "DEMO" ? "st-demo" : "st-off");

// ---------- App ----------
function App() {
  const [mode, setMode] = useState<Mode>({ kind: "loading" });
  const [page, setPage] = useState<Page>("Command Center");
  const [scan, setScan] = useState<ScanItem[]>([]);
  const [markets, setMarkets] = useState<MarketRow[] | null>(null);
  const [macro, setMacro] = useState<Macro | null>(null);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    const useDemo = (reason: string) => { setScan(snapshot.scanner); setMacro(snapshot.macro); setMarkets(null); setMode({ kind: "demo", reason }); };
    if (STATIC_HOST) { useDemo("This static site has no API server attached."); return; }
    Promise.all([api<{ items: ScanItem[] }>("/api/scanner?limit=100", 60000), api<{ markets: MarketRow[]; macro: Macro }>("/api/dashboard", 60000)])
      .then(([s, d]) => { setScan(s.items); setMarkets(d.markets); setMacro(d.macro); setMode({ kind: "api" }); })
      .catch(() => useDemo("The API server could not be reached."));
  }, []);

  const filtered = useMemo(() => scan.filter(a => `${a.symbol} ${a.name} ${a.market}`.toLowerCase().includes(search.toLowerCase())), [scan, search]);
  const nav = (x: Page, icon: ReactNode) => <button className={`nav-item ${page === x ? "active" : ""}`} onClick={() => setPage(x)}>{icon}<span>{x}</span></button>;

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><BrainCircuit size={28} /><div><strong>INVESTMENT INTELLIGENCE</strong><span>Research. Challenge. Decide.</span></div></div>
      <nav>{nav("Command Center", <Home size={16} />)}{nav("Opportunity Scanner", <Search size={16} />)}{nav("Investment Committee", <Users size={16} />)}{nav("Portfolio", <WalletCards size={16} />)}{nav("Market Intelligence", <Newspaper size={16} />)}{nav("Investment Journal", <BookOpen size={16} />)}</nav>
      <div className="tools"><span>TOOLS</span>{nav("Backtesting", <LineChart size={16} />)}{nav("Paper Trading", <CircleDollarSign size={16} />)}{nav("Broker Integration", <ShieldAlert size={16} />)}{nav("Settings", <SettingsIcon size={16} />)}</div>
    </aside>
    <main className="main">
      <header className="topbar">
        <div className="searchbox"><Search size={16} /><input value={search} onChange={e => { setSearch(e.target.value); if (page !== "Opportunity Scanner" && page !== "Command Center") setPage("Opportunity Scanner"); }} placeholder="Filter the research universe by name, ticker or market…" /></div>
      </header>
      <ModeBanner mode={mode} />
      <div className="workspace">
        <div className="primary">
          <div className="page-heading"><h1>{page}</h1><span className="today">{new Date().toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" })}</span></div>
          {mode.kind === "loading" ? <div className="card pad">Connecting to the research API… A free-tier server can take up to a minute to wake up.</div> :
            <PageBody page={page} mode={mode} scan={filtered} markets={markets} macro={macro} onOpen={setSelected} />}
        </div>
        <aside className="rightbar"><SourcesPanel mode={mode} scan={scan} /><MacroPanel macro={macro} /><Disclaimer /></aside>
      </div>
      <footer className="footer">Research and education tool. Not investment advice, not a broker, and no orders are placed from this site. Scores are model outputs from stated inputs and can be wrong.</footer>
    </main>
    {selected && <div className="modal" onClick={() => setSelected(null)}><div className="modal-card" onClick={e => e.stopPropagation()}><button className="modal-close" aria-label="Close" onClick={() => setSelected(null)}><X /></button><AssetDetail symbol={selected} mode={mode} /></div></div>}
  </div>;
}

function ModeBanner({ mode }: { mode: Mode }) {
  if (mode.kind === "api") return <div className="banner ok"><Database size={15} /> Connected to the research API. Each figure shows its source and whether it is LIVE or DEMO.</div>;
  if (mode.kind === "demo") return <div className="banner warn"><Database size={15} /> <span><b>Demo dataset.</b> {mode.reason} You are viewing bundled illustrative data: prices, ratios and scores are <b>not live</b> and must not be used for decisions.</span></div>;
  return null;
}

function PageBody({ page, mode, scan, markets, macro, onOpen }: { page: Page; mode: Mode; scan: ScanItem[]; markets: MarketRow[] | null; macro: Macro | null; onOpen: (s: string) => void }) {
  switch (page) {
    case "Command Center": return <CommandCenter mode={mode} scan={scan} markets={markets} onOpen={onOpen} />;
    case "Opportunity Scanner": return <Scanner scan={scan} onOpen={onOpen} />;
    case "Investment Committee": return <CommitteePage mode={mode} scan={scan} />;
    case "Portfolio": return <PortfolioPage mode={mode} />;
    case "Market Intelligence": return <IntelligencePage mode={mode} macro={macro} />;
    case "Paper Trading": return <PaperPage mode={mode} />;
    case "Settings": return <SettingsPage mode={mode} />;
    case "Investment Journal": return <NotBuilt title="Investment Journal" text="Saving research snapshots and decisions per account is not built yet. It is planned so every decision keeps its evidence, date and outcome." />;
    case "Backtesting": return <NotBuilt title="Backtesting" text="The backtest engine exists in the API, but no historical price data is connected yet. Results are not shown until real history is available, so no curve here is invented." />;
    case "Broker Integration": return <NotBuilt title="Broker Integration" text="Live trading is disabled. An optional Alpaca paper-trading (simulated) connection exists in the API and every order requires explicit human approval. Real-money execution would require a licensed broker and legal review." />;
  }
}

// ---------- Command Center ----------
function CommandCenter({ mode, scan, markets, onOpen }: { mode: Mode; scan: ScanItem[]; markets: MarketRow[] | null; onOpen: (s: string) => void }) {
  const live = scan.filter(a => a.price_status === "LIVE").length;
  const top = [...scan].sort((a, b) => b.score - a.score);
  return <>
    <section className="kpis">
      <Kpi title="Research universe" value={`${scan.length} assets`} sub="US, European and Ghana equities" />
      <Kpi title="Live price coverage" value={`${live} / ${scan.length}`} sub={live ? "Quotes from Yahoo Finance" : "No live quotes in this view"} />
      <Kpi title="Highest model score" value={top[0] ? `${top[0].score}` : "—"} sub={top[0] ? `${top[0].name} (${top[0].symbol})` : ""} />
      <Kpi title="Data mode" value={mode.kind === "api" ? "API" : "DEMO"} sub={mode.kind === "api" ? "Server-side calculations" : "Bundled illustrative snapshot"} />
    </section>
    <section className="card pad">
      <Header title="Market benchmarks" eyebrow="LIVE WHEN AVAILABLE · NO FALLBACK VALUES" />
      {markets ? <div className="ticker-row">{markets.map(m => <div className="ticker" key={m.symbol}><span>{m.name}</span><strong>{m.value == null ? "Unavailable" : num(m.value)}</strong><em className={(m.change_pct ?? 0) < 0 ? "down" : "up"}>{pct(m.change_pct)}</em></div>)}</div>
        : <p className="muted">Benchmark quotes are only shown when the API retrieves them live. None are displayed in demo mode.</p>}
    </section>
    <section className="card pad">
      <Header title="Highest-scoring assets" eyebrow="RANKED BY THE TRANSPARENT FACTOR MODEL" />
      <ScanTable rows={top.slice(0, 8)} onOpen={onOpen} />
    </section>
    {top[0] && <section className="card pad"><AssetDetail symbol={top[0].symbol} mode={mode} /></section>}
  </>;
}

function Kpi({ title, value, sub }: { title: string; value: string; sub: string }) {
  return <div className="card kpi"><span>{title}</span><strong>{value}</strong><small>{sub}</small></div>;
}
function Header({ title, eyebrow }: { title: string; eyebrow?: string }) {
  return <div className="card-header">{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h3>{title}</h3></div>;
}

function ScanTable({ rows, onOpen }: { rows: ScanItem[]; onOpen: (s: string) => void }) {
  if (!rows.length) return <p className="muted">No assets match this filter.</p>;
  return <div className="table-wrap"><table className="table">
    <thead><tr><th>Asset</th><th>Market</th><th className="r">Price</th><th className="r">Day</th><th className="r">Score</th><th>Band</th><th>Price data</th></tr></thead>
    <tbody>{rows.map(a => { const b = band(a.score); return <tr key={a.symbol} onClick={() => onOpen(a.symbol)} tabIndex={0} onKeyDown={e => e.key === "Enter" && onOpen(a.symbol)}>
      <td><b>{a.name}</b><small>{a.symbol}</small></td><td>{a.market}</td><td className="r">{money(a.price, a.currency)}</td>
      <td className={`r ${(a.change_pct ?? 0) < 0 ? "down" : "up"}`}>{pct(a.change_pct)}</td><td className="r"><b>{a.score.toFixed(1)}</b></td>
      <td><span className={`badge ${b.cls}`}>{b.label}</span></td><td><span className={`badge ${statusCls(a.price_status)}`}>{a.price_status}</span></td></tr>; })}</tbody>
  </table></div>;
}

// ---------- Asset detail ----------
function useAnalysis(symbol: string, mode: Mode) {
  const [state, setState] = useState<{ data?: Analysis; error?: string }>({});
  useEffect(() => {
    setState({});
    if (mode.kind !== "api") { const hit = snapshot.analyses[symbol]; setState(hit ? { data: hit.analysis } : { error: "Not in the demo dataset." }); return; }
    api<Analysis>(`/api/assets/${encodeURIComponent(symbol)}/analysis`).then(data => setState({ data })).catch(e => setState({ error: String(e.message || e) }));
  }, [symbol, mode.kind]);
  return state;
}

function AssetDetail({ symbol, mode }: { symbol: string; mode: Mode }) {
  const { data: a, error } = useAnalysis(symbol, mode);
  if (error) return <p className="muted">Analysis unavailable: {error}</p>;
  if (!a) return <p className="muted">Loading analysis…</p>;
  const b = band(a.score);
  return <div className="detail">
    <div className="detail-head">
      <div><span className="eyebrow">ASSET RESEARCH</span><h2>{a.name} <small>({a.symbol})</small></h2><p className="muted">{a.market} · {a.currency} · macro sensitivity {a.macro_sensitivity}</p></div>
      <div className="price"><strong>{money(a.price, a.currency)}</strong><em className={(a.change_pct ?? 0) < 0 ? "down" : "up"}>{pct(a.change_pct)}</em><span className={`badge ${statusCls(a.price_status)}`}>{a.price_status}</span><small>{a.price_source}</small></div>
    </div>
    <div className="detail-grid">
      <div className="box">
        <h4>Model score</h4>
        <div className="score"><b>{a.score.toFixed(1)}</b><span>/100</span></div>
        <span className={`badge ${b.cls}`}>{b.label}</span>
        <div className="bars">{Object.entries(a.breakdown).map(([k, v]) => <div key={k}><span>{k.replace("_", " ")}</span><i><em style={{ width: `${v}%` }} /></i><b>{v}</b></div>)}</div>
        <p className="tiny">Weights: fundamental 24%, growth 18%, cash flow 16%, valuation 14%, balance sheet 12%, momentum 9%, sentiment 7%. Fundamentals source: {a.fundamental_inputs.source} ({a.fundamental_inputs.status}).</p>
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
          <tbody>{a.valuation.scenarios.map(s => <tr key={s.label}><td>{s.label}</td><td className="r">{s.growth_pct}%</td><td className="r">{s.multiple}x</td><td className="r">{money(s.fair_value, a.currency)}</td><td className={`r ${s.upside_pct < 0 ? "down" : "up"}`}>{pct(s.upside_pct)}</td></tr>)}</tbody></table>
        <p className="tiny">Simple scenario scaffold from the stated growth and P/E inputs. It is not a price target.</p>
        <h4>Position-sizing illustration</h4>
        <p className="small">On a {money(a.risk.model_account_value, a.currency)} model account risking 1% with an {a.risk.stop_loss_pct}% stop: about {num(a.risk.shares, 2)} shares ({num(a.risk.position_weight_pct, 1)}% of the account).</p>
        <p className="tiny">{a.risk.note}</p>
      </div>
    </div>
  </div>;
}

// ---------- Pages ----------
function Scanner({ scan, onOpen }: { scan: ScanItem[]; onOpen: (s: string) => void }) {
  const [market, setMarket] = useState(""); const [min, setMin] = useState(0);
  const markets = [...new Set(scan.map(a => a.market))].sort();
  const rows = scan.filter(a => (!market || a.market === market) && a.score >= min).sort((a, b) => b.score - a.score);
  return <section className="card pad">
    <div className="filters">
      <label>Market <select value={market} onChange={e => setMarket(e.target.value)}><option value="">All markets</option>{markets.map(m => <option key={m}>{m}</option>)}</select></label>
      <label>Minimum score <input type="number" min={0} max={100} value={min} onChange={e => setMin(Number(e.target.value) || 0)} /></label>
      <span className="muted">{rows.length} of {scan.length} assets</span>
    </div>
    <ScanTable rows={rows} onOpen={onOpen} />
  </section>;
}

function CommitteePage({ mode, scan }: { mode: Mode; scan: ScanItem[] }) {
  const [symbol, setSymbol] = useState(scan[0]?.symbol ?? "MSFT");
  const [c, setC] = useState<{ data?: Committee; error?: string }>({});
  useEffect(() => {
    setC({});
    if (mode.kind !== "api") { const hit = snapshot.analyses[symbol]; setC(hit ? { data: hit.committee } : { error: "Not in the demo dataset." }); return; }
    api<Committee>(`/api/assets/${encodeURIComponent(symbol)}/committee`).then(data => setC({ data })).catch(e => setC({ error: String(e.message || e) }));
  }, [symbol, mode.kind]);
  return <section className="card pad">
    <div className="filters"><label>Asset <select value={symbol} onChange={e => setSymbol(e.target.value)}>{[...scan].sort((a, b) => a.name.localeCompare(b.name)).map(a => <option key={a.symbol} value={a.symbol}>{a.name} ({a.symbol})</option>)}</select></label></div>
    {c.error && <p className="muted">Committee packet unavailable: {c.error}</p>}
    {!c.data && !c.error && <p className="muted">Loading…</p>}
    {c.data && <div className="committee">
      <div className="kpis three"><Kpi title="Model score" value={c.data.score.toFixed(1)} sub={band(c.data.score).label} /><Kpi title="Signal strength (heuristic)" value={`${c.data.confidence}`} sub="Distance of the score from neutral, not a probability" /><Kpi title="Decision state" value="Human decision" sub="No automatic execution" /></div>
      {c.data.analysis ? <div className="box"><h4>AI synthesis ({c.data.model_provider})</h4><p className="small pre">{c.data.analysis}</p></div> :
        <div className="two"><div className="box"><h4>Arguments for</h4><ul className="list good">{c.data.bull_case.map(x => <li key={x}>{x}</li>)}</ul></div><div className="box"><h4>Arguments against</h4><ul className="list bad">{c.data.bear_case.map(x => <li key={x}>{x}</li>)}</ul></div></div>}
      <p className="question">Challenge: “{c.data.decision_question}”</p>
      <p className="tiny">Generated {new Date(c.data.timestamp).toLocaleString("en-GB")}. {c.data.analysis ? "Model-written text is a synthesis of the supplied facts only." : "Rule-based packet; no AI model is configured."}</p>
    </div>}
  </section>;
}

function useEndpoint<T>(path: string, mode: Mode, demo?: T) {
  const [s, setS] = useState<{ data?: T; error?: string }>({});
  useEffect(() => {
    if (mode.kind !== "api") { setS(demo ? { data: demo } : { error: "Requires the API server (not available on the static demo)." }); return; }
    api<T>(path).then(data => setS({ data })).catch(e => setS({ error: String(e.message || e) }));
  }, [path, mode.kind]);
  return s;
}

function PortfolioPage({ mode }: { mode: Mode }) {
  const p = useEndpoint<Portfolio>("/api/portfolio", mode, snapshot.portfolio);
  const r = useEndpoint<Risk>("/api/risk", mode, snapshot.risk);
  if (!p.data) return <section className="card pad muted">{p.error ?? "Loading…"}</section>;
  return <section className="card pad">
    <div className="banner warn inline"><b>Sample portfolio.</b> {p.data.notice}</div>
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
    {macro && <section className="card pad"><Header title={`Macro regime: ${macro.regime}`} /><MacroList macro={macro} /></section>}
  </>;
}

function PaperPage({ mode }: { mode: Mode }) {
  const s = useEndpoint<{ cash: number; equity: number; positions: unknown[]; orders: unknown[] }>("/api/paper-trading", mode);
  return <section className="card pad">
    <p className="small">Paper trading is simulated. No real money, no real orders. The simulated account currently resets when the server restarts (persistence is planned).</p>
    {s.error && <p className="muted">{s.error}</p>}
    {s.data && <div className="kpis three"><Kpi title="Simulated cash" value={num(s.data.cash)} sub="Starting balance 100,000" /><Kpi title="Simulated equity" value={num(s.data.equity)} sub="" /><Kpi title="Simulated orders" value={`${s.data.orders.length}`} sub={`${s.data.positions.length} open positions`} /></div>}
  </section>;
}

function SettingsPage({ mode }: { mode: Mode }) {
  const s = useEndpoint<Status>("/api/status", mode);
  return <section className="card pad">
    <p className="small">API base: <code>{API_BASE || (STATIC_HOST ? "none (static site)" : "same origin")}</code></p>
    {s.error && <p className="muted">{s.error}</p>}
    {s.data && <table className="table compact"><tbody>{Object.entries(s.data).map(([k, v]) => <tr key={k}><td><b>{k.replace("_", " ")}</b></td><td>{Object.entries(v).map(([kk, vv]) => `${kk}: ${String(vv)}`).join(" · ")}</td></tr>)}</tbody></table>}
  </section>;
}

function NotBuilt({ title, text }: { title: string; text: string }) {
  return <section className="card pad notbuilt"><span className="badge st-off">NOT AVAILABLE YET</span><h2>{title}</h2><p>{text}</p></section>;
}

// ---------- Side panels ----------
function SourcesPanel({ mode, scan }: { mode: Mode; scan: ScanItem[] }) {
  const live = scan.filter(a => a.price_status === "LIVE").length;
  const sec = scan.filter(a => a.fundamental_inputs.status === "LIVE").length;
  return <div className="side card pad"><Header title="Data sources" />
    <ul className="sources">
      <li><span className={`dot ${live ? "st-live" : "st-demo"}`} />Prices: {live ? `${live} live (Yahoo Finance)` : "demo values"}</li>
      <li><span className={`dot ${sec ? "st-live" : "st-demo"}`} />Fundamentals: {sec ? `${sec} from SEC EDGAR` : "demo values"}</li>
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
  return <div className="side card pad"><Header title={`Macro: ${macro.regime}`} eyebrow="RULE-BASED LABELS" /><MacroList macro={macro} /></div>;
}
function Disclaimer() {
  return <div className="side card pad"><Header title="How to read this" /><p className="tiny">Scores combine stated inputs with fixed weights. They describe the data, not the future. Always check the source and status badge of each figure, and consult a licensed adviser before investing.</p></div>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
