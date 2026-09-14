from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class CommitteeDecision:
    symbol: str
    verdict: str
    score: float
    confidence: float
    bull_case: list[str]
    bear_case: list[str]
    risks: list[str]
    catalysts: list[str]
    invalidation: str
    approval_state: str = "HUMAN_DECISION_REQUIRED"


def build_committee(analysis: dict[str, object], bull_bear: dict[str, object]) -> dict[str, object]:
    score = float(analysis["score"])
    confidence = float(bull_bear.get("confidence", 50))
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "symbol": analysis["symbol"], "verdict": analysis["verdict"], "score": score, "confidence": round(confidence, 1), "bull_case": bull_bear.get("bull", []), "bear_case": bull_bear.get("bear", []), "valuation": analysis.get("valuation", {}), "risk": analysis.get("risk", {}), "approval_state": "HUMAN_DECISION_REQUIRED", "execution": "NO_AUTOMATIC_EXECUTION", "decision_question": "What evidence would make this thesis wrong?"}
