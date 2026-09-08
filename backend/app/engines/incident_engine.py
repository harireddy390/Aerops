"""Incident engine: strict state machine. Status changes only via these transitions."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import Conflict
from app.db.models import Incident, IncidentEvent
from app.engines import audit_engine
from app.utils.time import utcnow

TRANSITIONS = {
    "OPEN": {"INVESTIGATING", "ACKNOWLEDGED", "FAILED"},
    "INVESTIGATING": {"DIAGNOSED", "FAILED"},
    "DIAGNOSED": {"REMEDIATING", "RECOVERING", "FAILED"},
    "REMEDIATING": {"RECOVERING", "FAILED"},
    "RECOVERING": {"RESOLVED", "FAILED"},
    "ACKNOWLEDGED": {"INVESTIGATING", "RESOLVED", "FAILED"},
    "FAILED": {"INVESTIGATING"},
    "RESOLVED": set(),
}


def add_event(db: Session, incident_id: int, event_type: str, message: str, meta: dict | None = None) -> None:
    db.add(IncidentEvent(incident_id=incident_id, event_type=event_type, message=message, meta=meta or {}))
    db.flush()


def create_incident(db: Session, *, service_id: int, type: str, severity: str,
                    error_message: str, exit_code=None, failure_reason="",
                    fingerprint: str = "") -> Incident:
    # one open incident per service+type: reuse instead of duplicating
    existing = db.query(Incident).filter(
        Incident.service_id == service_id,
        Incident.status.notin_(["RESOLVED", "FAILED"])).first()
    if existing:
        return existing
    inc = Incident(service_id=service_id, type=type, severity=severity,
                   error_message=error_message[:4000], exit_code=exit_code,
                   failure_reason=failure_reason[:4000], fingerprint=fingerprint[:32])
    db.add(inc)
    db.flush()
    add_event(db, inc.id, "INCIDENT_CREATED", f"Incident #{inc.id} opened: {error_message[:200]}")
    audit_engine.record(db, "INCIDENT_CREATED", service_id=service_id, incident_id=inc.id,
                        action="create_incident", result=severity)
    return inc


def transition(db: Session, incident: Incident, to: str, *, actor="system", message="") -> Incident:
    allowed = TRANSITIONS.get(incident.status, set())
    if to not in allowed:
        raise Conflict(f"Cannot move incident #{incident.id} {incident.status} -> {to}")
    incident.status = to
    if to == "ACKNOWLEDGED":
        incident.acknowledged_at = utcnow()
    if to in ("RESOLVED", "FAILED"):
        incident.resolved_at = utcnow()
        incident.duration_sec = (incident.resolved_at - incident.detected_at).total_seconds()
    add_event(db, incident.id, to, message or f"Status -> {to}")
    audit_engine.record(db, f"INCIDENT_{to}" if to in ("RESOLVED",) else "INCIDENT_UPDATED",
                        service_id=incident.service_id, incident_id=incident.id,
                        actor=actor, action=f"transition->{to}", result="ok")
    db.flush()
    return incident
