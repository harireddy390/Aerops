"""Audit engine: every important operation is recorded."""
from sqlalchemy.orm import Session

from app.db.models import AuditLog

EVENTS = {
    "SERVICE_CREATED", "SERVICE_STARTED", "SERVICE_STOPPED", "SERVICE_CRASHED",
    "INCIDENT_CREATED", "DIAGNOSIS_COMPLETED", "RESTART_ATTEMPTED", "RESTART_SUCCEEDED",
    "RESTART_FAILED", "REMEDIATION_APPROVED", "REMEDIATION_EXECUTED", "RECOVERY_VERIFIED",
    "INCIDENT_RESOLVED", "INCIDENT_ACKNOWLEDGED",
}


def record(db: Session, event: str, *, service_id=None, incident_id=None,
           actor="system", action="", result="", meta=None) -> AuditLog:
    entry = AuditLog(event=event, service_id=service_id, incident_id=incident_id,
                     actor=actor, action=action, result=result, meta=meta or {})
    db.add(entry)
    db.flush()
    return entry
