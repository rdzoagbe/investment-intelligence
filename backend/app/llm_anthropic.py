"""Claude (Anthropic) provider for the research assistant, via the official SDK."""
from __future__ import annotations

import os

import anthropic

DEFAULT_MODEL = "claude-opus-5-5"


def complete(system: str, user: str) -> dict[str, object]:
    """One grounded completion. Returns {text, model, refused, provider}.

    Server-side refusal fallback is enabled ("default" routing), so a policy decline on the
    primary model is retried on a fallback model inside the same call.
    """
    model = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
    client = anthropic.Anthropic(timeout=float(os.getenv("AI_TIMEOUT", "60")), max_retries=2)
    response = client.beta.messages.create(
        model=model,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": os.getenv("ASSISTANT_EFFORT", "high")},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        return {"text": "", "model": response.model, "refused": True, "provider": "anthropic"}
    text = "".join(block.text for block in response.content if block.type == "text")
    return {"text": text.strip(), "model": response.model, "refused": False, "truncated": response.stop_reason == "max_tokens", "provider": "anthropic"}
