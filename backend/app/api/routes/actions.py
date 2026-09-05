"""Manual remediation trigger (operator source) + ad-hoc diagnosis + system health."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions import NotFound
from app.core.security import require_role
from app.db.database import get_db
from app.db.models import Incident
from app.diagnosis import rule_engine
from app.engines import remediation_engine
from app.schemas import DiagnoseRequest, RemediationRequest

router = APIRouter(tags=["actions"])


@router.post("/api/incidents/{incident_id}/remediate")
async def remediate(incident_id: int, payload: RemediationRequest, db: Session = Depends(get_db),
                    user: dict = Depends(require_role("admin", "operator"))):
    inc = db.get(Incident, incident_id)
    if not inc:
        raise NotFound("incident not found")
    action = await remediation_engine.execute(db, inc, payload.action_type,
                                              source=f"operator:{user['username']}", params=payload.params)
    db.commit()
    return {"id": action.id, "status": action.status,
            "result": action.result, "error": action.error}


@router.post("/api/diagnose")
async def diagnose_text(payload: DiagnoseRequest):
    rule = rule_engine.diagnose(payload.text)
    return {"source": "rule", "root_cause": rule.root_cause,
            "explanation": rule.explanation, "confidence": rule.confidence,
            "recommended_action": rule.recommended_action, "risk_level": rule.risk_level}


@router.get("/api/system/health")
async def system_health(db: Session = Depends(get_db)):
    from app.core.config import settings
    from app.diagnosis import ai_diagnoser
    from app.monitoring.monitors import system_snapshot
    ai_ok = None
    if settings.ollama_enabled:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{settings.ollama_base_url}/api/tags")
                ai_ok = r.status_code == 200
        except Exception:
            ai_ok = False
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok", "components": {
        "database": "up" if db_ok else "down",
        "monitor_engine": "up",
        "ai_engine": "up" if ai_ok else ("disabled" if not settings.ollama_enabled else "unavailable"),
        "ai_openai": "configured" if settings.openai_api_key else "not-configured",
        "email": "configured" if (settings.smtp_user and settings.smtp_pass and settings.mail_to) else "not-configured",
        "notifications": "up", **system_snapshot()}}
