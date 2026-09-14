import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Asset = {
  symbol: string;
  name: string;
  market: string;
  currency: string;
  price: number;
  change_pct: number;
  score: number;
  verdict: string;
  breakdown: Record<string, number>;
  macro_sensitivity: string;
};

type Dashboard = {
  portfolio: {
    value: number;
    total_return_pct: number;
    benchmark_return_pct: number;
    risk_level: string;
    volatility_pct: number;
    cash_pct: number;
    cash_value: number;
  };
  markets: { name: string; value: number; change_pct: number }[];
  scanner: Asset[];
  committee: { symbol: string; verdict: string; score: number; question: string };
  insights: { type: string; text: string }[];
  data_status: string;
};

type Analysis = Asset & {
  thesis: { bull: string[]; bear: string[]; invalidation: string; market_question: string };
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

function formatMoney(value: number, currency = "EUR") {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency, maximumFractionDigits: 0 }).format(value);
}

function App() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [selected, setSelected] = useState<Analysis | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeNav, setActiveNav] = useState("Command Center");

  useEffect(() => {
    fetch(`${API_BASE}/api/dashboard`)
      .then((response) => {
        if (!response.ok) throw new Error("API unavailable");
        return response.json();
      })
      .then((data: Dashboard) => setDashboard(data))
      .catch(() => setError("Local API unavailable — start the FastAPI backend on port 8000."))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    if (!dashboard) return [];
    const q = search.trim().toLowerCase();
    return dashboard.scanner.filter((asset) => !q || `${asset.symbol} ${asset.name}`.toLowerCase().includes(q));
  }, [dashboard, search]);

  async function inspect(symbol: string) {
    const response = await fetch(`${API_BASE}/api/assets/${symbol}/analysis`);
    if (!response.ok) return;
    setSelected(await response.json());
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">II</div>
          <div><strong>Investment Intelligence</strong><span>Research. Challenge. Decide.</span></div>
        </div>
        <nav>
          {["Command Center", "Opportunity Scanner", "Investment Committee", "Portfolio", "Market Intelligence", "Investment Journal"].map((item) => (
            <button className={`nav-item ${activeNav === item ? "active" : ""}`} key={item} onClick={() => setActiveNav(item)}>
              <span className="nav-dot" />{item}
            </button>
          ))}
        </nav>
        <div className="sidebar-section">
          <span className="section-label">Tools</span>
          {['Backtesting', 'Paper Trading', 'Broker Integration', 'Settings'].map((item) => <button className="nav-item muted" key={item}>{item}</button>)}
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div><div className="eyebrow">{activeNav.toUpperCase()}</div><h1>Good morning.</h1></div>
          <input className="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search stock, ETF, index or company..." />
          <div className="status-pill"><span /> {error ? "API offline" : "Local engine online"}</div>
        </header>

        {loading && <div className="loading card">Connecting to the investment engine…</div>}
        {error && <div className="error-banner">{error}</div>}

        {dashboard && <>
          <section className="ticker-row">
            {dashboard.markets.map((market) => <div className="ticker" key={market.name}><strong>{market.name}</strong> {market.value.toLocaleString()} <span className="positive">+{market.change_pct.toFixed(2)}%</span></div>)}
          </section>

          <section className="kpi-grid">
            <div className="card kpi"><span>Portfolio Value</span><strong>{formatMoney(dashboard.portfolio.value)}</strong><small>+{formatMoney(dashboard.portfolio.value * dashboard.portfolio.total_return_pct / 100)} all time</small></div>
            <div className="card kpi"><span>Total Return</span><strong className="positive">+{dashboard.portfolio.total_return_pct}%</strong><small>vs benchmark +{dashboard.portfolio.benchmark_return_pct}%</small></div>
            <div className="card kpi"><span>Risk Level</span><strong>{dashboard.portfolio.risk_level}</strong><small>Volatility {dashboard.portfolio.volatility_pct}%</small></div>
            <div className="card kpi"><span>Cash</span><strong>{dashboard.portfolio.cash_pct}%</strong><small>{formatMoney(dashboard.portfolio.cash_value)} available</small></div>
          </section>

          <section className="content-grid">
            <div className="card opportunities">
              <div className="card-header"><div><span className="eyebrow">AI MARKET SCANNER</span><h2>Top Investment Opportunities</h2></div><button className="ghost">{filtered.length} ranked</button></div>
              <div className="table">
                <div className="table-head"><span>Asset</span><span>Market</span><span>Currency</span><span>AI Score</span></div>
                {filtered.map((asset) => <button className="table-row clickable" key={asset.symbol} onClick={() => inspect(asset.symbol)}>
                  <div><strong>{asset.symbol}</strong><small>{asset.name}</small></div><span>{asset.market}</span><span>{asset.currency}</span><strong className="score">{asset.score}/100</strong>
                </button>)}
              </div>
            </div>

            <div className="card insight">
              <div className="card-header"><div><span className="eyebrow">AI MARKET INSIGHTS</span><h2>What matters now</h2></div></div>
              <div className="insight-list">{dashboard.insights.map((item) => <article key={item.type}><span className="signal">{item.type}</span><p>{item.text}</p></article>)}</div>
            </div>
          </section>

          <section className="content-grid lower">
            <div className="card chart-card"><div className="card-header"><div><span className="eyebrow">PERFORMANCE</span><h2>Portfolio vs S&amp;P 500</h2></div><span className="range">1Y</span></div><div className="chart-placeholder"><div className="chart-line one" /><div className="chart-line two" /><div className="chart-labels"><span>Sep</span><span>Dec</span><span>Mar</span><span>Jun</span><span>Sep</span></div></div></div>
            <div className="card committee-card"><div className="card-header"><div><span className="eyebrow">INVESTMENT COMMITTEE</span><h2>{dashboard.committee.symbol}</h2></div><span className="verdict">{dashboard.committee.verdict}</span></div><div className="committee-score"><strong>{dashboard.committee.score}</strong><span>/100 AI Investment Score</span></div><p className="muted-copy">The committee combines deterministic scoring with a bull/bear challenge. Select an asset above to inspect the current thesis, risks and invalidation condition.</p><p className="question">“{dashboard.committee.question}”</p></div>
          </section>

          <div className="data-status">Data source: {dashboard.data_status}. No live market feed or order execution is connected yet.</div>
        </>}
      </main>

      {selected && <div className="modal-backdrop" onClick={() => setSelected(null)}><section className="analysis-modal" onClick={(event) => event.stopPropagation()}><button className="close" onClick={() => setSelected(null)}>×</button><div className="eyebrow">INVESTMENT COMMITTEE</div><h2>{selected.name} · {selected.symbol}</h2><div className="analysis-head"><strong>{selected.score}</strong><span>/100 · {selected.verdict}</span><span>{selected.currency} {selected.price.toFixed(2)} · {selected.change_pct >= 0 ? "+" : ""}{selected.change_pct.toFixed(2)}%</span></div><div className="analysis-columns"><div><h3>Bull thesis</h3>{selected.thesis.bull.map((point) => <p key={point}>+ {point}</p>)}</div><div><h3>Bear thesis</h3>{selected.thesis.bear.map((point) => <p key={point}>− {point}</p>)}</div></div><div className="invalidation"><strong>Invalidation:</strong> {selected.thesis.invalidation}</div></section></div>}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
