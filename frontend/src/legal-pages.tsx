// DRAFT legal texts. Not legal advice. They must be reviewed by a qualified lawyer before any public launch.
// Kept as plain data so the sign-in gate (auth-bootstrap.ts, no React) can show the same text.

export type LegalKey = "terms" | "privacy" | "risk";
export type LegalDoc = { title: string; sections: { heading: string; paragraphs: string[] }[] };

export const LEGAL_DRAFT_NOTICE = "DRAFT - not legal advice - to be reviewed by a qualified lawyer before public launch.";

export const LEGAL: Record<LegalKey, LegalDoc> = {
  terms: {
    title: "Terms of use",
    sections: [
      { heading: "What this service is", paragraphs: [
        "Investment Intelligence is a research and education tool. It collects market data, company filings and headlines, combines them with a transparent scoring model and shows the inputs and their sources.",
        "It is not investment advice, not a recommendation to buy, sell or hold any security, and not a personalised suitability assessment. Scores are neutral bands (High score, Watch, Neutral, Low score) calculated from stated inputs, and they can be wrong.",
      ] },
      { heading: "Not a broker, no orders", paragraphs: [
        "The service is not a broker or dealer and does not hold client money or securities. No real orders are placed from this site. Live trading is disabled. Paper trading is a simulation with no real money.",
      ] },
      { heading: "Data and its limits", paragraphs: [
        "Prices come from the Yahoo Finance chart API, an unofficial source that may be delayed, incomplete or unavailable. Company fundamentals come from SEC EDGAR filings where available. Headlines come from public RSS feeds. Where live data cannot be retrieved, bundled demo or seed values are used and labelled DEMO, SEED or UNAVAILABLE. Demo values must not be used for decisions.",
        "Every figure carries its source and status label. Check them before relying on any figure.",
      ] },
      { heading: "AI research assistant", paragraphs: [
        "The assistant answers only from evidence the platform gathers and cites it. Answers can still be incomplete or wrong, and answers without citations are marked unverified. It does not tell you what to buy or sell.",
      ] },
      { heading: "Your account", paragraphs: [
        "You are responsible for keeping your password secret. Do not enter broker, bank or other investment-account credentials. You can export your data and delete your account at any time from Settings.",
      ] },
      { heading: "No guarantees", paragraphs: [
        "The service is provided as is, without warranties of accuracy, availability or fitness for a particular purpose. To the extent permitted by law, the operator is not liable for losses resulting from use of the service or the data it shows.",
      ] },
    ],
  },
  privacy: {
    title: "Privacy notice",
    sections: [
      { heading: "What we store", paragraphs: [
        "Account: your name, email address, a salted password hash (never the password itself), when the account was created and when you accepted these documents.",
        "Your content: holdings you enter, journal entries, simulated paper-trading orders, alert rules and notifications, and the questions you ask the research assistant together with its answers.",
        "Your browser stores a sign-in token locally; signing out revokes it on the server.",
      ] },
      { heading: "Where it is stored", paragraphs: [
        "Data is stored in a PostgreSQL database hosted by Render in its Frankfurt (EU) region. Your data is private to your account; other users cannot see it.",
      ] },
      { heading: "AI assistant and third parties", paragraphs: [
        "When you ask the research assistant a question, the question and the evidence gathered for it are sent to the configured AI provider (Anthropic or OpenAI) to generate an answer. If your question concerns your portfolio or journal, that evidence includes your own holdings and journal entries. The page tells you when personal data was included. If no AI provider is configured, nothing is sent and only the evidence is shown.",
        "Market data requests to Yahoo Finance, SEC EDGAR and RSS feeds are made by the server and do not include your personal data.",
      ] },
      { heading: "Your rights", paragraphs: [
        "Export: Settings > Export my data downloads everything stored for your account as a JSON file.",
        "Deletion: Settings > Delete my account permanently deletes your account and all of its holdings, journal entries, paper orders, alerts and assistant history.",
        "You may also have rights to access, correct, restrict or object to processing, and to complain to a data-protection authority. Contact details for the operator must be added here before public launch.",
      ] },
      { heading: "Demo data", paragraphs: [
        "Bundled demo data is illustrative and contains no personal data. It is labelled DEMO wherever it appears.",
      ] },
    ],
  },
  risk: {
    title: "Risk disclosure",
    sections: [
      { heading: "Investing involves risk", paragraphs: [
        "The value of investments can go down as well as up, and you may get back less than you invest. Past performance, backtests and model scores do not predict future results.",
      ] },
      { heading: "Model and data risk", paragraphs: [
        "Scores combine stated inputs with fixed weights. They describe data, not the future. Inputs may be delayed, incomplete, unofficial or replaced by labelled demo values. Valuation scenarios and position-sizing figures are illustrations, not price targets or advice.",
        "Backtests use historical prices and simple rules. They ignore many real costs (taxes, spreads, slippage) and are subject to hindsight bias.",
      ] },
      { heading: "Currency risk", paragraphs: [
        "Assets are priced in different currencies (USD, EUR, GHS and others). Converted totals use exchange rates retrieved at the time and are only shown when every needed rate is available.",
      ] },
      { heading: "AI output", paragraphs: [
        "AI-generated text can be wrong even when it cites evidence. Always check the cited items and their source labels.",
      ] },
      { heading: "Get advice", paragraphs: [
        "This tool is for research and education only. Consider consulting a licensed financial adviser before making investment decisions.",
      ] },
    ],
  },
};

export function LegalPage({ doc }: { doc: LegalKey }) {
  const d = LEGAL[doc];
  return <section className="card pad legal">
    <div className="banner warn inline"><b>{LEGAL_DRAFT_NOTICE}</b></div>
    <h2>{d.title}</h2>
    {d.sections.map(s => <div key={s.heading}><h4>{s.heading}</h4>{s.paragraphs.map(p => <p key={p} className="small">{p}</p>)}</div>)}
  </section>;
}
