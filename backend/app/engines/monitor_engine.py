"""Monitor engine: MONITOR->DETECT->CAPTURE->DIAGNOSE->DECIDE->REMEDIATE->RESTART
->VERIFY->RECOVER->RECORD->NOTIFY. Runs as an asyncio background task; never
blocks request threads. Every step is audited; failures isolate per-service."""

import asyncio
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import sanitize_log
from app.db.database import SessionLocal
from app.db.models import Service, ServiceLog
from app.engines import (audit_engine, diagnosis_engine, health_engine,
                         incident_engine, metrics_engine, notification_engine,
                         remediation_engine, restart_manager)
from app.engines.restart_manager import PROJECT_ROOT
from app.remediation import policies
from app.utils.events import bus

log = get_logger("monitor")
_fail_streak: dict[int, int] = {}
_last_probe: dict[int, float] = {}
_last_restart: dict[int, float] = {}


def _capture_logs(db: Session, service: Service, incident_id: int) -> str:
    """Tail the service output file into bounded ServiceLog rows. Returns combined text."""
    path = PROJECT_ROOT / f".run-{service.id}.log"
    try:
        text = path.read_text(errors="replace")[-20000:] if path.exists() else ""
    except Exception as exc:
        text = f"<log unavailable: {exc}>"
    text = sanitize_log(text)
    tail = text[-8000:]
    if tail:
        db.add(ServiceLog(service_id=service.id, incident_id=incident_id,
                          stream="stdout", content=tail))
        db.flush()
    return tail


async def _set_status(db: Session, service: Service, status: str) -> None:
    if service.status != status:
        service.status = status
        db.flush()
        await bus.publish("service.status", {"service_id": service.id, "status": status})


async def _handle_failure(service_id: int, *, error: str, exit_code=None,
                          log_hint: str = "") -> None:
    db: Session = SessionLocal()
    try:
        service = db.get(Service, service_id)
        if not service or not service.enabled:
            return
        await _set_status(db, service, "CRASHED")
        # CAPTURE + INCIDENT
        incident = incident_engine.create_incident(
            db, service_id=service.id, type="crash",
            severity="critical", error_message=error, exit_code=exit_code,
            failure_reason=error[:500])
        incident_engine.transition(db, incident, "INVESTIGATING", message="analysis started")
        await bus.publish("incident.created", {"incident_id": incident.id, "service_id": service.id})
        tail = _capture_logs(db, service, incident.id) or log_hint
        incident_engine.add_event(db, incident.id, "LOGS_CAPTURED",
                                  f"captured {len(tail)} chars of output")
        # DIAGNOSE: rules instantly on the critical path; AI enriches in background
        diag = diagnosis_engine.diagnose_rules(db, incident, log_text=tail)
        incident_engine.transition(db, incident, "DIAGNOSED", message=f"{diag.source}: {diag.root_cause}")
        await bus.publish("diagnosis.completed", {"incident_id": incident.id, "cause": diag.root_cause})
        if service.ai_diagnosis:
            asyncio.create_task(diagnosis_engine.enrich_ai(incident.id, {
                "service": service.name, "error": incident.error_message,
                "exit_code": incident.exit_code, "rule_cause": diag.root_cause,
                "logs": tail[-1500:]}))
        # DECIDE + REMEDIATE under policy
        decision = policies.evaluate(diag.recommended_action,
                                     auto_remediation=service.auto_remediation,
                                     risk_level=diag.risk_level)
        incident_engine.add_event(db, incident.id, "REMEDIATION_DECISION",
                                  f"{diag.recommended_action}: {'allowed' if decision.allowed else 'denied'} — {decision.reason}")
        restarted = False
        if decision.allowed and service.restart_policy != "never" and \
                incident.restart_attempts < service.max_restart_attempts:
            if time.time() - _last_restart.get(service.id, 0) < service.cooldown_sec:
                incident_engine.add_event(db, incident.id, "COOLDOWN", "restart deferred: cooldown active")
            else:
                incident_engine.transition(db, incident, "REMEDIATING",
                                           message=f"executing {diag.recommended_action}")
                await _set_status(db, service, "RESTARTING")
                incident.restart_attempts += 1
                service.restart_count += 1
                _last_restart[service.id] = time.time()
                audit_engine.record(db, "RESTART_ATTEMPTED", service_id=service.id,
                                    incident_id=incident.id, action=diag.recommended_action,
                                    result=f"attempt {incident.restart_attempts}")
                await bus.publish("restart.started", {"incident_id": incident.id})
                action = await remediation_engine.execute(
                    db, incident, diag.recommended_action,
                    source="automation", params={"risk_level": diag.risk_level})
                restarted = action.status == "succeeded"
                audit_engine.record(db, "RESTART_SUCCEEDED" if restarted else "RESTART_FAILED",
                                    service_id=service.id, incident_id=incident.id,
                                    result=action.result or action.error)
        elif incident.restart_attempts >= service.max_restart_attempts:
            incident_engine.add_event(db, incident.id, "RESTART_LIMIT",
                                      f"max attempts ({service.max_restart_attempts}) reached")
        # VERIFY: N consecutive healthy checks
        if restarted:
            incident_engine.transition(db, incident, "RECOVERING", message="verifying recovery")
            await _set_status(db, service, "RECOVERING")
            db.commit()  # make restart visible before slow verify
            ok = await restart_manager.wait_healthy(lambda: _healthy(service.id))
            if ok:
                await _set_status(db, service, "RECOVERED")
                incident.recovery_verified = True
                audit_engine.record(db, "RECOVERY_VERIFIED", service_id=service.id,
                                    incident_id=incident.id, result="healthy x N")
                incident_engine.transition(db, incident, "RESOLVED", message="recovery verified")
                audit_engine.record(db, "INCIDENT_RESOLVED", service_id=service.id,
                                    incident_id=incident.id,
                                    result=f"{incident.duration_sec:.1f}s" if incident.duration_sec else "")
                await bus.publish("service.recovered", {"incident_id": incident.id, "service_id": service.id})
            else:
                await _set_status(db, service, "CRASHED")
                incident_engine.transition(db, incident, "FAILED", message="recovery verification failed")
        else:
            if incident.restart_attempts >= service.max_restart_attempts and \
                    service.restart_policy != "never":
                try:
                    incident_engine.transition(db, incident, "FAILED", message="restart budget exhausted")
                except Exception:
                    pass
        # NOTIFY (never fatal)
        try:
            if service.notifications_enabled:
                state = "RECOVERED" if incident.recovery_verified else incident.status
                notification_engine.notify(
                    db, f"Service {service.name} crashed — {state}",
                    f"Incident #{incident.id}\nDiagnosis: {diag.root_cause}\n"
                    f"Action: {diag.recommended_action}\nResult: {state}\n"
                    f"Recovery time: {incident.duration_sec or 0:.1f}s",
                    incident_id=incident.id)
                await bus.publish("notification", {"incident_id": incident.id})
        except Exception as exc:
            log.info(f"notify failed (non-fatal): {exc}")
        db.commit()
    except Exception as exc:
        db.rollback()
        log.info(f"failure handler isolated error for service {service_id}: {exc}")
        # never strand a service mid-flight: release it so the next tick retries
        # (restart budget still guards against infinite loops)
        try:
            svc = db.get(Service, service_id)
            if svc and svc.status in ("RESTARTING", "RECOVERING"):
                svc.status = "UNKNOWN"
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


async def _healthy(service_id: int) -> bool:
    db: Session = SessionLocal()
    try:
        service = db.get(Service, service_id)
        if not service:
            return False
        snap = await health_engine.check(service)
        return bool(snap["ok"])
    finally:
        db.close()


async def _tick() -> None:
    db: Session = SessionLocal()
    try:
        services = db.query(Service).filter(Service.enabled.is_(True)).all()
        for service in services:
            interval = service.health_check_interval or settings.default_health_interval
            if time.time() - _last_probe.get(service.id, 0) < interval:
                continue
            _last_probe[service.id] = time.time()
            try:
                snap = await health_engine.check(service)
            except Exception as exc:
                log.info(f"probe isolated error svc={service.id}: {exc}")
                continue
            info = restart_manager.proc_info(service.pid)
            metrics_engine.record(db, service.id, cpu=info["cpu"], mem_mb=info["mem_mb"],
                                  response_ms=snap.get("response_ms"), status=snap["status"])
            db.commit()
            if snap["ok"]:
                _fail_streak[service.id] = 0
                if service.status in ("CRASHED", "UNHEALTHY", "UNKNOWN", "RECOVERED"):
                    await _set_status(db, service,
                                "HEALTHY" if service.status != "RECOVERED" else "RECOVERED")
                    db.commit()
                await bus.publish("metrics", {"service_id": service.id, **info,
                                              "response_ms": snap.get("response_ms")})
            else:
                _fail_streak[service.id] = _fail_streak.get(service.id, 0) + 1
                if _fail_streak[service.id] >= 2 and service.status not in ("CRASHED", "RESTARTING", "RECOVERING"):
                    await _set_status(db, service, "UNHEALTHY" if service.health_check_type == "http" else "CRASHED")
                    db.commit()
                    code = restart_manager.exit_code(service.id)
                    await _handle_failure(service.id, error=snap["detail"], exit_code=code)
    except Exception as exc:
        log.info(f"monitor tick isolated error: {exc}")
    finally:
        db.close()


async def run_forever() -> None:
    log.info("monitor engine started")
    while True:
        await _tick()
        await asyncio.sleep(1)
