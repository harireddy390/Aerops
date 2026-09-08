"""Local AI diagnoser (Ollama). Optional: failures degrade to rules, never crash AeroOps."""
from __future__ import annotations

import json

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("ai")


def available() -> bool:
    return bool(settings.ollama_enabled)


async def diagnose_structured(context: dict) -> dict | None:
    """Return {root_cause, explanation, confidence, recommended_action, risk_level} or None."""
    if not settings.ollama_enabled:
        return None
    prompt = (
        "You are an SRE assistant. Reply with JSON ONLY, no markdown, with keys: "
        "root_cause, explanation, confidence (0-1), recommended_action "
        "(one of restart_service, restart_dependency, install_dependency, clear_temp, rollback_config, retry_health_check, escalate), "
        "risk_level (low|medium|high).\n\nIncident:\n" + json.dumps(context)[:3000]
    )
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_sec) as client:
            r = await client.post(f"{settings.ollama_base_url}/api/generate", json={
                "model": settings.ollama_model, "prompt": prompt, "stream": False,
                "format": "json",
            })
            r.raise_for_status()
            text = r.json().get("response", "")
            data = json.loads(text)
            data["confidence"] = float(data.get("confidence", 0.5))
            if data.get("risk_level") not in ("low", "medium", "high"):
                data["risk_level"] = "medium"
            return data
    except Exception as exc:  # AI must never break the loop
        log.info(f"ollama unavailable, falling back to rules: {exc}")
        return None
