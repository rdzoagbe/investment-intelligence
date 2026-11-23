"""Chart overlays computed from daily closes: trend line, moving averages, support/resistance.

These are descriptive technical-analysis heuristics. They summarise where prices have
been; they are not forecasts and not buy/sell signals. Every output says how it was
computed so the UI can show the method next to the line.

Only closing prices are available from the history adapter, so swing points are found
on closes rather than intraday highs/lows.
"""
from __future__ import annotations

from math import exp, log, sqrt

SWING_WINDOW = 5          # a swing high/low must be the extreme of +/- this many sessions
CLUSTER_TOLERANCE = 0.02  # swings within 2% of each other form one level
MAX_LEVELS = 3            # per side


def _sma(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            out[i] = running / window
    return out


def trend_line(closes: list[float]) -> dict[str, object] | None:
    """Least-squares fit of log(close) against session index (constant-growth trend).

    Returns the fitted value at every point, the implied annualised slope and R²,
    so a weak fit can be shown as weak.
    """
    n = len(closes)
    if n < 20 or any(c <= 0 for c in closes):
        return None
    ys = [log(c) for c in closes]
    mean_x, mean_y = (n - 1) / 2, sum(ys) / n
    sxx = sum((i - mean_x) ** 2 for i in range(n))
    sxy = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    fitted = [intercept + slope * i for i in range(n)]
    ss_res = sum((y - f) ** 2 for y, f in zip(ys, fitted))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    resid_sd = sqrt(ss_res / max(n - 2, 1))
    return {
        "values": [round(exp(f), 4) for f in fitted],
        "upper": [round(exp(f + 2 * resid_sd), 4) for f in fitted],
        "lower": [round(exp(f - 2 * resid_sd), 4) for f in fitted],
        "annualised_slope_pct": round((exp(slope * 252) - 1) * 100, 2),
        "r_squared": round(r2, 3),
        "direction": "UP" if slope > 0 else "DOWN" if slope < 0 else "FLAT",
        "method": "Least-squares fit of log closing price over the shown period; band = ±2 standard deviations of the residuals.",
    }


def _swings(closes: list[float], window: int) -> tuple[list[int], list[int]]:
    """Indices of swing highs/lows. A flat top or bottom (equal closes) counts once, at its first
    session; the run must be strictly exceeded on both sides within the window."""
    highs, lows = [], []
    n = len(closes)
    for i in range(window, n - window):
        c = closes[i]
        if i > 0 and closes[i - 1] == c:
            continue  # not the first session of a plateau
        j = i
        while j + 1 < n and closes[j + 1] == c:
            j += 1  # end of the plateau
        left, right = closes[max(0, i - window):i], closes[j + 1:j + 1 + window]
        if len(left) < window or len(right) < window:
            continue
        if all(x < c for x in left) and all(x < c for x in right):
            highs.append(i)
        if all(x > c for x in left) and all(x > c for x in right):
            lows.append(i)
    return highs, lows


def _cluster(points: list[tuple[int, float]], tolerance: float) -> list[dict[str, object]]:
    """Group swing prices so that no cluster spans more than `tolerance` (measured from its lowest
    member). Anchoring on the lowest price stops a level from drifting across a wide range."""
    clusters: list[list[tuple[int, float]]] = []
    for idx, price in sorted(points, key=lambda p: p[1]):
        if clusters:
            low = clusters[-1][0][1]
            if (price - low) / low <= tolerance:
                clusters[-1].append((idx, price))
                continue
        clusters.append([(idx, price)])
    out = []
    for c in clusters:
        level = sum(p for _, p in c) / len(c)
        out.append({"level": round(level, 4), "touches": len(c), "last_index": max(i for i, _ in c)})
    return out


def support_resistance(closes: list[float], dates: list[str]) -> dict[str, object]:
    """Nearest support levels below and resistance levels above the last close.

    Levels come from clustered swing highs and lows. Strength is the number of swings
    in the cluster; a level touched only once is reported but marked weak.
    """
    if len(closes) < 2 * SWING_WINDOW + 5:
        return {"support": [], "resistance": [], "method": "Not enough history to find swing points."}
    last = closes[-1]
    highs, lows = _swings(closes, SWING_WINDOW)
    levels = _cluster([(i, closes[i]) for i in highs + lows], CLUSTER_TOLERANCE)

    def describe(lv: dict[str, object]) -> dict[str, object]:
        return {"level": lv["level"], "touches": lv["touches"], "strength": "STRONG" if int(lv["touches"]) >= 3 else "MODERATE" if int(lv["touches"]) == 2 else "WEAK",
                "last_touched": dates[int(lv["last_index"])], "distance_pct": round((float(lv["level"]) / last - 1) * 100, 2)}

    support = sorted((lv for lv in levels if float(lv["level"]) < last), key=lambda lv: -float(lv["level"]))[:MAX_LEVELS]
    resistance = sorted((lv for lv in levels if float(lv["level"]) > last), key=lambda lv: float(lv["level"]))[:MAX_LEVELS]
    return {
        "support": [describe(lv) for lv in support],
        "resistance": [describe(lv) for lv in resistance],
        "method": f"Swing highs/lows on closing prices (extreme of ±{SWING_WINDOW} sessions), clustered within {int(CLUSTER_TOLERANCE * 100)}%. Strength = number of swings at that level.",
    }


def overlays(closes: list[float], dates: list[str]) -> dict[str, object]:
    sma50, sma200 = _sma(closes, 50), _sma(closes, 200)
    return {
        "trend": trend_line(closes),
        "sma50": [round(v, 4) if v is not None else None for v in sma50],
        "sma200": [round(v, 4) if v is not None else None for v in sma200],
        "levels": support_resistance(closes, dates),
        "disclaimer": "Technical overlays describe past prices only. They are not forecasts or buy/sell signals.",
    }
