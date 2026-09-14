import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Asset = {
  symbol: string; name: string; market: string; currency: string; price: number; change_pct: number;
  score: number; verdict: string; breakdown: Record<string, number>; macro_sensitivity: string;
};
type Dashboard = {
  portfolio: { value: number; total_return_pct: number; benchmark_return_pct: number; risk_level: string; volatility_pct: number; cash_pct: number; cash_value: number };
  markets: { name: string; value: number; change_pct: number }[]; scanner: Asset[];
  committee: { symbol: string; verdict: string; score: number; question: string };
  insights: { type: string; text: string }[]; data_status: string;
};
type Analysis = Asset & { thesis: { bull: string[]; bear: string[]; invalidation: string; market_question: string } };

const API_BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

const demoAssets: Asset[] = [
  { symbol: "MSFT", name: "Microsoft", market: "NASDAQ", currency: "USD", price: 415.2, change_pct: 1.05, score: 92, verdict: "BUY", breakdown: { fundamental: 96, growth: 91, cash_flow: 95, balance_sheet: 96, valuation: 68, momentum: 87, sentiment: 72 }, macro_sensitivity: "Moderate" },
  { symbol: "ASML", name: "ASML Holding", market: "Euronext Amsterdam", currency: "EUR", price: 672.4, change_pct: 0.82, score: 90, verdict: "BUY", breakdown: { fundamental: 89, growth: 87, cash_flow: 92, balance_sheet: 94, valuation: 72, momentum: 83, sentiment: 76 }, macro_sensitivity: "High" },
  { symbol: "VISA", name: "Visa", market: "NYSE", currency: "USD", price: 277.3, change_pct: 0.61, score: 88, verdict: "BUY", breakdown: { fundamental: 94, growth: 66, cash_flow: 98, balance_sheet: 100, valuation: 72, momentum: 79, sentiment: 74 }, macro_sensitivity: "Low" },
  { symbol: "AMZN", name: "Amazon", market: "NASDAQ", currency: "USD", price: 228.1, change_pct: 0.94, score: 86, verdict: "BUY", breakdown: { fundamental: 72, growth: 68, cash_flow: 47, balance_sheet: 85, valuation: 63, momentum: 88, sentiment: 81 }, macro_sensitivity: "Moderate" },
  { symbol: "ACCESS", name: "Access Bank Ghana", market: "GSE", currency: "GHS", price: 18.2, change_pct: -0.3, score: 68, verdict: "WATCH", breakdown: { fundamental: 65, growth: 83, cash_flow: 46, balance_sheet: 92, valuation: 100, momentum: 61, sentiment: 59 }, macro_sensitivity: "High" },
];

const demoDashboard: Dashboard = {
  portfolio: { value: 12450, total_return_pct: 12.4, benchmark_return_pct: 9.8, risk_level: "Moderate", volatility_pct: 14.8, cash_pct: 17, cash_value: 2117 },
  markets: [
    { name: "S&P 500", value: 5842, change_pct: 0.72 }, { name: "NASDAQ", value: 18771, change_pct: 0.91 },
    { name: "DAX", value: 23456, change_pct: 0.48 }, { name: "EUR/USD", value: 1.102, change_pct: 0.18 }, { name: "Gold", value: 2534, change_pct: 0.36 },
  ],
  scanner: demoAssets,
  committee: { symbol: "MSFT", verdict: "BUY", score: 92, question: "What does the market already know that this score may be missing?" },
  insights: [
    { type: "MACRO", text: "Central-bank expectations remain a key driver for long-duration growth assets." },
    { type: "SECTOR", text: "AI infrastructure demand continues to influence semiconductor and cloud valuations." },
    { type: "RISK", text: "The scanner separates deterministic scoring from narrative analysis so assumptions remain inspectable." },
  ],
  data_status: "DEMO_DATASET",
};

function formatMoney(value: number, currency = "EUR") {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency, maximumFractionDigits: 0 }).format(value);
}

function demoAnalysis(symbol: string): Analysis | null {
  const asset = demoAssets.find((item) => item.symbol === symbol);
  if (!asset) return null;
  return { ...asset, thesis: {
    bull: [
      `${asset.name} has a strong modeled operating profile and a supportive long-term growth catalyst.`,
      `The deterministic score is ${asset.score}/100, with strong contribution from fundamentals and cash generation.`,
      "Catalysts are monitored separately from the score so the thesis can be challenged rather than blindly followed.",
    ],
    bear: [
      "Valuation leaves room for multiple compression if expectations reset.",
      "Execution, macro sensitivity and sector-specific risks could weaken the current setup.",
      "A strong headline score does not eliminate downside risk or uncertainty.",
    ],
    invalidation: "The thesis weakens materially if growth, cash generation or balance-sheet quality deteriorate versus the tracked assumptions.",
    market_question: "What does the market already know that this score may be missing?",
  }};
}

function App() {
  const [dashboard, setDashboard] = useState<Dashboard>(demoDashboard);
  const [selected, setSelected] = useState<Analysis | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("Demo mode");
  const [activeNav, setActiveNav] = useState("Command Center");

  useEffect(() => {
    fetch(`${API_BASE}/api/dashboard`, { signal: AbortSignal.timeout(2500) })
      .then((response) => { if (!response.ok) throw new Error("API unavailable"); return response.json(); })
      .then((data: Dashboard) => { setDashboard(data); setStatus("Engine connected"); })
      .catch(() => setStatus("Demo mode"));
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return dashboard.scanner.filter((asset) => !q || `${asset.symbol} ${asset.name}`.toLowerCase().includes(q));
  }, [dashboard, search]);

  async function inspect(symbol: string) {
    try {
      const response = await fetch(`${API_BASE}/api/assets/${symbol}/analysis`, { signal: AbortSignal.timeout(2500) });
      if (!response.ok) throw new Error("API unavailable");
      setSelected(await response.json());
    } catch { setSelected(demoAnalysis(symbol)); }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">II</div><div><strong>Investment Intelligence</strong><span>Research. Challenge. Decide.</span></div></div>
      <nav>{["Command Center", "Opportunity Scanner", "Investment Committee", "Portfolio", "Market Intelligence", "Investment Journal"].map((item) => <button className={`nav-item ${activeNav === item ? "active" : ""}`} key={item} onClick={() => setActiveNav(item)}><span className="nav-dot" />{item}</button>)}</nav>
      <div className="sidebar-section"><span className="section-label">Tools</span>{["Backtesting", "Paper Trading", "Broker Integration", "Settings"].map((item) => <button className="nav-item muted" key={item}>{item}</button>)}</div>
    </aside>

    <main className="main-content">
      <header className="topbar"><div><div className="eyebrow">{activeNav.toUpperCase()}</div><h1>Good morning.</h1></div><input className="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search stock, ETF, index or company..."/><div className="status-pill"><span /> {status}</div></header>

      <section className="ticker-row">{dashboard.markets.map((market) => <div className="ticker" key={market.name}><strong>{market.name}</strong> {market.value.toLocaleString()} <span className="positive">+{market.change_pct.toFixed(2)}%</span></div>)}</section>

      <section className="kpi-grid">
        <div className="card kpi"><span>Portfolio Value</span><strong>{formatMoney(dashboard.portfolio.value)}</strong><small>+{formatMoney(dashboard.portfolio.value * dashboard.portfolio.total_return_pct / 100)} all time</small></div>
        <div className="card kpi"><span>Total Return</span><strong className="positive">+{dashboard.portfolio.total_return_pct}%</strong><small>vs benchmark +{dashboard.portfolio.benchmark_return_pct}%</small></div>
        <div className="card kpi"><span>Risk Level</span><strong>{dashboard.portfolio.risk_level}</strong><small>Volatility {dashboard.portfolio.volatility_pct}%</small></div>
        <div className="card kpi"><span>Cash</span><strong>{dashboard.portfolio.cash_pct}%</strong><small>{formatMoney(dashboard.portfolio.cash_value)} available</small></div>
      </section>

      <section className="content-grid">
        <div className="card opportunities"><div className="card-header"><div><span className="eyebrow">AI MARKET SCANNER</span><h2>Top Investment Opportunities</h2></div><button className="ghost">{filtered.length} ranked</button></div>
          <div className="table"><div className="table-head"><span>Asset</span><span>Market</span><span>Currency</span><span>AI Score</span></div>{filtered.map((asset) => <button className="table-row clickable" key={asset.symbol} onClick={() => inspect(asset.symbol)}><div><strong>{asset.symbol}</strong><small>{asset.name}</small></div><span>{asset.market}</span><span>{asset.currency}</span><strong className="score">{asset.score}/100</strong></button>)}</div>
        </div>
        <div className="card insight"><div className="card-header"><div><span className="eyebrow">AI MARKET INSIGHTS</span><h2>What matters now</h2></div></div><div className="insight-list">{dashboard.insights.map((item) => <article key={item.type}><span className="signal">{item.type}</span><p>{item.text}</p></article>)}</div></div>
      </section>

      <section className="content-grid lower">
        <div className="card chart-card"><div className="card-header"><div><span className="eyebrow">PERFORMANCE</span><h2>Portfolio vs S&amp;P 500</h2></div><span className="range">1Y</span></div><div className="chart-placeholder"><div className="chart-line one"/><div className="chart-line two"/><div className="chart-labels"><span>Sep</span><span>Dec</span><span>Mar</span><span>Jun</span><span>Sep</span></div></div></div>
        <div className="card committee-card"><div className="card-header"><div><span className="eyebrow">INVESTMENT COMMITTEE</span><h2>{dashboard.committee.symbol}</h2></div><span className="verdict">{dashboard.committee.verdict}</span></div><div className="committee-score"><strong>{dashboard.committee.score}</strong><span>/100 AI Investment Score</span></div><p className="muted-copy">The committee combines deterministic scoring with a bull/bear challenge. Select an asset above to inspect the current thesis, risks and invalidation condition.</p><p className="question">“{dashboard.committee.question}”</p></div>
      </section>
      <div className="data-status">Data source: {dashboard.data_status}. This public demo does not execute trades.</div>
    </main>

    {selected && <div className="modal-backdrop" onClick={() => setSelected(null)}><section className="analysis-modal" onClick={(e) => e.stopPropagation()}><button className="close" onClick={() => setSelected(null)}>×</button><div className="eyebrow">INVESTMENT COMMITTEE</div><h2>{selected.name} · {selected.symbol}</h2><div className="analysis-head"><strong>{selected.score}</strong><span>/100 · {selected.verdict}</span><span>{selected.currency} {selected.price.toFixed(2)} · {selected.change_pct >= 0 ? "+" : ""}{selected.change_pct.toFixed(2)}%</span></div><div className="analysis-columns"><div><h3>Bull thesis</h3>{selected.thesis.bull.map((point) => <p key={point}>+ {point}</p>)}</div><div><h3>Bear thesis</h3>{selected.thesis.bear.map((point) => <p key={point}>− {point}</p>)}</div></div><div className="invalidation"><strong>Invalidation:</strong> {selected.thesis.invalidation}</div></section></div>}
  </div>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
