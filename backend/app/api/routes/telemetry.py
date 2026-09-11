"""Browser crash telemetry: turns client-side failures into AeroOps incidents,
then fires the autonomous code-fix pipeline in the background.

Public by design (browsers can't hold API secrets) but deliberately narrow:
it can ONLY create/dedupe incidents and propose guarded patches. The patch
engine (exact-match + allowlisted verify + backup/rollback) is the execution
gate; nothing runs on a shell, ever.
"""
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Incident, Service, ServiceLog
from app.diagnosis.client_stack import hints_from_stack, primary_hint
from app.diagnosis.stackparse import fingerprint as _fingerprint
from app.diagnosis.stackparse import parse as parse_crash
from app.engines import audit_engine, diagnosis_engine, incident_engine, notification_engine
from app.remediation.code_pipeline import run_client_remediation, run_code_remediation
from app.utils.events import bus
from app.utils.rate_limit import allow as rate_allow
from app.utils.time import utcnow

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

DEDUP_WINDOW_MIN = 10
CLIENT_RATE_LIMIT = 30  # beacon bursts per service+IP per minute
CLIENT_RATE_WINDOW_SEC = 60


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
    if incident.status in ("OPEN", "INVESTIGATING"):
        incident_engine.transition(db, incident, "DIAGNOSED", message=f"{diag.source}: {diag.root_cause}")
    else:
        # reused in-progress incident: record diagnosis without rewinding it
        incident_engine.add_event(db, incident.id, "DIAGNOSIS_COMPLETED",
                                  f"{diag.source}: {diag.root_cause}")
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


# ---------------------------------------------------------------------------
# Public client ingest for live published web apps (Lovable / React+Vite / SPA).
# No operator session: browsers authenticate with the service's public
# client_api_key (beacon-safe) or, for keyless legacy services, the public
# service identifier. Incident-only: can never trigger actions directly; the
# guarded code pipeline runs in the background exactly like /crash.
# ---------------------------------------------------------------------------

def _client_key_from(request: Request, body: dict) -> str:
    header = (request.headers.get("x-api-key")
              or request.headers.get("x-aeroops-key") or "")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        header = header or auth[7:].strip()
    return (header or body.get("apiKey") or body.get("api_key")
            or body.get("client_api_key") or body.get("clientApiKey") or "").strip()


def _find_client_service(db: Session, service_id: str) -> Service | None:
    sid = (service_id or "").strip()
    if not sid:
        return None
    if sid.isdigit():
        svc = db.get(Service, int(sid))
        if svc:
            return svc
    svc = db.query(Service).filter(Service.name == sid).first()
    if svc:
        return svc
    return db.query(Service).filter(Service.client_api_key == sid).first()


def _client_field(body: dict, *names: str, default: str = "") -> str:
    for name in names:
        value = body.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return default


def _client_int(body: dict, *names: str) -> int:
    for name in names:
        try:
            return max(0, int(body.get(name) or 0))
        except (TypeError, ValueError):
            continue
    return 0


@router.post("/client")
async def report_client_crash(request: Request, background: BackgroundTasks,
                              db: Session = Depends(get_db)):
    """Beacon ingest for published web apps. Public, key-or-identifier authed."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="invalid JSON body")
    service_id = (_client_field(body, "serviceId", "service_id", "service"))
    if not service_id:
        raise HTTPException(status_code=422, detail="serviceId is required")
    svc = _find_client_service(db, service_id)
    if not svc:
        raise HTTPException(status_code=404, detail="unknown serviceId")
    provided = _client_key_from(request, body)
    stored = (svc.client_api_key or "").strip()
    if stored and provided != stored and service_id.strip() != stored:
        raise HTTPException(status_code=401, detail="invalid client_api_key")

    ip = request.client.host if request.client else "unknown"
    ok, retry = rate_allow(f"client:{svc.id}:{ip}", limit=CLIENT_RATE_LIMIT,
                           window_sec=CLIENT_RATE_WINDOW_SEC)
    if not ok:
        raise HTTPException(status_code=429, detail="telemetry rate limit exceeded",
                            headers={"Retry-After": str(retry)})

    error_name = _client_field(body, "error_name", "errorName", "name", default="Error")[:80]
    message = _client_field(body, "message", "error_message")[:2000]
    stack_trace = _client_field(body, "stack_trace", "stackTrace", "stack")[:20000]
    file_path = _client_field(body, "file_path", "filePath", "file")[:1000]
    line = _client_int(body, "line_number", "lineNumber", "line")
    column = _client_int(body, "column_number", "columnNumber", "column")
    url = _client_field(body, "url", "pageUrl", "page_url", "route")[:500]
    user_agent = _client_field(body, "userAgent", "user_agent", "ua")[:300]
    component_stack = _client_field(body, "componentStack", "component_stack")[:8000]
    release = _client_field(body, "release", "version")[:60]
    occurred_at = _client_field(body, "timestamp", "occurredAt", "occurred_at")[:40]

    hint = primary_hint(stack_trace, file_path=file_path, line=line, column=column)
    file_hint, line_no = (hint.file_hint, hint.line) if hint.file_hint else (file_path, line)
    text = f"{error_name}: {message}\n{stack_trace}"
    if component_stack:
        text += f"\nComponent stack:{component_stack}"
    ev = parse_crash(text)
    if not ev.exc_type:
        ev.exc_type = error_name
    if not ev.exc_msg:
        ev.exc_msg = message[:500]
    if not ev.fingerprint:
        ev.fingerprint = _fingerprint(f"{ev.exc_type}|{message}", None)

    if ev.fingerprint:
        dupe = (db.query(Incident).filter(
            Incident.service_id == svc.id,
            Incident.fingerprint == ev.fingerprint,
            Incident.status.notin_(["RESOLVED", "FAILED"]),
            Incident.detected_at > utcnow() - timedelta(minutes=DEDUP_WINDOW_MIN))
            .order_by(Incident.id.desc()).first())
        if dupe:
            incident_engine.add_event(db, dupe.id, "CLIENT_CRASH_REPEATED",
                                      f"live hit at {url[:120] or svc.published_url[:120]}")
            db.commit()
            return {"incident_id": dupe.id, "deduped": True,
                    "fingerprint": ev.fingerprint, "location": ev.location,
                    "file_hint": file_hint}

    origin = url or svc.published_url or ""
    incident = incident_engine.create_incident(
        db, service_id=svc.id, type="frontend", severity="critical",
        error_message=f"[client] {error_name}: {message or 'browser crash'}"[:2000],
        failure_reason=f"origin={origin} route={url} release={release} "
                       f"ua={user_agent} at={occurred_at}"[:500],
        fingerprint=ev.fingerprint)
    if incident.status == "OPEN":
        incident_engine.transition(db, incident, "INVESTIGATING", message="live browser report triaged")
    else:
        incident_engine.add_event(db, incident.id, "CLIENT_CRASH_REPEATED",
                                  f"further live report: {ev.exc_type} {ev.location}"[:300])
    db.add(ServiceLog(
        service_id=svc.id, incident_id=incident.id, stream="browser-client",
        content=(f"origin: {origin}\nfile: {file_hint}:{line_no}\n"
                 f"component stack:\n{component_stack[:2000]}\n"
                 f"stack:\n{stack_trace}"[:8000])))
    diag = diagnosis_engine.diagnose_rules(db, incident, log_text=text)
    if incident.status in ("OPEN", "INVESTIGATING"):
        incident_engine.transition(db, incident, "DIAGNOSED", message=f"{diag.source}: {diag.root_cause}")
    else:
        incident_engine.add_event(db, incident.id, "DIAGNOSIS_COMPLETED",
                                  f"{diag.source}: {diag.root_cause}")
    audit_engine.record(db, "DIAGNOSIS_COMPLETED", service_id=svc.id,
                        incident_id=incident.id, actor="client-telemetry",
                        action=f"{diag.source}:{diag.root_cause[:80]}", result="recorded")
    if svc.notifications_enabled:
        notification_engine.notify(
            db, f"Live crash on {svc.name}",
            f"Incident #{incident.id}\n{ev.exc_type} {ev.location or file_hint}\n"
            f"Diagnosis: {diag.root_cause}\nOrigin: {origin}",
            incident_id=incident.id)
    db.commit()
    await bus.publish("incident.created", {"incident_id": incident.id, "service_id": svc.id})
    # autonomous fix runs AFTER the response, never blocking the beacon
    hints = [{"file_hint": h.file_hint, "line": h.line, "column": h.column}
             for h in hints_from_stack(stack_trace, file_path=file_path,
                                       line=line, column=column)]
    background.add_task(run_client_remediation, incident.id, hints or
                        [{"file_hint": file_hint, "line": line_no, "column": 0}])
    return {"incident_id": incident.id, "deduped": False,
            "status": incident.status, "fingerprint": ev.fingerprint,
            "location": ev.location, "file_hint": file_hint}
