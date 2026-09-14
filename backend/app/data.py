from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssetSnapshot:
    symbol: str
    name: str
    market: str
    currency: str
    price: float
    change_pct: float
    revenue_growth_pct: float
    operating_margin_pct: float
    free_cash_flow_margin_pct: float
    net_debt_to_ebitda: float
    pe_ratio: float
    momentum_score: float
    sentiment_score: float
    macro_sensitivity: str
    catalysts: tuple[str, ...]
    risks: tuple[str, ...]


# The seed universe is deliberately marked as a model dataset. Live providers can
# replace prices/fundamentals without changing the scoring or scanner contracts.
ASSETS: tuple[AssetSnapshot, ...] = (
    AssetSnapshot("MSFT", "Microsoft", "NASDAQ", "USD", 415.20, 1.05, 14.0, 44.0, 32.0, -0.2, 35.0, 87.0, 72.0, "Moderate", ("Cloud/AI demand", "Copilot monetisation", "Operating leverage"), ("Valuation", "Regulation", "AI infrastructure intensity")),
    AssetSnapshot("ASML", "ASML Holding", "Euronext Amsterdam", "EUR", 672.40, 0.82, 12.0, 32.0, 27.0, -0.1, 31.0, 83.0, 76.0, "High", ("EUV demand", "AI semiconductor capex", "Service revenue growth"), ("China restrictions", "Semiconductor cycle", "Customer concentration")),
    AssetSnapshot("VISA", "Visa", "NYSE", "USD", 277.30, 0.61, 10.0, 67.0, 50.0, -0.8, 31.0, 79.0, 74.0, "Low", ("Cashless payments", "Cross-border recovery", "Operating leverage"), ("Regulation", "Consumer slowdown", "Pricing scrutiny")),
    AssetSnapshot("ACCESS", "Access Bank Ghana", "GSE", "GHS", 18.20, -0.30, 18.0, 25.0, 8.0, 0.0, 6.5, 61.0, 59.0, "High", ("Regional banking growth", "Digital channels", "Ghana credit recovery"), ("FX volatility", "Credit losses", "Interest-rate sensitivity")),
    AssetSnapshot("AMZN", "Amazon", "NASDAQ", "USD", 228.10, 0.94, 11.0, 11.0, 9.0, 0.4, 39.0, 88.0, 81.0, "Moderate", ("AWS growth", "Advertising", "Retail margin expansion"), ("Valuation", "Cloud competition", "Regulation")),
    AssetSnapshot("AAPL", "Apple", "NASDAQ", "USD", 229.40, 0.44, 6.0, 32.0, 24.0, 0.3, 34.0, 80.0, 75.0, "Moderate", ("Services growth", "Installed base", "AI features"), ("Valuation", "China exposure", "Hardware cycle")),
    AssetSnapshot("GOOGL", "Alphabet", "NASDAQ", "USD", 175.60, 0.76, 13.0, 32.0, 22.0, -0.6, 25.0, 84.0, 78.0, "Moderate", ("Search monetisation", "Cloud growth", "AI products"), ("Regulation", "AI disruption", "Capex intensity")),
    AssetSnapshot("META", "Meta Platforms", "NASDAQ", "USD", 548.20, 1.22, 18.0, 38.0, 30.0, -0.5, 24.0, 90.0, 82.0, "Moderate", ("Ad demand", "AI recommendation", "Messaging monetisation"), ("Regulation", "Capex", "Engagement changes")),
    AssetSnapshot("NVDA", "NVIDIA", "NASDAQ", "USD", 119.80, 1.71, 28.0, 62.0, 35.0, -1.0, 45.0, 94.0, 86.0, "High", ("AI accelerator demand", "Data-centre growth", "Platform ecosystem"), ("Valuation", "Competition", "Export controls")),
    AssetSnapshot("AVGO", "Broadcom", "NASDAQ", "USD", 171.30, 1.05, 17.0, 42.0, 28.0, 1.2, 32.0, 86.0, 80.0, "High", ("AI networking", "Custom accelerators", "Software cash flow"), ("Leverage", "Customer concentration", "Semiconductor cycle")),
    AssetSnapshot("TSM", "Taiwan Semiconductor", "NYSE", "USD", 194.10, 1.18, 20.0, 47.0, 31.0, -0.3, 27.0, 89.0, 83.0, "High", ("Leading-edge demand", "AI chips", "Capacity expansion"), ("Geopolitics", "Capex cycle", "Concentration")),
    AssetSnapshot("ORCL", "Oracle", "NYSE", "USD", 178.40, 0.52, 9.0, 31.0, 20.0, 3.2, 35.0, 78.0, 74.0, "Moderate", ("Cloud infrastructure", "Database installed base", "AI demand"), ("Leverage", "Cloud competition", "Valuation")),
    AssetSnapshot("CRM", "Salesforce", "NYSE", "USD", 302.60, 0.68, 10.0, 18.0, 25.0, 0.2, 34.0, 76.0, 72.0, "Moderate", ("Subscription growth", "AI agents", "Margin expansion"), ("Competition", "Growth deceleration", "Valuation")),
    AssetSnapshot("JPM", "JPMorgan Chase", "NYSE", "USD", 224.70, 0.31, 7.0, 30.0, 18.0, 0.0, 13.0, 77.0, 73.0, "High", ("Net interest income", "Investment banking", "Credit normalisation"), ("Credit losses", "Rates", "Regulation")),
    AssetSnapshot("BRK-B", "Berkshire Hathaway", "NYSE", "USD", 455.20, 0.18, 5.0, 18.0, 16.0, -0.7, 22.0, 70.0, 69.0, "Low", ("Insurance float", "Cash optionality", "Capital allocation"), ("Insurance losses", "Succession", "Market valuation")),
    AssetSnapshot("LLY", "Eli Lilly", "NYSE", "USD", 835.00, 0.95, 24.0, 34.0, 20.0, 0.5, 42.0, 88.0, 84.0, "Moderate", ("GLP-1 demand", "Pipeline", "Manufacturing scale"), ("Valuation", "Competition", "Pricing policy")),
    AssetSnapshot("JNJ", "Johnson & Johnson", "NYSE", "USD", 162.40, 0.12, 3.0, 25.0, 19.0, 0.6, 15.0, 64.0, 67.0, "Low", ("Defensive demand", "MedTech", "Pharma pipeline"), ("Litigation", "Patent expiry", "Regulation")),
    AssetSnapshot("NESN.SW", "Nestlé", "SIX Swiss Exchange", "CHF", 82.10, -0.14, 4.0, 17.0, 12.0, 1.8, 20.0, 58.0, 61.0, "Low", ("Pricing power", "Emerging markets", "Portfolio optimisation"), ("Input costs", "Consumer weakness", "FX")),
    AssetSnapshot("SAP", "SAP", "Xetra", "EUR", 247.30, 0.73, 10.0, 28.0, 24.0, 0.2, 41.0, 82.0, 79.0, "Moderate", ("Cloud backlog", "Recurring revenue", "AI integration"), ("Valuation", "Cloud transition", "Execution")),
    AssetSnapshot("MC.PA", "LVMH", "Euronext Paris", "EUR", 648.50, -0.22, 6.0, 27.0, 18.0, 1.0, 23.0, 62.0, 65.0, "Moderate", ("Luxury recovery", "Brand power", "Asia demand"), ("China slowdown", "FX", "Consumer demand")),
    AssetSnapshot("SU.PA", "Schneider Electric", "Euronext Paris", "EUR", 245.80, 0.66, 11.0, 18.0, 12.0, 1.3, 29.0, 81.0, 77.0, "Moderate", ("Electrification", "Data centres", "Energy efficiency"), ("Valuation", "Industrial cycle", "Input costs")),
    AssetSnapshot("AIR.PA", "Airbus", "Euronext Paris", "EUR", 154.20, 0.37, 8.0, 10.0, 6.0, 0.4, 26.0, 72.0, 70.0, "Moderate", ("Aircraft backlog", "Fleet renewal", "Aftermarket"), ("Supply chain", "Production execution", "Cyclicality")),
    AssetSnapshot("SONY", "Sony Group", "NYSE", "USD", 91.30, 0.41, 7.0, 12.0, 9.0, 0.3, 17.0, 69.0, 71.0, "Moderate", ("Gaming", "Entertainment", "Image sensors"), ("Console cycle", "FX", "Content costs")),
    AssetSnapshot("KO", "Coca-Cola", "NYSE", "USD", 71.20, 0.09, 5.0, 31.0, 20.0, 1.7, 26.0, 66.0, 68.0, "Low", ("Pricing", "Global distribution", "Defensive demand"), ("Input costs", "FX", "Consumer trade-down")),
    AssetSnapshot("TSLA", "Tesla", "NASDAQ", "USD", 242.60, 1.31, 9.0, 8.0, 7.0, -0.8, 70.0, 83.0, 79.0, "High", ("Energy storage", "Autonomy", "Manufacturing scale"), ("Valuation", "Competition", "Demand volatility")),
)


def get_asset(symbol: str) -> AssetSnapshot | None:
    symbol = symbol.strip().upper()
    return next((asset for asset in ASSETS if asset.symbol == symbol), None)
