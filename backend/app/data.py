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


ASSETS: tuple[AssetSnapshot, ...] = (
    AssetSnapshot(
        "MSFT", "Microsoft", "NASDAQ", "USD", 415.20, 1.05,
        14.0, 44.0, 32.0, -0.2, 35.0, 87.0, 72.0, "Moderate",
        ("Cloud/AI demand", "Copilot monetisation", "Operating leverage"),
        ("Valuation", "Regulation", "AI infrastructure intensity"),
    ),
    AssetSnapshot(
        "ASML", "ASML Holding", "Euronext Amsterdam", "EUR", 672.40, 0.82,
        12.0, 32.0, 27.0, -0.1, 31.0, 83.0, 76.0, "High",
        ("EUV demand", "AI semiconductor capex", "Service revenue growth"),
        ("China restrictions", "Semiconductor cycle", "Customer concentration"),
    ),
    AssetSnapshot(
        "VISA", "Visa", "NYSE", "USD", 277.30, 0.61,
        10.0, 67.0, 50.0, -0.8, 31.0, 79.0, 74.0, "Low",
        ("Cashless payments", "Cross-border recovery", "Operating leverage"),
        ("Regulation", "Consumer slowdown", "Pricing scrutiny"),
    ),
    AssetSnapshot(
        "ACCESS", "Access Bank Ghana", "GSE", "GHS", 18.20, -0.30,
        18.0, 25.0, 8.0, 0.0, 6.5, 61.0, 59.0, "High",
        ("Regional banking growth", "Digital channels", "Ghana credit recovery"),
        ("FX volatility", "Credit losses", "Interest-rate sensitivity"),
    ),
    AssetSnapshot(
        "AMZN", "Amazon", "NASDAQ", "USD", 228.10, 0.94,
        11.0, 11.0, 9.0, 0.4, 39.0, 88.0, 81.0, "Moderate",
        ("AWS growth", "Advertising", "Retail margin expansion"),
        ("Valuation", "Cloud competition", "Regulation"),
    ),
)


def get_asset(symbol: str) -> AssetSnapshot | None:
    symbol = symbol.strip().upper()
    return next((asset for asset in ASSETS if asset.symbol == symbol), None)
