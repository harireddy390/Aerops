"""Code-remediation pipeline: crash report -> isolated Git branch -> AI-proposed
surgical patch -> two-tier verification (+reflexion retries) -> delivery gate
(AUTO_MERGE or DRAFT_PR). Non-git services keep the legacy .bak flow.

Runs in the background, never blocks telemetry. Every gate failure records an
event and notifies a human instead of touching code.
"""
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import Incident, RemediationAction
from app.diagnosis.code_diagnosis_agent import propose_fix
from app.diagnosis.reflexion_agent import propose_with_reflexion
from app.engines import audit_engine, incident_engine, notification_engine
from app.engines.restart_manager import PROJECT_ROOT
from app.remediation import delivery_gate, git_workspace, policies
from app.remediation.safe_patcher import apply_patch, read_context, resolve_target
from app.remediation.test_harness import verify as harness_verify
from app.utils.events import bus
from app.utils.time import utcnow


def _language(target: Path) -> str:
    return {"py": "python", "js": "javascript", "jsx": "javascript",
            "ts": "typescript", "tsx": "typescript"}.get(target.suffix.lstrip(".").lower(), "unknown")


def _service_dir(svc) -> Path:
    return (PROJECT_ROOT / (svc.working_directory or ".")).resolve()


async def run_code_remediation(incident_id: int, file_hint: str, line: int) -> None:
    db: Session = SessionLocal()
    try:
        incident = db.get(Incident, incident_id)
        if not incident:
            return
        svc = incident.service
        # Gate: code fixes run when the service opts into automation, OR for
        # browser-reported frontend crashes (this path never restarts anything).
        if not svc.auto_remediation and incident.type != "frontend":
            incident_engine.add_event(db, incident.id, "CODEFIX_SKIPPED",
                                      "auto-remediation disabled for this service")
            db.commit()
            return
        repo = _service_dir(svc)
        target = resolve_target(Path(svc.working_directory or "."), PROJECT_ROOT, file_hint)
        if not target:
            incident_engine.add_event(db, incident.id, "CODEFIX_UNRESOLVABLE",
                                      f"could not map '{file_hint[:120]}' to one local file")
            _notify_human(db, incident, "Could not locate the crashing file",
                          f"Hint was '{file_hint[:200]}'. Fix it by hand.")
            db.commit()
            return
        can_auto = svc.auto_remediation or incident.type == "frontend"
        decision = policies.evaluate("apply_code_patch",
                                     auto_remediation=can_auto,
                                     risk_level="medium")
        if not decision.allowed:
            incident_engine.add_event(db, incident.id, "CODEFIX_DENIED", decision.reason)
            _notify_human(db, incident, "Patch blocked by safety policy", decision.reason)
            db.commit()
            return
        context = read_context(target, max(line, 1))
        error = f"{incident.error_message}"
        if git_workspace.is_repo(repo):
            await _git_flow(db, incident, svc, target, context, error, file_hint, line)
        else:
            await _legacy_flow(db, incident, svc, target, context, error)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


async def _git_flow(db: Session, incident: Incident, svc, target: Path,
                    context: str, error: str, file_hint: str, line: int) -> None:
    repo = _service_dir(svc)
    try:
        ws = await git_workspace.open_workspace(
            repo, incident.id, incident.fingerprint or "manual")
    except RuntimeError as exc:
        incident_engine.add_event(db, incident.id, "CODEFIX_NO_WORKSPACE", str(exc)[:300])
        _notify_human(db, incident, "Repo not ready for auto-fix", str(exc)[:500])
        return
    incident_engine.add_event(db, incident.id, "CODEFIX_BRANCH",
                              f"isolated on {ws.branch} (base {ws.base_ref[:8]})")

    async def propose_first():
        return await propose_fix(file_path=str(target), language=_language(target),
                                 error=error, context_block=context)

    async def try_patch(proposal):
        applied = _write_exact(target, proposal.search_block, proposal.replacement_block)
        if not applied[0]:
            return False, applied[1]
        report = await harness_verify(target)
        if report.ok:
            return True, "syntax + scoped tests green"
        return False, report.failure_text

    proposal, provider, outcome = await propose_with_reflexion(
        propose_first, error=error, context_block=context, try_patch=try_patch)
    if outcome != "verified" or not proposal:
        await git_workspace.abandon(ws)
        try:
            incident_engine.transition(db, incident, "ESCALATED_MANUAL",
                                       message="reflexion exhausted — needs a human")
        except Exception:
            pass
        incident_engine.add_event(db, incident.id, "CODEFIX_ESCALATED",
                                  "2 reflexion rounds failed; branch removed, tree intact")
        audit_engine.record(db, "REMEDIATION_EXECUTED", service_id=svc.id,
                            incident_id=incident.id, actor="automation",
                            action="apply_code_patch", result="escalated")
        _notify_human(db, incident, "Auto-fix needs a human",
                      "Two AI revisions failed verification; nothing was merged.")
        return

    ok, diff_stat = await git_workspace.commit_fix(
        ws, incident_id=incident.id, fingerprint=incident.fingerprint or "manual",
        root_cause=proposal.root_cause, model=provider)
    if not ok:
        await git_workspace.abandon(ws)
        incident_engine.add_event(db, incident.id, "CODEFIX_FAILED", diff_stat[:300])
        return
    action = RemediationAction(incident_id=incident.id, action_type="apply_code_patch",
                               source="automation", status="succeeded",
                               params={"file": str(target), "provider": provider,
                                       "branch": ws.branch, "diff": diff_stat},
                               result=f"{provider}: {proposal.root_cause}"[:1000],
                               started_at=utcnow(), completed_at=utcnow())
    db.add(action)
    db.flush()
    incident_engine.add_event(db, incident.id, "CODEFIX_APPLIED",
                              f"verified on {ws.branch} ({provider})")
    audit_engine.record(db, "REMEDIATION_EXECUTED", service_id=svc.id,
                        incident_id=incident.id, actor="automation",
                        action="apply_code_patch", result="succeeded")
    mode = (svc.policy_mode or "DRAFT_PR").upper()
    deploy_branch = svc.deploy_branch or await git_workspace.current_branch(repo) or "main"
    if mode == "AUTO_MERGE":
        await delivery_gate.deliver_merged(db, ws, incident=incident,
                                           deploy_branch=deploy_branch,
                                           test_results="syntax + scoped regression green")
    else:
        await delivery_gate.deliver_draft_pr(
            db, ws, incident=incident, root_cause=proposal.root_cause,
            stack=incident.error_message,
            test_results="syntax + scoped regression green", diff_stat=diff_stat)


async def _legacy_flow(db: Session, incident: Incident, svc, target: Path,
                       context: str, error: str) -> None:
    """Non-git services: original .bak backup flow (unchanged behavior)."""
    proposal, provider = await propose_fix(
        file_path=str(target), language=_language(target), error=error,
        context_block=context)
    if not proposal:
        incident_engine.add_event(db, incident.id, "CODEFIX_NO_PROPOSAL",
                                  "AI could not propose a safe surgical fix")
        _notify_human(db, incident, "No safe auto-fix found",
                      f"Crash at {target.name}. Needs a human.")
        return
    incident_engine.add_event(
        db, incident.id, "CODEFIX_PROPOSED",
        f"{provider}: {proposal.root_cause} — applying guarded patch "
        f"(verify: {proposal.verification_command})"[:500])
    action = RemediationAction(incident_id=incident.id, action_type="apply_code_patch",
                               source="automation", status="running",
                               params={"file": str(target), "provider": provider,
                                       "verify": proposal.verification_command})
    db.add(action)
    db.flush()
    result = await apply_patch(
        target=target, search_block=proposal.search_block,
        replacement_block=proposal.replacement_block,
        verification_command=proposal.verification_command,
        cwd=target.parent, project_root=PROJECT_ROOT)
    action.completed_at = utcnow()
    if result.ok:
        action.status = "succeeded"
        action.result = f"{provider}: {proposal.root_cause} — {result.detail}"[:1000]
        incident_engine.add_event(db, incident.id, "CODEFIX_APPLIED",
                                  f"verified patch in {target.name} ({provider})")
        audit_engine.record(db, "REMEDIATION_EXECUTED", service_id=svc.id,
                            incident_id=incident.id, actor="automation",
                            action="apply_code_patch", result="succeeded")
        notification_engine.notify(
            db, f"Code fixed on {svc.name}",
            f"Incident #{incident.id}\nCause: {proposal.root_cause}\n"
            f"File: {target.name}\nVerified: {proposal.verification_command}\n"
            f"Provider: {provider}",
            incident_id=incident.id)
        await bus.publish("notification", {"incident_id": incident.id})
    else:
        action.status = "failed"
        action.error = result.detail[:1000]
        incident_engine.add_event(db, incident.id, "CODEFIX_FAILED", result.detail[:500])
        audit_engine.record(db, "REMEDIATION_EXECUTED", service_id=svc.id,
                            incident_id=incident.id, actor="automation",
                            action="apply_code_patch", result="failed")
        _notify_human(db, incident, "Auto-fix failed safely, repo intact", result.detail)


def _write_exact(target: Path, search: str, replacement: str) -> tuple[bool, str]:
    """Workspace write with the exact-once gate (git is the backup here)."""
    try:
        original = target.read_text()
    except OSError as exc:
        return False, f"cannot read target: {exc}"
    hits = original.count(search)
    if hits == 0:
        return False, "search_block not found — model context stale"
    if hits > 1:
        return False, f"search_block matches {hits}× — ambiguous"
    try:
        target.write_text(original.replace(search, replacement, 1))
    except OSError as exc:
        return False, f"write failed: {exc}"
    return True, "written"


def _notify_human(db: Session, incident: Incident, title: str, body: str) -> None:
    notification_engine.notify(db, f"{title} (incident #{incident.id})",
                               f"{body}\nService: {incident.service.name if incident.service else '?'}",
                               incident_id=incident.id)
