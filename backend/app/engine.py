from __future__ import annotations

from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from math import isfinite

from .data import ASSETS, AssetSnapshot, get_asset
from .fundamentals import FundamentalSnapshot, fundamentals_for_asset
from .history import momentum_score, price_history, statistics
from .market_data import live_quotes, quote_dict, quote_for_asset
from .risk import position_risk
from .valuation import scenario_values


# Position sizing is illustrated against a fixed model account, not a real portfolio.
MODEL_ACCOUNT_VALUE = 10_000.0


def band_label(score: float) -> str:
    """Neutral display bands (mirrors the UI); not buy/sell instructions."""
    return "High score" if score >= 85 else "Watch" if score >= 72 else "Neutral" if score >= 60 else "Low score"


def band_code(score: float) -> str:
    """The band in upper snake case (the API `verdict` field). Never BUY/HOLD/AVOID."""
    return band_label(score).upper().replace(" ", "_")


SEED_LABEL = "Seed value (not live)"
LIVE_SEC_LABEL = "SEC Company Facts"
# A live P/E divides a split-adjusted live price by annual EPS that is not restated until
# the next 10-K, so it is only used while the EPS period is recent and the share count has
# not changed in a way that suggests a split (or a different share class, e.g. BRK-B vs A).
MAX_EPS_AGE_DAYS = 456  # ~15 months
SHARE_RATIO_BOUNDS = (0.8, 1.25)


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def live_pe_assessment(price: float, price_live: bool, currency: str, fundamentals: FundamentalSnapshot, today: date | None = None,
                       split_dates: tuple[str, ...] | list[str] = ()) -> tuple[float | None, str | None]:
    """(P/E, None) from the live price and SEC diluted EPS, or (None, reason) when it must be withheld."""
    if not price_live:
        return None, "price is not live"
    if currency != "USD":
        return None, "quote currency is not USD (SEC EPS is in USD)"
    eps = fundamentals.diluted_eps
    if fundamentals.status != "LIVE" or not eps or eps <= 0:
        return None, "no positive live SEC diluted EPS"
    try:
        period_end = date.fromisoformat(str(fundamentals.eps_period_end))
    except ValueError:
        return None, "SEC EPS period is unknown"
    if ((today or date.today()) - period_end).days > MAX_EPS_AGE_DAYS:
        return None, "SEC EPS period is older than 15 months"
    later = [d for d in split_dates if d > period_end.isoformat()]
    if later:
        return None, f"stock split on {later[-1]} after the EPS period (EPS is not split-adjusted yet)"
    shares, diluted = fundamentals.shares_outstanding, fundamentals.diluted_shares
    if not shares or not diluted or shares <= 0 or diluted <= 0:
        return None, "cannot rule out a stock split since the EPS period (share counts unavailable)"
    ratio = shares / diluted
    if not SHARE_RATIO_BOUNDS[0] <= ratio <= SHARE_RATIO_BOUNDS[1]:
        return None, f"share count changed {ratio:.2f}x since the EPS period (possible stock split or share-class mismatch)"
    return round(price / eps, 2), None


def live_pe(price: float, price_live: bool, currency: str, fundamentals: FundamentalSnapshot, today: date | None = None) -> float | None:
    """P/E from the live price and the latest SEC diluted EPS, only when both are live, in USD and comparable."""
    return live_pe_assessment(price, price_live, currency, fundamentals, today)[0]


def score_asset(asset: AssetSnapshot, quote: dict[str, object] | None = None) -> dict[str, object]:
    price = float(quote["price"]) if quote and isinstance(quote.get("price"), (int, float)) else asset.price
    # A quote's own day change is passed through even when it is None: a seed change must
    # never sit next to a live price. The seed is used only when there is no quote at all.
    if quote:
        raw_change = quote.get("change_pct")
        change_pct = float(raw_change) if isinstance(raw_change, (int, float)) else None
    else:
        change_pct = asset.change_pct
    price_live = bool(quote and quote.get("status") == "LIVE")
    quote_currency = str(quote.get("currency") or "") if quote else ""
    currency = quote_currency if price_live and quote_currency else asset.currency
    fundamentals = fundamentals_for_asset(asset)
    history = price_history(asset.symbol, "2y")
    stats = statistics(history) if history else None
    hist_momentum = momentum_score(stats) if stats else None
    pe, pe_reason = live_pe_assessment(price, price_live, quote_currency, fundamentals,
                                       split_dates=[d for d, _ in history.splits] if history else ())
    pe_input = pe if pe is not None else asset.pe_ratio
    sec_live = fundamentals.status == "LIVE"
    field_values = {
        "revenue_growth_pct": (fundamentals.revenue_growth_pct, asset.revenue_growth_pct),
        "operating_margin_pct": (fundamentals.operating_margin_pct, asset.operating_margin_pct),
        "free_cash_flow_margin_pct": (fundamentals.free_cash_flow_margin_pct, asset.free_cash_flow_margin_pct),
    }
    inputs: dict[str, float] = {}
    field_sources: dict[str, str] = {}
    for key, (live_value, seed_value) in field_values.items():
        if sec_live and live_value is not None:
            inputs[key], field_sources[key] = float(live_value), f"{LIVE_SEC_LABEL} FY{fundamentals.fiscal_year}" if fundamentals.fiscal_year else LIVE_SEC_LABEL
        else:
            inputs[key], field_sources[key] = float(seed_value), SEED_LABEL
    live_fields = sum(1 for v in field_sources.values() if v != SEED_LABEL)
    fundamentals_status = "LIVE" if live_fields == len(field_sources) else "PARTIAL" if live_fields else "DEMO"
    seed_fields = [k for k, v in field_sources.items() if v == SEED_LABEL]
    fundamentals_source = (fundamentals.source if fundamentals_status == "LIVE"
                           else f"{LIVE_SEC_LABEL} with seed values for {', '.join(seed_fields)}" if fundamentals_status == "PARTIAL"
                           else fundamentals.source if not sec_live else SEED_LABEL)
    growth_input, margin_input, fcf_input = inputs["revenue_growth_pct"], inputs["operating_margin_pct"], inputs["free_cash_flow_margin_pct"]
    # Leverage is not derived from filings yet: the seed net debt / EBITDA is labelled as such.
    fundamental = clamp(35 + margin_input * 0.55 + fcf_input * 0.35 + max(growth_input, 0) * 0.8 - max(asset.net_debt_to_ebitda, 0) * 7)
    growth = clamp(45 + growth_input * 2.1)
    cash_flow = clamp(35 + fcf_input * 1.35)
    balance_sheet = clamp(92 - max(asset.net_debt_to_ebitda, 0) * 18)
    valuation = clamp(108 - pe_input * 1.15)
    momentum = clamp(hist_momentum if hist_momentum is not None else asset.momentum_score)
    sentiment = clamp(asset.sentiment_score)
    composite = round(fundamental * 0.24 + growth * 0.18 + cash_flow * 0.16 + balance_sheet * 0.12 + valuation * 0.14 + momentum * 0.09 + sentiment * 0.07, 1)
    result: dict[str, object] = {
        "symbol": asset.symbol, "name": asset.name, "market": asset.market, "currency": currency,
        "price": price, "change_pct": change_pct, "score": composite, "verdict": band_code(composite), "band": band_label(composite),
        "breakdown": {"fundamental": round(fundamental), "growth": round(growth), "cash_flow": round(cash_flow), "balance_sheet": round(balance_sheet), "valuation": round(valuation), "momentum": round(momentum), "sentiment": round(sentiment)},
        "fundamental_inputs": {"revenue_growth_pct": round(growth_input, 2), "operating_margin_pct": round(margin_input, 2), "free_cash_flow_margin_pct": round(fcf_input, 2),
                               "source": fundamentals_source, "status": fundamentals_status, "field_sources": field_sources, "fiscal_year": fundamentals.fiscal_year if sec_live else None},
        "macro_sensitivity": asset.macro_sensitivity,
        "market_inputs": {
            "pe_ratio": round(pe_input, 2), "pe_source": "Live price / SEC diluted EPS" if pe is not None else SEED_LABEL,
            "pe_note": None if pe is not None else f"Live P/E withheld: {pe_reason}.",
            "momentum_source": "12-1 month price momentum and 200-day trend" if hist_momentum is not None else SEED_LABEL,
            "sentiment_source": SEED_LABEL,
            "net_debt_to_ebitda": asset.net_debt_to_ebitda, "balance_sheet_source": SEED_LABEL,
            "history": stats,
        },
        "price_source": str(quote.get("provider")) if quote else "Internal deterministic dataset",
        "price_status": str(quote.get("status")) if quote else "DEMO",
    }
    if currency != asset.currency:
        result["listing_currency"] = asset.currency
        result["currency_note"] = f"Live quote is in {currency}; the seed listing currency is {asset.currency}."
    return result


def scanner(limit: int = 5) -> list[dict[str, object]]:
    # Warm the history and fundamentals caches in parallel; scoring then reads from cache.
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda a: (price_history(a.symbol, "2y"), fundamentals_for_asset(a)), ASSETS))
    quotes = {str(q["symbol"]): q for q in live_quotes()}
    ranked = sorted((score_asset(asset, quotes.get(asset.symbol)) for asset in ASSETS), key=lambda item: item["score"], reverse=True)
    return ranked[:limit]


def analyze_asset(symbol: str) -> dict[str, object] | None:
    asset = get_asset(symbol)
    if asset is None:
        return None
    quote = quote_dict(quote_for_asset(asset))
    scored = score_asset(asset, quote)
    current_price = float(scored["price"])
    scenarios = scenario_values(current_price, float(scored["fundamental_inputs"]["revenue_growth_pct"]), float(scored["market_inputs"]["pe_ratio"]))
    base = next(item for item in scenarios if item["label"] == "Base")
    fi = scored["fundamental_inputs"]
    fs = fi["field_sources"]
    risk = position_risk(portfolio_value=MODEL_ACCOUNT_VALUE, entry_price=current_price, stop_price=current_price * 0.92, max_risk_pct=1.0)
    return {
        **scored,
        "thesis": {
            "bull": [f"Revenue growth is {fi['revenue_growth_pct']:.1f}% ({fs['revenue_growth_pct']}).", f"Operating margin is {fi['operating_margin_pct']:.1f}% ({fs['operating_margin_pct']}) and free-cash-flow margin is {fi['free_cash_flow_margin_pct']:.1f}% ({fs['free_cash_flow_margin_pct']}).", asset.catalysts[0]],
            "bear": [f"A P/E of {scored['market_inputs']['pe_ratio']:.1f} ({scored['market_inputs']['pe_source'].lower()}) leaves valuation sensitivity in the thesis.", asset.risks[0], asset.risks[1]],
            "invalidation": "The thesis is weakened materially if growth, cash generation or balance-sheet quality deteriorate versus the tracked assumptions.",
            "market_question": "What does the market already know that this score may be missing?",
        },
        "valuation": {"scenarios": scenarios, "base_case": base},
        "risk": {**risk, "model_account_value": MODEL_ACCOUNT_VALUE, "stop_loss_pct": 8.0, "note": "Illustrative sizing for a model account: 1% risk with an 8% stop. Not a recommendation."},
        "raw_inputs": asdict(asset),
        "data_status": "LIVE_MARKET_DATA" if scored["price_status"] == "LIVE" else "DEMO_DATASET",
    }


def validate_numeric_values(payload: dict[str, object]) -> None:
    for key, value in payload.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not isfinite(float(value)):
            raise ValueError(f"Non-finite numeric value for {key}")
