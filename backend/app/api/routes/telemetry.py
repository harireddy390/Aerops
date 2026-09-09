"""Browser crash telemetry: turns client-side failures into AeroOps incidents,
then fires the autonomous code-fix pipeline in the background.

Public by design (browsers can't hold API secrets) but deliberately narrow:
it can ONLY create/dedupe incidents and propose guarded patches. The patch
engine (exact-match + allowlisted verify + backup/rollback) is the execution
gate; nothing runs on a shell, ever.
"""
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Incident, Service, ServiceLog
from app.diagnosis.stackparse import parse as parse_crash
from app.engines import audit_engine, diagnosis_engine, incident_engine, notification_engine
from app.remediation.code_pipeline import run_code_remediation
from app.utils.events import bus
from app.utils.time import utcnow

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

DEDUP_WINDOW_MIN = 10


class CrashReportPayload(BaseModel):
    """Strict contract for the TypeScript reporter (Module 1)."""
    service_id: str = Field(min_length=1, max_length=120)
    error_name: str = Field(default="Error", max_length=80)
    message: str = Field(default="", max_length=2000)
    file_path: str = Field(default="", max_length=1000)
    line_number: int = Field(default=0, ge=0, le=10_000_000)
    column_number: int = Field(default=0, ge=0, le=1_000_000)
    stack_trace: str = Field(default="", max_length=20000)
    url: str = Field(default="", max_length=500)
    release: str = Field(default="", max_length=60)
    componentStack: str = Field(default="", max_length=8000)
    userAgent: str = Field(default="", max_length=300)


class TelemetryCrash(BaseModel):
    """Legacy JS-reporter shape (kept working)."""
    service: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="onerror", max_length=40)
    message: str = Field(default="", max_length=2000)
    file: str = Field(default="", max_length=1000)
    line: int = Field(default=0, ge=0)
    column: int = Field(default=0, ge=0)
    stack: str = Field(default="", max_length=20000)
    componentStack: str = Field(default="", max_length=8000)
    url: str = Field(default="", max_length=500)
    userAgent: str = Field(default="", max_length=300)
    release: str = Field(default="", max_length=60)


def _get_or_create_service(db: Session, name: str, url: str) -> Service:
    svc = db.query(Service).filter(Service.name == name).first()
    if svc:
        return svc
    svc = Service(
        name=name, description="auto-registered browser app (telemetry)",
        type="http", health_check_type="http", health_check_url=url,
        health_check_interval=60, restart_policy="never", max_restart_attempts=0,
        auto_remediation=False, ai_diagnosis=True, enabled=True)
    db.add(svc)
    db.flush()
    audit_engine.record(db, "SERVICE_CREATED", service_id=svc.id, actor="telemetry",
                        action="auto-register browser app", result="ok")
    return svc


@router.post("/crash")
async def report_crash(request: dict, background: BackgroundTasks,
                       db: Session = Depends(get_db)):
    """Accept the strict CrashReportPayload (TS reporter) or the legacy shape."""
    payload, file_hint, line = _normalize(request)
    svc = _get_or_create_service(db, payload["service"], payload["url"])
    text = f"{payload['message']}\n{payload['stack']}"
    if payload["componentStack"]:
        text += f"\nComponent stack:{payload['componentStack']}"
    ev = parse_crash(text)

    # flood guard: same fingerprint on an open incident -> attach, don't duplicate
    if ev.fingerprint:
        dupe = (db.query(Incident).filter(
            Incident.service_id == svc.id,
            Incident.fingerprint == ev.fingerprint,
            Incident.status.notin_(["RESOLVED", "FAILED"]),
            Incident.detected_at > utcnow() - timedelta(minutes=DEDUP_WINDOW_MIN))
            .order_by(Incident.id.desc()).first())
        if dupe:
            incident_engine.add_event(db, dupe.id, "CRASH_REPEATED",
                                      f"another browser hit ({payload['url'][:120]})")
            db.commit()
            return {"incident_id": dupe.id, "deduped": True,
                    "fingerprint": ev.fingerprint, "location": ev.location}

    incident = incident_engine.create_incident(
        db, service_id=svc.id, type="frontend", severity="critical",
        error_message=f"[{payload['kind']}] {payload['message'] or 'browser crash'}"[:2000],
        failure_reason=f"url={payload['url']} release={payload['release']} "
                       f"ua={payload['userAgent']}"[:500],
        fingerprint=ev.fingerprint)
    if incident.status == "OPEN":
        incident_engine.transition(db, incident, "INVESTIGATING", message="browser report triaged")
    else:
        # reused an in-progress incident (repeat crash): attach, don't rewind it
        incident_engine.add_event(db, incident.id, "CRASH_REPEATED",
                                  f"further report: {ev.exc_type} {ev.location}"[:300])
    db.add(ServiceLog(
        service_id=svc.id, incident_id=incident.id, stream="browser",
        content=(f"url: {payload['url']}\nfile: {file_hint}:{line}\n"
                 f"stack:\n{payload['stack']}"[:8000])))
    diag = diagnosis_engine.diagnose_rules(db, incident, log_text=text)
    incident_engine.transition(db, incident, "DIAGNOSED", message=f"{diag.source}: {diag.root_cause}")
    audit_engine.record(db, "DIAGNOSIS_COMPLETED", service_id=svc.id,
                        incident_id=incident.id, actor="telemetry",
                        action=f"{diag.source}:{diag.root_cause[:80]}", result="recorded")
    if svc.notifications_enabled:
        notification_engine.notify(
            db, f"Browser crash on {svc.name}",
            f"Incident #{incident.id}\n{ev.exc_type} {ev.location}\n"
            f"Diagnosis: {diag.root_cause}\nURL: {payload['url']}",
            incident_id=incident.id)
    db.commit()
    await bus.publish("incident.created", {"incident_id": incident.id, "service_id": svc.id})
    # code-fix pipeline runs AFTER the response, never blocking telemetry
    background.add_task(run_code_remediation, incident.id, file_hint, line)
    return {"incident_id": incident.id, "deduped": False,
            "status": incident.status, "fingerprint": ev.fingerprint,
            "location": ev.location}


def _normalize(request: dict) -> tuple[dict, str, int]:
    """Strict new payload first, legacy shape second. Returns (fields, file_hint, line)."""
    try:
        p = CrashReportPayload(**request)
        return ({
            "service": p.service_id.strip(), "kind": "telemetry",
            "message": f"{p.error_name}: {p.message}".strip(": "),
            "stack": f"{p.error_name}: {p.message}\n{p.stack_trace}",
            "componentStack": p.componentStack, "url": p.url.strip(),
            "release": p.release, "userAgent": p.userAgent,
        }, p.file_path, p.line_number)
    except Exception:
        pass
    legacy = TelemetryCrash(**request)  # raises 422 if neither shape fits
    return ({
        "service": legacy.service.strip(), "kind": legacy.kind,
        "message": legacy.message, "stack": legacy.stack,
        "componentStack": legacy.componentStack, "url": legacy.url.strip(),
        "release": legacy.release, "userAgent": legacy.userAgent,
    }, legacy.file, legacy.line)
