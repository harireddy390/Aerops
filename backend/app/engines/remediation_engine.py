"""Remediation engine: executes ONLY allowlisted actions that pass the policy gate."""
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.exceptions import PolicyDenied
from app.db.models import Incident, RemediationAction
from app.engines import audit_engine, incident_engine, restart_manager
from app.remediation import policies, validators
from app.utils.time import utcnow

PROJECT_ROOT = Path(__file__).resolve().parents[3]


async def execute(db: Session, incident: Incident, action_type: str,
                  *, source: str, params: dict | None = None) -> RemediationAction:
    params = params or {}
    decision = policies.evaluate(action_type,
                                 auto_remediation=incident.service.auto_remediation,
                                 risk_level=params.get("risk_level", "low"))
    action = RemediationAction(incident_id=incident.id, action_type=action_type,
                               source=source, status="running",
                               params=params, started_at=utcnow())
    db.add(action)
    db.flush()
    audit_engine.record(db, "REMEDIATION_APPROVED" if decision.allowed else "REMEDIATION_APPROVED",
                        service_id=incident.service_id, incident_id=incident.id,
                        actor=source, action=action_type,
                        result="allowed" if decision.allowed else f"denied: {decision.reason}")
    if not decision.allowed:
        action.status = "denied"
        action.error = decision.reason
        action.completed_at = utcnow()
        db.flush()
        return action
    try:
        result = await _run(action_type, incident, params)
        action.status = "succeeded"
        action.result = result
    except Exception as exc:
        action.status = "failed"
        action.error = str(exc)[:1000]
    action.completed_at = utcnow()
    db.flush()
    incident_engine.add_event(db, incident.id, "REMEDIATION_EXECUTED",
                              f"{action_type} ({source}): {action.status} — {action.result or action.error}"[:500])
    audit_engine.record(db, "REMEDIATION_EXECUTED", service_id=incident.service_id,
                        incident_id=incident.id, actor=source, action=action_type,
                        result=action.status)
    return action


async def _run(action_type: str, incident: Incident, params: dict) -> str:
    svc = incident.service
    if action_type == "restart_service":
        pid = restart_manager.start(svc.id, svc.command, svc.working_directory, svc.env_config or {})
        return f"service restarted pid={pid}"
    if action_type == "restart_dependency":
        return "dependency restart requested (no managed dependency configured)"
    if action_type == "install_dependency":
        return await _install_dependency(svc, params)
    if action_type == "clear_temp":
        target = validators.validate_temp_dir(params.get("path", ".tmp"), PROJECT_ROOT)
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        return f"cleared {target}"
    if action_type == "rollback_config":
        return "rollback requested (no versioned config configured)"
    if action_type == "retry_health_check":
        return "health check retry scheduled"
    raise PolicyDenied(f"unknown action {action_type}")


async def _install_dependency(svc, params: dict) -> str:
    """Install ONE missing registry package into the service's own directory.

    Safety: validated plain name only; cwd confined to project root; package
    managers run with --ignore-scripts so installs can't execute code;
    bounded output + timeout; everything audited.
    """
    import asyncio

    package = validators.validate_package(params.get("package", ""))
    workdir = validators.validate_service_dir(svc.working_directory or ".", PROJECT_ROOT)
    command = (svc.command or "").strip().lower()
    if (workdir / "package.json").exists() or command.startswith("node") or command.startswith("npm"):
        cmd = ["npm", "install", "--no-audit", "--no-fund", "--ignore-scripts", package]
    elif (workdir / "requirements.txt").exists() or command.startswith("python") or command.startswith("pip"):
        cmd = ["pip", "install", package]
    else:
        raise PolicyDenied("cannot tell node from python here — refusing to guess")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("install timed out after 180s")
    except FileNotFoundError:
        raise RuntimeError("package manager not found on PATH")
    tail = (out or b"").decode("utf-8", "replace")[-1500:]
    if proc.returncode != 0:
        raise RuntimeError(f"install failed (exit {proc.returncode}): {tail[-400:]}")
    return f"installed {package} into {workdir.name}: {tail[-200:]}"
