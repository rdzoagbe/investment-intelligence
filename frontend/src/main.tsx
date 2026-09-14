import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const exampleAssets = [
  { symbol: "MSFT", name: "Microsoft", market: "NASDAQ", currency: "USD", score: 92 },
  { symbol: "ASML", name: "ASML Holding", market: "Euronext Amsterdam", currency: "EUR", score: 90 },
  { symbol: "ACCESS", name: "Access Bank Ghana", market: "GSE", currency: "GHS", score: 84 },
  { symbol: "VISA", name: "Visa", market: "NYSE", currency: "USD", score: 84 },
];

function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">II</div>
          <div>
            <strong>Investment Intelligence</strong>
            <span>Research. Challenge. Decide.</span>
          </div>
        </div>

        <nav>
          {['Command Center', 'Opportunity Scanner', 'Investment Committee', 'Portfolio', 'Market Intelligence', 'Investment Journal'].map((item, index) => (
            <button className={`nav-item ${index === 0 ? 'active' : ''}`} key={item}>
              <span className="nav-dot" />
              {item}
            </button>
          ))}
        </nav>

        <div className="sidebar-section">
          <span className="section-label">Tools</span>
          <button className="nav-item muted">Backtesting</button>
          <button className="nav-item muted">Paper Trading</button>
          <button className="nav-item muted">Broker Integration</button>
          <button className="nav-item muted">Settings</button>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <div className="eyebrow">COMMAND CENTER</div>
            <h1>Good morning.</h1>
          </div>
          <div className="search">⌕ <span>Search stock, ETF, index or company...</span></div>
          <div className="status-pill"><span /> Local engine online</div>
        </header>

        <section className="ticker-row">
          {['S&amp;P 500  5,842 +0.72%', 'NASDAQ  18,771 +0.91%', 'DAX  23,456 +0.48%', 'EUR/USD  1.102 +0.18%', 'Gold  $2,534 +0.36%'].map((ticker) => (
            <div className="ticker" key={ticker} dangerouslySetInnerHTML={{ __html: ticker }} />
          ))}
        </section>

        <section className="kpi-grid">
          <div className="card kpi"><span>Portfolio Value</span><strong>€12,450</strong><small>+€1,372 all time</small></div>
          <div className="card kpi"><span>Total Return</span><strong className="positive">+12.4%</strong><small>vs benchmark +9.8%</small></div>
          <div className="card kpi"><span>Risk Level</span><strong>Moderate</strong><small>Volatility 14.8%</small></div>
          <div className="card kpi"><span>Cash</span><strong>17.0%</strong><small>€2,117 available</small></div>
        </section>

        <section className="content-grid">
          <div className="card opportunities">
            <div className="card-header">
              <div><span className="eyebrow">AI MARKET SCANNER</span><h2>Top Investment Opportunities</h2></div>
              <button className="ghost">View all →</button>
            </div>
            <div className="table">
              <div className="table-head"><span>Asset</span><span>Market</span><span>Currency</span><span>AI Score</span></div>
              {exampleAssets.map((asset) => (
                <div className="table-row" key={asset.symbol}>
                  <div><strong>{asset.symbol}</strong><small>{asset.name}</small></div>
                  <span>{asset.market}</span><span>{asset.currency}</span>
                  <strong className="score">{asset.score}/100</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="card insight">
            <div className="card-header">
              <div><span className="eyebrow">AI MARKET INSIGHTS</span><h2>What matters now</h2></div>
            </div>
            <div className="insight-list">
              <article><span className="signal">MACRO</span><p>Central-bank expectations remain a key driver for long-duration growth assets.</p></article>
              <article><span className="signal">SECTOR</span><p>AI infrastructure demand continues to influence semiconductor and cloud valuations.</p></article>
              <article><span className="signal">GHANA</span><p>GSE research is configured as a dedicated market adapter in the roadmap.</p></article>
            </div>
          </div>
        </section>

        <section className="content-grid lower">
          <div className="card chart-card">
            <div className="card-header"><div><span className="eyebrow">PERFORMANCE</span><h2>Portfolio vs S&amp;P 500</h2></div><span className="range">1Y</span></div>
            <div className="chart-placeholder"><div className="chart-line one" /><div className="chart-line two" /><div className="chart-labels"><span>Sep</span><span>Dec</span><span>Mar</span><span>Jun</span><span>Sep</span></div></div>
          </div>

          <div className="card committee-card">
            <div className="card-header"><div><span className="eyebrow">INVESTMENT COMMITTEE</span><h2>Microsoft · MSFT</h2></div><span className="verdict">WATCH</span></div>
            <div className="committee-score"><strong>92</strong><span>/100 AI Investment Score</span></div>
            <div className="score-grid"><div><span>Fundamental</span><strong>96</strong></div><div><span>Growth</span><strong>91</strong></div><div><span>Cash Flow</span><strong>95</strong></div><div><span>Valuation</span><strong>78</strong></div></div>
            <p className="muted-copy">Bull thesis is strong, but valuation and regulatory sensitivity keep the committee at WATCH until the thesis/risk balance improves.</p>
          </div>
        </section>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
