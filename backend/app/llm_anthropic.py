"""Claude (Anthropic) provider for the research assistant, via the official SDK."""
from __future__ import annotations

import os
import time

import anthropic

from .llm import MAX_OUTPUT_TOKENS, model_budget

DEFAULT_MODEL = "claude-opus-5-5"
MIN_RETRY_BUDGET_S = 15.0  # only retry a transient failure when at least this much time is left
_RETRYABLE = (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError)


def complete(system: str, user: str, budget_s: float | None = None) -> dict[str, object]:
    """One grounded completion. Returns {text, model, refused, truncated, provider}.

    Server-side refusal fallback is enabled ("default" routing), so a policy decline on the
    primary model is retried on a fallback model inside the same call.

    The whole call, retries included, stays within `budget_s` seconds: each attempt gets the
    remaining time as its timeout, the SDK's own retries are off, and a transient failure
    (rate limit, 5xx, dropped connection; not a timeout) is retried once if time remains.
    """
    model = os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
    budget = model_budget() if budget_s is None else budget_s
    deadline = time.monotonic() + budget
    attempts = 0
    while True:
        attempts += 1
        remaining = deadline - time.monotonic()
        client = anthropic.Anthropic(timeout=max(1.0, remaining), max_retries=0)
        try:
            response = client.beta.messages.create(
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": os.getenv("ASSISTANT_EFFORT", "high")},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            break
        except anthropic.APITimeoutError:
            raise
        except _RETRYABLE:
            if attempts >= 2 or deadline - time.monotonic() < MIN_RETRY_BUDGET_S:
                raise
            time.sleep(1.0)
    if response.stop_reason == "refusal":
        return {"text": "", "model": response.model, "refused": True, "truncated": False, "provider": "anthropic"}
    text = "".join(block.text for block in response.content if block.type == "text")
    return {"text": text.strip(), "model": response.model, "refused": False, "truncated": response.stop_reason == "max_tokens", "provider": "anthropic"}
