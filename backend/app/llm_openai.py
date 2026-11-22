"""OpenAI provider for the research assistant (Responses API over HTTPS), kept for existing deployments."""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


def complete(system: str, user: str) -> dict[str, object]:
    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    body = json.dumps({"model": model, "input": [
        {"role": "system", "content": [{"type": "input_text", "text": system}]},
        {"role": "user", "content": [{"type": "input_text", "text": user}]},
    ]}).encode()
    req = Request("https://api.openai.com/v1/responses", data=body, method="POST",
                  headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}", "Content-Type": "application/json"})
    with urlopen(req, timeout=float(os.getenv("AI_TIMEOUT", "60"))) as response:  # noqa: S310 - fixed provider URL
        payload = json.loads(response.read().decode())
    text = payload.get("output_text") or "".join(
        part.get("text", "") for item in payload.get("output", []) for part in item.get("content", []) if isinstance(part, dict))
    return {"text": str(text).strip(), "model": model, "refused": False, "provider": "openai"}
