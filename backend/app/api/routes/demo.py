"""Failure simulation: crash a running demo service on demand (safe chaos button)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions import NotFound
from app.core.security import require_role
from app.db.database import get_db
from app.db.models import Service
from app.engines import restart_manager

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/simulate-failure")
def simulate_failure(service_id: int, db: Session = Depends(get_db),
                     user: dict = Depends(require_role("admin", "operator"))):
    svc = db.get(Service, service_id)
    if not svc:
        raise NotFound("service not found")
    # Kill the process abruptly: monitor detects -> incident -> diagnose -> restart -> verify.
    proc = restart_manager._processes.get(service_id)
    if proc and proc.poll() is None:
        proc.kill()
        return {"killed": True, "pid": proc.pid}
    # http-type demo without process: rely on its own /crash endpoint if configured
    return {"killed": False, "detail": "service has no running process; use its /crash endpoint"}
