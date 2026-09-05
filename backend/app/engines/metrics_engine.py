"""Metrics engine: throttled writes + aggregates for charts."""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Incident, ServiceMetric
from app.utils.time import utcnow


def record(db: Session, service_id: int, *, cpu: float, mem_mb: float,
           response_ms: float | None, status: str) -> None:
    db.add(ServiceMetric(service_id=service_id, cpu_pct=cpu, mem_mb=mem_mb,
                         response_ms=response_ms, status=status))
    cutoff = utcnow() - timedelta(days=settings.metrics_retention_days)
    db.query(ServiceMetric).filter(ServiceMetric.timestamp < cutoff).delete()


def series(db: Session, service_id: int, limit: int = 120) -> list[ServiceMetric]:
    return (db.query(ServiceMetric).filter(ServiceMetric.service_id == service_id)
            .order_by(ServiceMetric.id.desc()).limit(limit).all()[::-1])


def recovery_stats(db: Session) -> dict:
    rows = db.query(Incident).filter(Incident.status == "RESOLVED",
                                    Incident.duration_sec.isnot(None)).all()
    durations = [r.duration_sec for r in rows if r.duration_sec]
    restarts = sum(r.restart_attempts for r in rows)
    return {"resolved": len(rows),
            "avg_recovery_sec": round(sum(durations) / len(durations), 1) if durations else 0.0,
            "restarts": restarts}
