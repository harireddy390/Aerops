"""Diagnosis engine: rules first (instant, on the critical path), AI second.

AI chain: OpenAI (if key configured) -> Ollama (if enabled) -> rules stand alone.
A slow or dead model never blocks restart/recovery: the monitor records rules
instantly and AI enriches in the background. AI output is data, never executed.
"""
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import Diagnosis, Incident
from app.diagnosis import ai_diagnoser, openai_diagnoser, rule_engine
from app.engines import audit_engine, incident_engine


def _record(db: Session, incident: Incident, *, source: str, model: str,
            cause: str, expl: str, conf: float, action: str, risk: str) -> Diagnosis:
    diag = Diagnosis(incident_id=incident.id, source=source, model=model,
                     root_cause=cause, explanation=expl, confidence=conf,
                     recommended_action=action, risk_level=risk)
    db.add(diag)
    db.flush()
    audit_engine.record(db, "DIAGNOSIS_COMPLETED", service_id=incident.service_id,
                        incident_id=incident.id, action=f"{source}:{cause[:80]}",
                        result=f"conf={conf}")
    incident_engine.add_event(db, incident.id, "DIAGNOSIS_COMPLETED",
                              f"{source}: {cause} (conf {conf:.2f}) -> {action}")
    return diag


async def ai_opinion(context: dict) -> tuple[dict | None, str]:
    """Try OpenAI first, then Ollama. Returns (opinion, provider). Never raises."""
    if settings.openai_api_key:
        try:
            opinion = await openai_diagnoser.diagnose_structured(context)
            if opinion and opinion.get("root_cause"):
                return opinion, f"openai:{settings.openai_model}"
        except Exception:
            pass
    if settings.ollama_enabled:
        try:
            opinion = await ai_diagnoser.diagnose_structured(context)
            if opinion and opinion.get("root_cause"):
                return opinion, f"ollama:{settings.ollama_model}"
        except Exception:
            pass
    return None, ""


def _apply_ai(diag: Diagnosis, opinion: dict, provider: str) -> None:
    diag.source = "rule+ai" if diag.source == "rule" else "ai"
    diag.model = provider
    diag.root_cause = opinion["root_cause"]
    diag.explanation = opinion.get("explanation", diag.explanation)
    diag.confidence = opinion.get("confidence", diag.confidence)
    diag.recommended_action = opinion.get("recommended_action", diag.recommended_action)
    diag.risk_level = opinion.get("risk_level", diag.risk_level)


async def diagnose(db: Session, incident: Incident, *, log_text: str, ai_allowed: bool) -> Diagnosis:
    """Combined path (kept for API/tests). Monitor uses diagnose_rules + enrich_ai."""
    rule = rule_engine.diagnose(f"{incident.error_message}\n{log_text}")
    diag = _record(db, incident, source="rule", model="rules",
                   cause=rule.root_cause, expl=rule.explanation,
                   conf=rule.confidence, action=rule.recommended_action, risk=rule.risk_level)
    if ai_allowed:
        opinion, provider = await ai_opinion({
            "service": incident.service.name if incident.service else "?",
            "error": incident.error_message, "exit_code": incident.exit_code,
            "rule_cause": rule.root_cause, "logs": log_text[-1500:]})
        if opinion:
            _apply_ai(diag, opinion, provider)
            db.flush()
    return diag


def diagnose_rules(db: Session, incident: Incident, *, log_text: str) -> Diagnosis:
    rule = rule_engine.diagnose(f"{incident.error_message}\n{log_text}")
    return _record(db, incident, source="rule", model="rules",
                   cause=rule.root_cause, expl=rule.explanation,
                   conf=rule.confidence, action=rule.recommended_action, risk=rule.risk_level)


async def enrich_ai(incident_id: int, context: dict) -> None:
    """Background AI second opinion (OpenAI -> Ollama). Own session; never raises."""
    db: Session = SessionLocal()
    try:
        from app.utils.events import bus
        incident = db.get(Incident, incident_id)
        if not incident:
            return
        opinion, provider = await ai_opinion(context)
        if opinion:
            _record(db, incident, source="ai", model=provider,
                    cause=opinion["root_cause"],
                    expl=opinion.get("explanation", ""),
                    conf=float(opinion.get("confidence", 0.5)),
                    action=opinion.get("recommended_action", "restart_service"),
                    risk=opinion.get("risk_level", "medium"))
            db.commit()
            await bus.publish("diagnosis.ai", {"incident_id": incident.id})
    except Exception:
        db.rollback()
    finally:
        db.close()
