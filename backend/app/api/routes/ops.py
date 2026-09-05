"""Logs, diagnostics history, remediation history, notifications, metrics, system."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions import NotFound
from app.db.database import get_db
from app.db.models import AuditLog, Diagnosis, Incident, Notification, RemediationAction

router = APIRouter(tags=["ops"])


@router.get("/api/logs")
def logs(service_id: int | None = None, incident_id: int | None = None,
         limit: int = 100, db: Session = Depends(get_db)):
    from app.db.models import ServiceLog
    query = db.query(ServiceLog).order_by(ServiceLog.id.desc())
    if service_id:
        query = query.filter(ServiceLog.service_id == service_id)
    if incident_id:
        query = query.filter(ServiceLog.incident_id == incident_id)
    rows = query.limit(min(limit, 500)).all()[::-1]
    return [{"service_id": r.service_id, "incident_id": r.incident_id,
             "stream": r.stream, "content": r.content[-4000:],
             "t": r.timestamp.isoformat()} for r in rows]


@router.get("/api/diagnostics")
def diagnostics(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(Diagnosis).order_by(Diagnosis.id.desc()).limit(min(limit, 200)).all()
    return [{"id": d.id, "incident_id": d.incident_id, "source": d.source,
             "model": d.model, "root_cause": d.root_cause, "confidence": d.confidence,
             "risk": d.risk_level, "recommendation": d.recommended_action,
             "t": d.created_at.isoformat()} for d in rows]


@router.get("/api/remediation")
def remediation(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(RemediationAction).order_by(RemediationAction.id.desc()).limit(min(limit, 200)).all()
    return [{"id": a.id, "incident_id": a.incident_id, "action": a.action_type,
             "source": a.source, "status": a.status, "result": a.result,
             "error": a.error} for a in rows]


@router.get("/api/notifications")
def notifications(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(Notification).order_by(Notification.id.desc()).limit(min(limit, 200)).all()
    return [{"id": n.id, "title": n.title, "body": n.body[:500],
             "channel": n.channel, "delivered": n.delivered,
             "t": n.created_at.isoformat()} for n in rows]


@router.get("/api/audit")
def audit(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 300)).all()
    return [{"t": a.timestamp.isoformat(), "event": a.event, "service_id": a.service_id,
             "incident_id": a.incident_id, "actor": a.actor, "action": a.action,
             "result": a.result} for a in rows]


@router.get("/api/metrics/summary")
def metrics_summary(db: Session = Depends(get_db)):
    from app.db.models import Service
    from app.engines import metrics_engine
    services = db.query(Service).all()
    open_inc = db.query(Incident).filter(Incident.status.notin_(["RESOLVED", "FAILED"])).count()
    stats = metrics_engine.recovery_stats(db)
    by_status: dict[str, int] = {}
    for s in services:
        by_status[s.status] = by_status.get(s.status, 0) + 1
    return {"total": len(services), "by_status": by_status,
            "open_incidents": open_inc, **stats}
