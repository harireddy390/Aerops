"""Service registry + lifecycle controls."""
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions import NotFound
from app.core.security import require_role, safe_workdir, split_command
from app.db.database import get_db
from app.db.models import Service
from app.engines import audit_engine, restart_manager
from app.engines.restart_manager import PROJECT_ROOT
from app.schemas import ServiceCreate, ServiceOut, ServiceUpdate

router = APIRouter(prefix="/api/services", tags=["services"])


def _out(s: Service) -> ServiceOut:
    return ServiceOut.model_validate(s)


@router.get("", response_model=list[ServiceOut])
def list_services(db: Session = Depends(get_db)):
    return [_out(s) for s in db.query(Service).order_by(Service.id).all()]


@router.post("", response_model=ServiceOut, status_code=201)
def create_service(payload: ServiceCreate, db: Session = Depends(get_db),
                   user: dict = Depends(require_role("admin", "operator"))):
    if payload.command:
        split_command(payload.command)  # validate now, fail fast
    safe_workdir(payload.working_directory, Path(PROJECT_ROOT))
    if db.query(Service).filter(Service.name == payload.name).first():
        from app.core.exceptions import Conflict
        raise Conflict(f"service '{payload.name}' already exists")
    svc = Service(**payload.model_dump())
    db.add(svc)
    db.commit()
    db.refresh(svc)
    audit_engine.record(db, "SERVICE_CREATED", service_id=svc.id, actor=user["username"],
                        action="create", result="ok")
    db.commit()
    return _out(svc)


@router.get("/{service_id}", response_model=ServiceOut)
def get_service(service_id: int, db: Session = Depends(get_db)):
    svc = db.get(Service, service_id)
    if not svc:
        raise NotFound("service not found")
    return _out(svc)


@router.put("/{service_id}", response_model=ServiceOut)
def update_service(service_id: int, payload: ServiceUpdate, db: Session = Depends(get_db),
                   _: dict = Depends(require_role("admin", "operator"))):
    svc = db.get(Service, service_id)
    if not svc:
        raise NotFound("service not found")
    data = payload.model_dump(exclude_unset=True)
    if "command" in data and data["command"]:
        split_command(data["command"])
    if "working_directory" in data:
        safe_workdir(data["working_directory"], Path(PROJECT_ROOT))
    for key, value in data.items():
        setattr(svc, key, value)
    db.commit()
    db.refresh(svc)
    return _out(svc)


@router.delete("/{service_id}", status_code=204)
def delete_service(service_id: int, db: Session = Depends(get_db),
                   user: dict = Depends(require_role("admin", "operator"))):
    svc = db.get(Service, service_id)
    if not svc:
        raise NotFound("service not found")
    restart_manager.stop(svc.id)
    audit_engine.record(db, "SERVICE_STOPPED", service_id=svc.id, actor=user["username"],
                        action="delete", result="ok")
    db.delete(svc)
    db.commit()
    return None


@router.post("/{service_id}/start")
def start_service(service_id: int, db: Session = Depends(get_db),
                  user: dict = Depends(require_role("admin", "operator"))):
    svc = db.get(Service, service_id)
    if not svc:
        raise NotFound("service not found")
    # desired state: watched again from now on
    svc.enabled = True
    pid = None
    if svc.command:
        pid = restart_manager.start(svc.id, svc.command, svc.working_directory, svc.env_config or {})
        svc.pid = pid
    svc.status = "UNKNOWN"  # monitor evaluates on next probe; never assumed healthy
    audit_engine.record(db, "SERVICE_STARTED", service_id=svc.id, actor=user["username"],
                        action="start", result=f"pid={pid}" if pid else "watching resumed")
    db.commit()
    return {"pid": pid, "status": svc.status}


@router.post("/{service_id}/stop")
def stop_service(service_id: int, db: Session = Depends(get_db),
                 user: dict = Depends(require_role("admin", "operator"))):
    svc = db.get(Service, service_id)
    if not svc:
        raise NotFound("service not found")
    # desired state: stopped. Monitor skips disabled services, so unlike a
    # crash this never triggers incidents or restarts until Start resumes it.
    try:
        restart_manager.stop(svc.id)
    except Exception:
        pass
    svc.pid = None
    svc.enabled = False
    svc.status = "STOPPED"
    audit_engine.record(db, "SERVICE_STOPPED", service_id=svc.id, actor=user["username"], action="stop", result="ok")
    db.commit()
    return {"status": svc.status}


@router.post("/{service_id}/restart")
def restart_service(service_id: int, db: Session = Depends(get_db),
                    user: dict = Depends(require_role("admin", "operator"))):
    svc = db.get(Service, service_id)
    if not svc:
        raise NotFound("service not found")
    restart_manager.stop(svc.id)
    pid = restart_manager.start(svc.id, svc.command, svc.working_directory, svc.env_config or {})
    svc.pid = pid
    svc.enabled = True
    svc.status = "UNKNOWN"  # monitor confirms on next probe
    svc.restart_count += 1
    audit_engine.record(db, "RESTART_SUCCEEDED", service_id=svc.id, actor=user["username"],
                        action="manual-restart", result=f"pid={pid}")
    db.commit()
    return {"pid": pid, "status": svc.status}


@router.get("/{service_id}/metrics")
def service_metrics(service_id: int, limit: int = 120, db: Session = Depends(get_db)):
    if not db.get(Service, service_id):
        raise NotFound("service not found")
    from app.engines import metrics_engine
    rows = metrics_engine.series(db, service_id, limit)
    return [{"cpu": r.cpu_pct, "mem_mb": r.mem_mb, "response_ms": r.response_ms,
             "status": r.status, "t": r.timestamp.isoformat()} for r in rows]


@router.get("/{service_id}/logs")
def service_logs(service_id: int, limit: int = 100, db: Session = Depends(get_db)):
    if not db.get(Service, service_id):
        raise NotFound("service not found")
    from app.db.models import ServiceLog
    rows = (db.query(ServiceLog).filter(ServiceLog.service_id == service_id)
            .order_by(ServiceLog.id.desc()).limit(min(limit, 500)).all()[::-1])
    return [{"stream": r.stream, "content": r.content[-4000:], "t": r.timestamp.isoformat(),
             "incident_id": r.incident_id} for r in rows]
