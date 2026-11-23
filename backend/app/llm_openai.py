"""OpenAI provider for the research assistant (Responses API over HTTPS), kept for existing deployments."""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

from .llm import MAX_OUTPUT_TOKENS, model_budget


def parse_response(payload: dict[str, object], model: str) -> dict[str, object]:
    """Read a raw Responses API payload.

    The REST JSON has no `output_text` field (that is an SDK convenience): the text is in
    output[].content[] parts of type "output_text"; a part of type "refusal" means the model
    declined; status "incomplete" means the answer was cut off.
    """
    texts: list[str] = []
    refused = False
    for item in payload.get("output") or []:  # type: ignore[union-attr]
        if not isinstance(item, dict) or item.get("type", "message") != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "output_text":
                texts.append(str(part.get("text") or ""))
            elif part.get("type") == "refusal":
                refused = True
    truncated = payload.get("status") == "incomplete"
    resolved_model = str(payload.get("model") or model)
    if refused and not "".join(texts).strip():
        return {"text": "", "model": resolved_model, "refused": True, "truncated": truncated, "provider": "openai"}
    return {"text": "".join(texts).strip(), "model": resolved_model, "refused": False, "truncated": truncated, "provider": "openai"}


def complete(system: str, user: str, budget_s: float | None = None) -> dict[str, object]:
    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    body = json.dumps({"model": model, "max_output_tokens": MAX_OUTPUT_TOKENS, "input": [
        {"role": "system", "content": [{"type": "input_text", "text": system}]},
        {"role": "user", "content": [{"type": "input_text", "text": user}]},
    ]}).encode()
    req = Request("https://api.openai.com/v1/responses", data=body, method="POST",
                  headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}", "Content-Type": "application/json"})
    # One attempt, no retries, so the call stays within the budget.
    with urlopen(req, timeout=model_budget() if budget_s is None else budget_s) as response:  # noqa: S310 - fixed provider URL
        payload = json.loads(response.read().decode())
    if not isinstance(payload, dict):
        raise ValueError("Unexpected response from the OpenAI Responses API")
    return parse_response(payload, model)
