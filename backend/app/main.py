"""AeroOps FastAPI application: lifespan starts monitor engine + seeds demo services."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import events
from app.api.routes import actions, auth, demo, delivery, incidents, ops, sdk, services, telemetry
from app.core.config import settings
from app.core.exceptions import AeroOpsError, aeroops_error_handler
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.db.database import SessionLocal, init_db
from app.engines import monitor_engine

log = get_logger("app")
_monitor_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed()
    global _monitor_task
    if settings.monitor_enabled:
        _monitor_task = asyncio.create_task(monitor_engine.run_forever())
        log.info("AeroOps started (monitor engine online)")
    else:
        log.info("AeroOps started (monitor engine DISABLED)")
    yield
    if _monitor_task:
        _monitor_task.cancel()


def _seed() -> None:
    """Register demo services on first boot; re-queue stale incidents from a hard stop."""
    from app.db.models import Incident, Service
    from app.engines import audit_engine, incident_engine
    db = SessionLocal()
    try:
        if settings.seed_demos and db.query(Service).count() == 0:
            demos = [
                Service(name="healthy-service", description="Always-on demo (Python http.server)",
                        type="process", command="python -m http.server 4101",
                        working_directory="demo-services/healthy-service",
                        health_check_type="http", health_check_url="http://localhost:4101",
                        max_restart_attempts=3),
                Service(name="crash-service", description="Node demo with /crash endpoint (reused legacy server)",
                        type="process", command="node server.js",
                        working_directory="demo-services/crash-service",
                        health_check_type="http", health_check_url="http://localhost:3000/health",
                        max_restart_attempts=3),
            ]
            for svc in demos:
                db.add(svc)
            db.commit()
            audit_engine.record(db, "SERVICE_CREATED", actor="seed", action="seed demos", result="ok")
        # warm recovery: anything left mid-flight by a hard stop goes back to OPEN
        stale = db.query(Incident).filter(
            Incident.status.in_(["INVESTIGATING", "DIAGNOSED", "REMEDIATING", "RECOVERING"])).all()
        for inc in stale:
            incident_engine.add_event(db, inc.id, "WARM_RESTART",
                                      f"re-queued from {inc.status} after supervisor restart")
            inc.status = "OPEN"
        # ...and services stuck mid-flight get re-probed from scratch
        for svc in db.query(Service).filter(
                Service.status.in_(["RESTARTING", "RECOVERING"])).all():
            svc.status = "UNKNOWN"
        if stale:
            audit_engine.record(db, "INCIDENT_UPDATED", actor="seed",
                                action=f"re-queued {len(stale)} stale incidents", result="ok")
        db.commit()
    finally:
        db.close()


app = FastAPI(title="AeroOps", version="2.1.0", lifespan=lifespan)
app.add_exception_handler(AeroOpsError, aeroops_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

authed = [Depends(get_current_user)]
app.include_router(auth.router)  # register/login stay public by design
app.include_router(sdk.router)  # browser SDK: public static snippet, no auth
app.include_router(telemetry.router)  # browser ingest: public but incident-only, never acts
app.include_router(services.router, dependencies=authed)
app.include_router(incidents.router, dependencies=authed)
app.include_router(ops.router, dependencies=authed)
app.include_router(actions.router, dependencies=authed)
app.include_router(demo.router, dependencies=authed)
app.include_router(delivery.router, dependencies=authed)
app.include_router(events.router, dependencies=authed)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "aeroops"}
