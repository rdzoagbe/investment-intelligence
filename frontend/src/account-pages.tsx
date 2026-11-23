import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { type ChartLevel, type ChartSeries, api, cls, describeError, Header, isAbort, Kpi, LineChartSvg, localToday, money, Notice, num, pct, signedIn, statusCls, when, type Mode } from "./lib";

type AssetOption = { symbol: string; name: string };
type Stats = { volatility_1y_pct: number | null; momentum_12_1_pct: number | null; return_1y_pct: number | null; vs_200d_average_pct: number | null; max_drawdown_1y_pct: number | null; observations: number };

/** Load JSON for `path`. Only the latest request may update state: older responses (a previous asset,
 *  range or a reload overtaken by a newer one) are aborted and ignored. Data is tagged with its path so a
 *  stale result is never shown under a new selection. */
function useLoad<T>(path: string | null) {
  const [s, setS] = useState<{ path?: string; data?: T; error?: string; loading: boolean }>({ loading: true });
  const latest = useRef<{ id: number; ctrl?: AbortController }>({ id: 0 });
  const reload = useCallback(() => {
    latest.current.ctrl?.abort();
    const id = ++latest.current.id;
    if (!path) { setS({ loading: false }); return; }
    const ctrl = new AbortController();
    latest.current.ctrl = ctrl;
    setS(prev => ({ ...(prev.path === path ? prev : {}), path, loading: true }));
    api<T>(path, { signal: ctrl.signal })
      .then(data => { if (id === latest.current.id) setS({ path, data, loading: false }); })
      .catch(e => { if (id === latest.current.id && !isAbort(e)) setS({ path, error: describeError(e), loading: false }); });
  }, [path]);
  useEffect(() => { reload(); return () => { latest.current.ctrl?.abort(); latest.current.id++; }; }, [reload]);
  const current = s.path === path ? s : { loading: !!path };
  return { ...current, reload };
}

/** Keep a selected symbol valid for the current asset list: never fall back to a hidden default. */
function useSymbol(assets: AssetOption[], preferred?: string) {
  const [picked, setPicked] = useState(preferred ?? assets[0]?.symbol ?? "");
  const valid = assets.some(a => a.symbol === picked) ? picked : (assets[0]?.symbol ?? "");
  return [valid, setPicked] as const;
}

function needsAccount(mode: Mode, what: string) {
  if (mode.kind !== "api") return <Notice>{what} needs the API server and an account. It is not available on the static demo site.</Notice>;
  if (!signedIn()) return <Notice>Sign in to use {what.toLowerCase()}. Your data is stored privately against your account.</Notice>;
  return null;
}

function AssetSelect({ assets, value, onChange }: { assets: AssetOption[]; value: string; onChange: (s: string) => void }) {
  return <select value={value} onChange={e => onChange(e.target.value)}>{[...assets].sort((a, b) => a.name.localeCompare(b.name)).map(a => <option key={a.symbol} value={a.symbol}>{a.name} ({a.symbol})</option>)}</select>;
}

// ---------- Price history panel (asset detail) ----------
export function PriceHistoryPanel({ symbol, mode }: { symbol: string; mode: Mode }) {
  const [range, setRange] = useState("1y");
  const [show, setShow] = useState({ trend: true, averages: true, levels: true });
  const h = useLoad<{ points: { date: string; close: number }[]; currency: string; provider: string; adjusted?: boolean; statistics: Stats; overlays?: Overlays }>(mode.kind === "api" ? `/api/assets/${encodeURIComponent(symbol)}/history?range=${range}` : null);
  if (mode.kind !== "api") return <p className="tiny">Price history is only shown when the API retrieves it live. None is displayed in demo mode.</p>;
  return <div className="box span-all">
    <div className="row-between"><h4>Price history{h.data ? (h.data.adjusted ? " (adjusted close)" : " (close, not adjusted for dividends)") : ""}</h4><div className="seg" role="group" aria-label="History range">{["1y", "2y", "5y"].map(r => <button key={r} className={r === range ? "on" : ""} aria-pressed={r === range} onClick={() => setRange(r)}>{r}</button>)}</div></div>
    {h.loading && <p className="muted">Loading history…</p>}
    {h.error && <p className="muted">History unavailable: {h.error}</p>}
    {h.data && !h.loading && <>
      <TechnicalChart symbol={symbol} currency={h.data.currency} points={h.data.points} overlays={h.data.overlays} show={show} setShow={setShow} />
      <div className="stats">
        <span>1y return <b className={cls(h.data.statistics.return_1y_pct)}>{pct(h.data.statistics.return_1y_pct)}</b></span>
        <span>12-1 momentum <b className={cls(h.data.statistics.momentum_12_1_pct)}>{pct(h.data.statistics.momentum_12_1_pct)}</b></span>
        <span>vs 200-day avg <b className={cls(h.data.statistics.vs_200d_average_pct)}>{pct(h.data.statistics.vs_200d_average_pct)}</b></span>
        <span>1y volatility <b>{num(h.data.statistics.volatility_1y_pct)}%</b></span>
        <span>1y max drawdown <b className="down">{num(h.data.statistics.max_drawdown_1y_pct)}%</b></span>
      </div>
      <p className="tiny">{h.data.provider} · {h.data.points.length} daily closes · {h.data.currency}{h.data.adjusted === false ? " · not adjusted for dividends or splits" : ""}</p>
    </>}
  </div>;
}

// ---------- Technical overlays ----------
type Level = { level: number; touches: number; strength: string; last_touched: string; distance_pct: number };
type Overlays = {
  trend: { values: number[]; upper: number[]; lower: number[]; annualised_slope_pct: number; r_squared: number; direction: string; method: string } | null;
  sma50: (number | null)[]; sma200: (number | null)[];
  levels: { support: Level[]; resistance: Level[]; method: string };
  disclaimer: string;
};
type Show = { trend: boolean; averages: boolean; levels: boolean };

function TechnicalChart({ symbol, currency, points, overlays, show, setShow }: { symbol: string; currency: string; points: { date: string; close: number }[]; overlays?: Overlays; show: Show; setShow: (s: Show) => void }) {
  const series: ChartSeries[] = [{ name: `${symbol} close`, values: points.map(p => p.close), color: "#3aa0ff" }];
  const o = overlays;
  if (o && show.trend && o.trend) series.push({ name: "Trend line", values: o.trend.values, color: "#f5b937", dash: "2 0", width: 1.6 });
  if (o && show.averages) {
    if (o.sma50.some(v => v != null)) series.push({ name: "50-day average", values: o.sma50, color: "#b29cff", width: 1.4 });
    if (o.sma200.some(v => v != null)) series.push({ name: "200-day average", values: o.sma200, color: "#9ab1ca", width: 1.4, dash: "4 3" });
  }
  const levels: ChartLevel[] = o && show.levels ? [
    ...o.levels.support.slice(0, 2).map((l, i) => ({ value: l.level, label: `Support ${i + 1}`, color: "#22e0aa" })),
    ...o.levels.resistance.slice(0, 2).map((l, i) => ({ value: l.level, label: `Resistance ${i + 1}`, color: "#ff6b7a" })),
  ] : [];
  // A channel around a weak fit would look meaningful when it is not, so it is only drawn for R² >= 0.3.
  const band = o && show.trend && o.trend && o.trend.r_squared >= 0.3 ? { upper: o.trend.upper, lower: o.trend.lower, color: "#f5b937", name: "Trend band (±2σ)" } : undefined;
  const toggle = (k: keyof Show) => setShow({ ...show, [k]: !show[k] });
  return <>
    {o && <div className="seg overlay-toggles" role="group" aria-label="Chart overlays">
      <button className={show.trend ? "on" : ""} aria-pressed={show.trend} onClick={() => toggle("trend")}>Trend line</button>
      <button className={show.averages ? "on" : ""} aria-pressed={show.averages} onClick={() => toggle("averages")}>50/200-day averages</button>
      <button className={show.levels ? "on" : ""} aria-pressed={show.levels} onClick={() => toggle("levels")}>Support &amp; resistance</button>
    </div>}
    <LineChartSvg labels={points.map(p => p.date)} series={series} levels={levels} band={band} height={240} />
    {o && <div className="technicals">
      {o.trend && show.trend && <p className="small">Trend: <b className={o.trend.direction === "UP" ? "up" : o.trend.direction === "DOWN" ? "down" : ""}>{o.trend.direction.toLowerCase()}</b>, about {pct(o.trend.annualised_slope_pct)} a year over this period. Fit quality R² {num(o.trend.r_squared, 2)}{o.trend.r_squared < 0.3 ? " (weak: prices did not follow a steady trend)" : ""}.</p>}
      {show.levels && <div className="table-wrap"><table className="table compact">
        <thead><tr><th>Level</th><th className="r">Price ({currency})</th><th className="r">From last close</th><th>Strength</th><th>Last touched</th></tr></thead>
        <tbody>
          {o.levels.resistance.slice(0, 2).reverse().map((l, i, arr) => <tr key={`r${l.level}`}><td className="down">Resistance {arr.length - i}</td><td className="r">{num(l.level, 2)}</td><td className="r up">{pct(l.distance_pct)}</td><td>{l.strength.toLowerCase()} ({l.touches} touch{l.touches === 1 ? "" : "es"})</td><td>{l.last_touched}</td></tr>)}
          {o.levels.support.slice(0, 2).map((l, i) => <tr key={`s${l.level}`}><td className="up">Support {i + 1}</td><td className="r">{num(l.level, 2)}</td><td className="r down">{pct(l.distance_pct)}</td><td>{l.strength.toLowerCase()} ({l.touches} touch{l.touches === 1 ? "" : "es"})</td><td>{l.last_touched}</td></tr>)}
          {!o.levels.support.length && !o.levels.resistance.length && <tr><td colSpan={5} className="muted">No clear support or resistance levels in this period.</td></tr>}
        </tbody></table></div>}
      <details className="tiny"><summary>How these lines are calculated</summary>
        <ul>{o.trend && <li>{o.trend.method}</li>}<li>Moving averages: mean of the last 50 / 200 daily closes (shown once enough history exists).</li><li>{o.levels.method}</li></ul>
      </details>
      <p className="tiny warn-text">{o.disclaimer}</p>
    </div>}
  </>;
}

// ---------- Save to journal (asset detail) ----------
export function SaveToJournal({ symbol, mode }: { symbol: string; mode: Mode }) {
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState("");
  if (mode.kind !== "api" || !signedIn()) return null;
  if (!open) return <><button className="btn" onClick={() => { setOpen(true); setMsg(""); }}>Record a decision in my journal</button>{msg && <p className="ok-text" role="status">{msg}</p>}</>;
  return <JournalForm symbol={symbol} onDone={text => { setMsg(text); setOpen(false); }} onCancel={() => setOpen(false)} />;
}

function JournalForm({ symbol, assets, onDone, onCancel }: { symbol: string; assets?: AssetOption[]; onDone: (msg: string) => void; onCancel?: () => void }) {
  const [picked, setSym] = useState(symbol);
  const sym = !assets || assets.some(a => a.symbol === picked) ? picked : (assets[0]?.symbol ?? "");
  const [decision, setDecision] = useState("WATCH");
  const [thesis, setThesis] = useState("");
  const [review, setReview] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr("");
    if (!sym) { setErr("Choose an asset first."); return; }
    setBusy(true);
    try {
      await api("/api/me/journal", { method: "POST", body: JSON.stringify({ symbol: sym, decision, thesis, review_on: review || null }) });
      setThesis(""); setReview(""); onDone(`Saved ${decision} on ${sym} with the current evidence snapshot.`);
    } catch (e2) { setErr((e2 as Error).message); } finally { setBusy(false); }
  };
  return <form className="form box" onSubmit={submit}>
    <div className="filters">
      {assets ? <label>Asset <AssetSelect assets={assets} value={sym} onChange={setSym} /></label> : <label>Asset <input value={sym} readOnly /></label>}
      <label>Decision <select value={decision} onChange={e => setDecision(e.target.value)}>{["RESEARCH", "WATCH", "BUY", "ADD", "TRIM", "SELL", "PASS"].map(d => <option key={d}>{d}</option>)}</select></label>
      <label>Review on <input type="date" value={review} onChange={e => setReview(e.target.value)} /></label>
    </div>
    <label className="full">Thesis: why, what evidence, what would prove you wrong<textarea required minLength={10} maxLength={4000} rows={4} value={thesis} onChange={e => setThesis(e.target.value)} /></label>
    {err && <p className="error">{err}</p>}
    <div className="row"><button className="btn primary" disabled={busy || !sym}>{busy ? "Saving…" : "Save entry"}</button>{onCancel && <button type="button" className="btn" onClick={onCancel}>Cancel</button>}</div>
    <p className="tiny">The current price, score and data sources are stored with the entry so you can review the decision later against what you knew at the time. Journal entries are private notes, not orders.</p>
  </form>;
}

type JournalEntry = { id: number; symbol: string; decision: string; thesis: string; review_on: string | null; outcome: string; created_at: number; evidence: { price: number; currency: string; price_status: string; score: number; fundamentals_source: string } };

export function JournalPage({ mode, assets }: { mode: Mode; assets: AssetOption[] }) {
  const gate = needsAccount(mode, "The investment journal");
  const PAGE = 200;
  const j = useLoad<{ entries: JournalEntry[]; outcomes: string[] }>(gate ? null : `/api/me/journal?limit=${PAGE}`);
  // Older pages fetched with "Load older entries"; cleared whenever the first page reloads.
  const [older, setOlder] = useState<{ entries: JournalEntry[]; more: boolean; loading: boolean; error: string }>({ entries: [], more: true, loading: false, error: "" });
  useEffect(() => { setOlder({ entries: [], more: true, loading: false, error: "" }); }, [j.data]);
  const loadOlder = async () => {
    setOlder(o => ({ ...o, loading: true, error: "" }));
    try {
      const page = await api<{ entries: JournalEntry[] }>(`/api/me/journal?limit=${PAGE}&offset=${PAGE + older.entries.length}`);
      setOlder(o => ({ entries: [...o.entries, ...page.entries], more: page.entries.length === PAGE, loading: false, error: "" }));
    } catch (e) { setOlder(o => ({ ...o, loading: false, error: describeError(e) })); }
  };
  const entries = [...(j.data?.entries ?? []), ...older.entries];
  const mayHaveMore = (j.data?.entries.length ?? 0) === PAGE && older.more;
  const [msg, setMsg] = useState("");
  const [outcomeErr, setOutcomeErr] = useState<{ id: number; text: string } | null>(null);
  if (gate) return gate;
  const setOutcome = async (id: number, outcome: string) => {
    try { await api(`/api/me/journal/${id}`, { method: "PATCH", body: JSON.stringify({ outcome }) }); setOutcomeErr(null); j.reload(); }
    catch (e) { setOutcomeErr({ id, text: `Outcome not saved: ${describeError(e)}` }); }
  };
  // review_on is a calendar date chosen in the user's own time zone, so compare with the local date.
  const today = localToday();
  return <>
    <section className="card pad"><Header title="New entry" eyebrow="DECISIONS WITH THEIR EVIDENCE" />
      <JournalForm symbol={assets[0]?.symbol ?? ""} assets={assets} onDone={text => { setMsg(text); j.reload(); }} />
      {msg && <p className="ok-text" role="status">{msg}</p>}
    </section>
    <section className="card pad"><Header title={`Entries (${entries.length}${mayHaveMore ? "+" : ""})`} />
      {j.error && <p className="muted">{j.error}</p>}
      {j.data?.entries.length === 0 && <p className="muted">No entries yet.</p>}
      <div className="entries">{entries.map(e => <article key={e.id} className={`entry ${e.review_on && e.review_on <= today && e.outcome === "OPEN" ? "due" : ""}`}>
        <div className="row-between"><b>{e.decision} · {e.symbol}</b><span className="tiny">{when(e.created_at)}</span></div>
        <p className="small pre">{e.thesis}</p>
        <p className="tiny">At decision: {money(e.evidence.price, e.evidence.currency)} <span className={`badge ${statusCls(e.evidence.price_status)}`}>{e.evidence.price_status}</span> · score {e.evidence.score} · fundamentals: {e.evidence.fundamentals_source}{e.review_on ? ` · review on ${e.review_on}${e.review_on <= today && e.outcome === "OPEN" ? " (due)" : ""}` : ""}</p>
        <label className="inline">Outcome <select value={e.outcome} onChange={ev => setOutcome(e.id, ev.target.value)}>{(j.data?.outcomes ?? []).map(o => <option key={o} value={o}>{o.replace(/_/g, " ").toLowerCase()}</option>)}</select></label>
        {outcomeErr?.id === e.id && <p className="error" role="alert">{outcomeErr.text}</p>}
      </article>)}</div>
      {mayHaveMore && <div className="row"><button className="btn" disabled={older.loading} onClick={loadOlder}>{older.loading ? "Loading…" : "Load older entries"}</button></div>}
      {older.error && <p className="error" role="alert">Could not load older entries: {older.error}</p>}
    </section>
  </>;
}

// ---------- Portfolio ----------
type Holding = { symbol: string; name: string; quantity: number; average_cost: number; price: number; currency: string; price_status: string; price_source: string; value: number; pnl: number; pnl_pct: number | null; weight_in_currency_pct: number | null; history: Stats | null };
type FxRate = { rate: number | null; status: string; source: string | null };
type Converted = { currency: string; value: number; cost: number; pnl: number; return_pct: number | null; rates: Record<string, FxRate>; complete: boolean; live?: boolean; demo_priced_holdings?: number; note: string };
type MyPortfolio = { holdings: Holding[]; totals_by_currency: Record<string, { value: number; cost: number; pnl: number; return_pct: number | null }>; converted?: Converted | null; concentration_flags: string[]; notes: string[] };

function ConvertedTotals({ c, currencies }: { c: Converted | null | undefined; currencies: number }) {
  if (c == null) return currencies > 1 ? <p className="tiny">No combined total is shown: an exchange rate needed to convert every currency could not be retrieved live, and rates are never assumed.</p> : null;
  return <div className="box converted">
    <div className="kpis three">
      <Kpi title={`Combined value (${c.currency})`} value={money(c.value, c.currency)} sub={`Cost ${money(c.cost, c.currency)}`} />
      <Kpi title={`Combined P&L (${c.currency})`} value={money(c.pnl, c.currency)} sub={pct(c.return_pct)} />
      <Kpi title="Conversion" value={!c.complete ? "Partial" : c.live === false ? "Not live" : "Complete"}
        sub={!c.complete ? "Some holdings are left out (no exchange rate for their cost currency)" : c.live === false ? `${c.demo_priced_holdings ?? "Some"} holding(s) valued at DEMO prices` : "Every holding converted at live prices"} />
    </div>
    <ul className="inputs">{Object.entries(c.rates).map(([cur, r]) => <li key={cur}><span>{cur} → {c.currency}</span><b>{r.rate == null ? "unavailable" : num(r.rate, 6)}</b> <span className={`badge ${statusCls(r.status)}`}>{r.status}</span> <span className="tiny">{r.source ?? ""}</span></li>)}</ul>
    {c.note && <p className="tiny">{c.note}</p>}
  </div>;
}

export function MyPortfolioPage({ assets }: { assets: AssetOption[] }) {
  const p = useLoad<MyPortfolio>("/api/me/portfolio");
  const [symbol, setSymbol] = useSymbol(assets);
  const [qty, setQty] = useState(""); const [cost, setCost] = useState(""); const [err, setErr] = useState("");
  const save = async (e: FormEvent) => {
    e.preventDefault(); setErr("");
    try { await api("/api/me/holdings", { method: "POST", body: JSON.stringify({ symbol, quantity: Number(qty), average_cost: Number(cost) }) }); setQty(""); setCost(""); p.reload(); }
    catch (e2) { setErr((e2 as Error).message); }
  };
  const remove = async (s: string) => { setErr(""); await api(`/api/me/holdings/${encodeURIComponent(s)}`, { method: "DELETE" }).catch(e => setErr(describeError(e))); p.reload(); };
  return <>
    <section className="card pad"><Header title="My holdings" eyebrow="PRIVATE TO YOUR ACCOUNT" />
      <form className="filters" onSubmit={save}>
        <label>Asset <AssetSelect assets={assets} value={symbol} onChange={setSymbol} /></label>
        <label>Quantity <input type="number" step="any" min="0" required value={qty} onChange={e => setQty(e.target.value)} /></label>
        <label>Average cost (asset currency) <input type="number" step="any" min="0" required value={cost} onChange={e => setCost(e.target.value)} /></label>
        <button className="btn primary" disabled={!symbol}>Add or update</button>
      </form>
      {err && <p className="error">{err}</p>}
      {p.error && <p className="muted">{p.error}</p>}
      {p.data && (p.data.holdings.length === 0 ? <p className="muted">No holdings yet. Add what you own to track it at current prices.</p> : <>
        <div className="kpis">{Object.entries(p.data.totals_by_currency).map(([c, t]) => <Kpi key={c} title={`Total in ${c}`} value={money(t.value, c)} sub={`P&L ${money(t.pnl, c)} (${pct(t.return_pct)})`} />)}</div>
        <ConvertedTotals c={p.data.converted} currencies={Object.keys(p.data.totals_by_currency).length} />
        {p.data.concentration_flags.map(f => <p key={f} className="warn-text">Concentration: {f}.</p>)}
        <div className="table-wrap"><table className="table compact">
          <thead><tr><th>Asset</th><th className="r">Qty</th><th className="r">Avg cost</th><th className="r">Price</th><th className="r">Value</th><th className="r">P&L</th><th className="r">Weight*</th><th className="r">1y vol</th><th className="r">1y return</th><th /></tr></thead>
          <tbody>{p.data.holdings.map(h => <tr key={h.symbol}>
            <td><b>{h.name}</b><small>{h.symbol} <span className={`badge ${statusCls(h.price_status)}`}>{h.price_status}</span></small></td>
            <td className="r">{num(h.quantity, 4)}</td><td className="r">{money(h.average_cost, h.currency)}</td><td className="r">{money(h.price, h.currency)}</td>
            <td className="r">{money(h.value, h.currency)}</td><td className={`r ${cls(h.pnl)}`}>{money(h.pnl, h.currency)}<small>{pct(h.pnl_pct)}</small></td>
            <td className="r">{num(h.weight_in_currency_pct, 1)}%</td><td className="r">{h.history ? `${num(h.history.volatility_1y_pct)}%` : "—"}</td>
            <td className={`r ${cls(h.history?.return_1y_pct)}`}>{h.history ? pct(h.history.return_1y_pct) : "—"}</td>
            <td><button className="btn small" onClick={() => remove(h.symbol)}>Remove</button></td></tr>)}</tbody>
        </table></div>
        <p className="tiny">*Weight within holdings of the same currency. {p.data.notes.join(" ")} Volatility and return use live daily history when available ("—" when not).</p>
      </>)}
    </section>
  </>;
}

// ---------- Paper trading ----------
type PaperAcct = { starting_cash: number; cash: number; demo_priced_positions?: number; positions: { symbol: string; quantity: number; average_cost: number; price: number; price_status: string; currency: string; value: number; pnl: number }[]; orders: { id: number; symbol: string; side: string; quantity: number; fill_price: number; price_status: string; created_at: number }[]; notes: string[] };

export function PaperTradingPage({ mode, assets }: { mode: Mode; assets: AssetOption[] }) {
  const gate = needsAccount(mode, "Paper trading");
  const a = useLoad<PaperAcct>(gate ? null : "/api/me/paper");
  const [symbol, setSymbol] = useSymbol(assets);
  const [side, setSide] = useState("BUY"); const [qty, setQty] = useState(""); const [msg, setMsg] = useState(""); const [err, setErr] = useState("");
  if (gate) return gate;
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(""); setMsg("");
    if (!symbol) { setErr("Choose an asset first."); return; }
    try {
      const o = await api<{ side: string; quantity: number; symbol: string; fill_price: number; price_status: string }>("/api/me/paper/orders", { method: "POST", body: JSON.stringify({ symbol, side, quantity: Number(qty) }) });
      setMsg(`Simulated ${o.side} of ${o.quantity} ${o.symbol} filled at ${num(o.fill_price)} (${o.price_status} quote).`); setQty(""); a.reload();
    } catch (e2) { setErr((e2 as Error).message); }
  };
  return <>
    <div className="banner warn inline"><b>Simulation only.</b> No real money and no real orders. Fills use the server's current quote and record whether it was live.</div>
    {a.data && <div className="kpis three"><Kpi title="Simulated cash" value={num(a.data.cash)} sub={`Started with ${num(a.data.starting_cash)}`} /><Kpi title="Open positions" value={`${a.data.positions.length}`} sub="" /><Kpi title="Orders" value={`${a.data.orders.length}`} sub="Stored permanently in your account" /></div>}
    {a.data && (a.data.demo_priced_positions ?? 0) > 0 && <p className="warn-text">{a.data.demo_priced_positions} open position{a.data.demo_priced_positions === 1 ? " is" : "s are"} valued with DEMO prices, so equity and returns are not live.</p>}
    <section className="card pad"><Header title="Place a simulated order" />
      <form className="filters" onSubmit={submit}>
        <label>Asset <AssetSelect assets={assets} value={symbol} onChange={setSymbol} /></label>
        <label>Side <select value={side} onChange={e => setSide(e.target.value)}><option>BUY</option><option>SELL</option></select></label>
        <label>Quantity <input type="number" step="any" min="0" required value={qty} onChange={e => setQty(e.target.value)} /></label>
        <button className="btn primary" disabled={!symbol}>Submit simulated order</button>
      </form>
      {err && <p className="error">{err}</p>}{msg && <p className="ok-text">{msg}</p>}
    </section>
    {a.data && <section className="card pad"><Header title="Positions" />
      {a.data.positions.length === 0 ? <p className="muted">No open positions.</p> : <div className="table-wrap"><table className="table compact"><thead><tr><th>Asset</th><th className="r">Qty</th><th className="r">Avg cost</th><th className="r">Price</th><th className="r">Value</th><th className="r">P&L</th></tr></thead>
        <tbody>{a.data.positions.map(p => <tr key={p.symbol}><td>{p.symbol} <span className={`badge ${statusCls(p.price_status)}`}>{p.price_status}</span></td><td className="r">{num(p.quantity, 4)}</td><td className="r">{money(p.average_cost, p.currency)}</td><td className="r">{money(p.price, p.currency)}</td><td className="r">{money(p.value, p.currency)}</td><td className={`r ${cls(p.pnl)}`}>{money(p.pnl, p.currency)}</td></tr>)}</tbody></table></div>}
      <h4>Order history</h4>
      {a.data.orders.length === 0 ? <p className="muted">No orders yet.</p> : <div className="table-wrap"><table className="table compact"><thead><tr><th>Time</th><th>Asset</th><th>Side</th><th className="r">Qty</th><th className="r">Fill</th><th>Quote</th></tr></thead>
        <tbody>{a.data.orders.map(o => <tr key={o.id}><td>{when(o.created_at)}</td><td>{o.symbol}</td><td>{o.side}</td><td className="r">{num(o.quantity, 4)}</td><td className="r">{num(o.fill_price)}</td><td><span className={`badge ${statusCls(o.price_status)}`}>{o.price_status}</span></td></tr>)}</tbody></table></div>}
      <p className="tiny">{a.data.notes.join(" ")}</p>
    </section>}
  </>;
}

// ---------- Backtesting ----------
type Curve = { final_equity: number; total_return_pct: number; cagr_pct: number; max_drawdown_pct: number; equity_curve: number[]; trade_count?: number; time_invested_pct?: number };
type Backtest = { symbol: string; currency: string; provider: string; rule: string; start: string; end: string; dates: string[]; strategy: Curve; buy_and_hold: Curve; caveats: string[] };

export function BacktestPage({ mode, assets }: { mode: Mode; assets: AssetOption[] }) {
  const [symbol, setSymbol] = useSymbol(assets, assets.find(a => a.symbol === "MSFT")?.symbol);
  const [range, setRange] = useState("5y"); const [windowDays, setWindowDays] = useState(200);
  const bt = useLoad<Backtest>(mode.kind === "api" && symbol ? `/api/assets/${encodeURIComponent(symbol)}/backtest?range=${range}&window=${windowDays}` : null);
  if (mode.kind !== "api") return <Notice>Backtests run only on real price history retrieved by the API. The static demo site has no history, so no backtest is shown rather than an invented one.</Notice>;
  const row = (name: string, c: Curve) => <tr><td><b>{name}</b></td><td className="r">{num(c.final_equity)}</td><td className={`r ${cls(c.total_return_pct)}`}>{pct(c.total_return_pct)}</td><td className={`r ${cls(c.cagr_pct)}`}>{pct(c.cagr_pct)}</td><td className="r down">{num(c.max_drawdown_pct)}%</td><td className="r">{c.trade_count ?? 1}</td><td className="r">{c.time_invested_pct ?? 100}%</td></tr>;
  return <section className="card pad">
    <div className="filters">
      <label>Asset <AssetSelect assets={assets} value={symbol} onChange={setSymbol} /></label>
      <label>History <select value={range} onChange={e => setRange(e.target.value)}><option value="2y">2 years</option><option value="5y">5 years</option><option value="10y">10 years</option></select></label>
      <label>Trend window (days) <select value={windowDays} onChange={e => setWindowDays(Number(e.target.value))}>{[50, 100, 150, 200].map(w => <option key={w} value={w}>{w}</option>)}</select></label>
    </div>
    {bt.loading && <p className="muted">Running on real history…</p>}
    {bt.error && !bt.loading && <p className="muted">Backtest unavailable: {bt.error}</p>}
    {bt.data && !bt.loading && <>
      <p className="small">{bt.data.rule} Period {bt.data.start} to {bt.data.end}, starting with {num(10000)} {bt.data.currency}.</p>
      <LineChartSvg labels={bt.data.dates} series={[{ name: "Trend rule", values: bt.data.strategy.equity_curve, color: "#22e0aa" }, { name: "Buy and hold", values: bt.data.buy_and_hold.equity_curve, color: "#3aa0ff" }]} />
      <div className="table-wrap"><table className="table compact"><thead><tr><th /><th className="r">Final</th><th className="r">Total</th><th className="r">Per year</th><th className="r">Max drawdown</th><th className="r">Trades</th><th className="r">Invested</th></tr></thead>
        <tbody>{row("Trend rule", bt.data.strategy)}{row("Buy and hold", bt.data.buy_and_hold)}</tbody></table></div>
      <ul className="list bad">{bt.data.caveats.map(c => <li key={c}>{c}</li>)}</ul>
      <p className="tiny">{bt.data.provider}</p>
    </>}
  </section>;
}
