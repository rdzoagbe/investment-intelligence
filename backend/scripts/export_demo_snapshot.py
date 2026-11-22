"""Export the deterministic demo dataset for the static (GitHub Pages) build.

The static site has no API server, so it ships this snapshot instead. Every
record is generated in demo mode and is labelled DEMO in the UI: these are
illustrative inputs, not live market data.

Usage (from backend/):  python scripts/export_demo_snapshot.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["MARKET_DATA_MODE"] = "demo"
os.environ["FUNDAMENTALS_MODE"] = "demo"
os.environ.pop("OPENAI_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.committee import build_committee  # noqa: E402
from app.data import ASSETS  # noqa: E402
from app.engine import analyze_asset, scanner  # noqa: E402
from app.intelligence import bull_bear, macro_snapshot  # noqa: E402
from app.main import portfolio, risk  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "demo-snapshot.json"


def main() -> None:
    analyses: dict[str, object] = {}
    for asset in ASSETS:
        analysis = analyze_asset(asset.symbol)
        assert analysis is not None
        bb = bull_bear(asset.symbol, float(analysis["score"]), list(asset.catalysts), list(asset.risks))
        analyses[asset.symbol] = {"analysis": analysis, "committee": build_committee(analysis, bb)}
    snapshot = {
        "label": "DEMO_DATASET",
        "notice": "Illustrative seed data bundled with the static site. Prices, ratios and scores are not live and must not be used for investment decisions.",
        "scanner": scanner(100),
        "analyses": analyses,
        "macro": macro_snapshot(),
        "portfolio": portfolio(),
        "risk": risk(),
    }
    OUT.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
