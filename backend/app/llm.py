"""Pick the assistant's model provider from configuration. No key means no model: the
assistant then returns the gathered evidence without a generated answer.

Every provider returns {text, model, refused, truncated, provider} and must finish within
the time budget it is given (seconds), so the whole /api/assistant/ask request stays under
REQUEST_BUDGET_S. The frontend should wait at least FRONTEND_TIMEOUT_S before giving up.
"""
from __future__ import annotations

import os

REQUEST_BUDGET_S = 110.0  # hard ceiling for one assistant request, evidence gathering included
DEFAULT_MODEL_BUDGET_S = 90.0  # default ceiling for the provider call itself
MAX_OUTPUT_TOKENS = 16000  # room for adaptive thinking plus a short answer
FRONTEND_TIMEOUT_S = 120  # what the browser should wait before aborting


def model_budget() -> float:
    """Seconds the provider call may take (AI_TIMEOUT), capped so the request fits REQUEST_BUDGET_S."""
    try:
        value = float(os.getenv("AI_TIMEOUT", str(DEFAULT_MODEL_BUDGET_S)))
    except ValueError:
        value = DEFAULT_MODEL_BUDGET_S
    return max(5.0, min(value, REQUEST_BUDGET_S - 10))


def provider() -> str:
    choice = os.getenv("ASSISTANT_PROVIDER", "").strip().lower()
    if choice in {"anthropic", "openai", "none"}:
        if choice == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
            return "none"
        if choice == "openai" and not os.getenv("OPENAI_API_KEY"):
            return "none"
        return choice
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "none"


def complete(system: str, user: str, budget_s: float | None = None) -> dict[str, object]:
    name = provider()
    if name == "anthropic":
        from .llm_anthropic import complete as run
    elif name == "openai":
        from .llm_openai import complete as run
    else:
        raise RuntimeError("No model provider configured")
    return run(system, user, budget_s=min(budget_s, model_budget()) if budget_s is not None else model_budget())
