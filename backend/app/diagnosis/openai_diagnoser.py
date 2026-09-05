"""Cloud AI diagnoser (OpenAI). Optional primary: configured key -> structured
diagnosis; any failure (no key, offline, bad response) returns None so the
chain falls through to Ollama, then rules. Output is data only, never executed."""
from __future__ import annotations

import json

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("openai")

SYSTEM = (
    "You are an SRE incident analyst. Reply with JSON ONLY, no markdown, "
    "with exactly these keys: root_cause (string), explanation (string), "
    "confidence (0-1 number), recommended_action (one of restart_service, "
    "restart_dependency, clear_temp, rollback_config, retry_health_check, "
    "escalate), risk_level (low|medium|high)."
)

_ALLOWED_ACTIONS = {
    "restart_service", "restart_dependency", "clear_temp",
    "rollback_config", "retry_health_check", "escalate",
}


def configured() -> bool:
    return bool(settings.openai_api_key)


async def diagnose_structured(context: dict) -> dict | None:
    if not settings.openai_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=settings.openai_timeout_sec) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "temperature": 0.2,
                    "max_tokens": 500,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": "Incident:\n" + json.dumps(context)[:3000]},
                    ],
                },
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            data = json.loads(text)
    except Exception as exc:
        log.info(f"openai unavailable, falling through: {type(exc).__name__}")
        return None
    try:
        data["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        if data.get("recommended_action") not in _ALLOWED_ACTIONS:
            data["recommended_action"] = "restart_service"
        if data.get("risk_level") not in ("low", "medium", "high"):
            data["risk_level"] = "medium"
        if not str(data.get("root_cause", "")).strip():
            return None
        return data
    except (ValueError, TypeError, AttributeError):
        return None
