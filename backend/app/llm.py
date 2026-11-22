"""Pick the assistant's model provider from configuration. No key means no model: the
assistant then returns the gathered evidence without a generated answer."""
from __future__ import annotations

import os


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


def complete(system: str, user: str) -> dict[str, object]:
    name = provider()
    if name == "anthropic":
        from .llm_anthropic import complete as run
    elif name == "openai":
        from .llm_openai import complete as run
    else:
        raise RuntimeError("No model provider configured")
    return run(system, user)
