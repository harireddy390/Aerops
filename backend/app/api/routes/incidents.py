"""Incident query + acknowledge + timeline."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions import NotFound
from app.core.security import require_role
from app.db.database import get_db
from app.db.models import Incident
from app.engines import audit_engine, incident_engine
from app.schemas import IncidentOut

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=list[IncidentOut])
def list_incidents(status: str | None = None, service_id: int | None = None,
                   limit: int = 50, db: Session = Depends(get_db)):
    query = db.query(Incident).order_by(Incident.id.desc())
    if status:
        query = query.filter(Incident.status == status.upper())
    if service_id:
        query = query.filter(Incident.service_id == service_id)
    return [IncidentOut.model_validate(i) for i in query.limit(min(limit, 200)).all()]


@router.get("/{incident_id}")
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    inc = db.get(Incident, incident_id)
    if not inc:
        raise NotFound("incident not found")
    return {
        **IncidentOut.model_validate(inc).model_dump(),
        "failure_reason": inc.failure_reason,
        "acknowledged_at": inc.acknowledged_at,
        "diagnoses": [{"id": d.id, "source": d.source, "model": d.model, "root_cause": d.root_cause,
                       "explanation": d.explanation, "confidence": d.confidence,
                       "recommended_action": d.recommended_action,
                       "risk_level": d.risk_level} for d in inc.diagnoses],
        "actions": [{"id": a.id, "type": a.action_type, "source": a.source,
                     "status": a.status, "result": a.result, "error": a.error,
                     "started": a.started_at, "completed": a.completed_at} for a in inc.actions],
    }


@router.post("/{incident_id}/acknowledge")
def acknowledge(incident_id: int, db: Session = Depends(get_db),
                user: dict = Depends(require_role("admin", "operator"))):
    inc = db.get(Incident, incident_id)
    if not inc:
        raise NotFound("incident not found")
    incident_engine.transition(db, inc, "ACKNOWLEDGED", actor=user["username"],
                               message="acknowledged by operator")
    audit_engine.record(db, "INCIDENT_ACKNOWLEDGED", service_id=inc.service_id,
                        incident_id=inc.id, actor=user["username"], result="ok")
    db.commit()
    return {"status": inc.status}


@router.get("/{incident_id}/timeline")
def timeline(incident_id: int, db: Session = Depends(get_db)):
    inc = db.get(Incident, incident_id)
    if not inc:
        raise NotFound("incident not found")
    return [{"t": e.timestamp.isoformat(), "type": e.event_type,
             "message": e.message, "meta": e.meta} for e in
            sorted(inc.events, key=lambda e: e.id)]
