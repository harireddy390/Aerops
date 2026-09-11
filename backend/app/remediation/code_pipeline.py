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
from app.core.logging import get_logger
from app.diagnosis.code_context import collect_context, render_slices
from app.diagnosis.code_diagnosis_agent import propose_fix, propose_multifile
from app.diagnosis.reflexion_agent import propose_multifile_with_reflexion
from app.engines import audit_engine, incident_engine, notification_engine
from app.engines.restart_manager import PROJECT_ROOT
from app.remediation import delivery_gate, git_workspace, policies
from app.remediation.safe_patcher import (apply_diffs, apply_patch, materialize_at,
                                          read_context, resolve_target)
from app.remediation.test_harness import verify_with_command as harness_verify_custom
from app.utils.events import bus
from app.utils.time import utcnow

log = get_logger("code-pipeline")


def _language(target: Path) -> str:
    return {"py": "python", "js": "javascript", "jsx": "javascript",
            "ts": "typescript", "tsx": "typescript"}.get(target.suffix.lstrip(".").lower(), "unknown")


def _service_dir(svc) -> Path:
    return (PROJECT_ROOT / (svc.working_directory or ".")).resolve()


def _resolve_local(svc, file_hint: str) -> Path | None:
    """Map a crash hint across the service roots: working dir first (legacy
    behavior), then the frontend/backend workspace subpaths (client SPAs)."""
    bases = [svc.working_directory or "."]
    for extra in (getattr(svc, "workspace_frontend", ""), getattr(svc, "workspace_backend", "")):
        if extra and extra not in bases:
            bases.append(extra)
    for base in bases:
        target = resolve_target(Path(base), PROJECT_ROOT, file_hint or "")
        if target:
            return target
    return None


async def run_client_remediation(incident_id: int, hints: list[dict]) -> None:
    """Client entry: sync the linked clone, map the browser stack to a local
    file across all workspace roots, then run the standard pipeline."""
    db: Session = SessionLocal()
    try:
        incident = db.get(Incident, incident_id)
        if not incident:
            return
        svc = incident.service
        repo = _service_dir(svc)
        note = await git_workspace.sync_repo(
            repo, target_branch=(svc.target_branch or svc.deploy_branch or "main"))
        incident_engine.add_event(db, incident.id, "REPO_SYNCED", note[:300])
        db.commit()
        for hint in hints or []:
            file_hint = (hint or {}).get("file_hint", "")
            if _resolve_local(svc, file_hint):
                await run_code_remediation(incident_id, file_hint,
                                           int((hint or {}).get("line") or 0))
                return
        incident_engine.add_event(db, incident.id, "CODEFIX_UNRESOLVABLE",
                                  f"live stack maps to no local file: "
                                  f"{str((hints or [{}])[0].get('file_hint', ''))[:120]}")
        _notify_human(db, incident, "Could not locate the live crashing file",
                      f"Browser stack references "
                      f"{str((hints or [{}])[0].get('file_hint', ''))[:200]}. Fix it by hand.")
        db.commit()
    except Exception as exc:
        log.info(f"client pipeline isolated error on incident {incident_id}: {type(exc).__name__}: {exc}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


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
        target = _resolve_local(svc, file_hint)
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
    except Exception as exc:
        log.info(f"code pipeline isolated error on incident {incident_id}: {type(exc).__name__}: {exc}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


async def _git_flow(db: Session, incident: Incident, svc, target: Path,
                    context: str, error: str, file_hint: str, line: int) -> None:
    from app.diagnosis.code_context import collect_context, render_slices
    repo = _service_dir(svc)
    prefix = "fix-client" if incident.type == "frontend" else "fix"
    try:
        ws = await git_workspace.open_workspace(
            repo, incident.id, incident.fingerprint or "manual", prefix=prefix)
    except RuntimeError as exc:
        incident_engine.add_event(db, incident.id, "CODEFIX_NO_WORKSPACE", str(exc)[:300])
        _notify_human(db, incident, "Repo not ready for auto-fix", str(exc)[:500])
        return
    incident_engine.add_event(db, incident.id, "CODEFIX_BRANCH",
                              f"isolated on {ws.branch} (base {ws.base_ref[:8]})")

    # multi-file evidence: crash locus + imported helpers, raw lines only
    # (models copy numbered prefixes verbatim into diffs otherwise).
    import re as _re2
    _, slices = collect_context(repo_root=repo, target=target, line=max(line, 1))
    model_context = (f"The crash is at line {max(line, 1)} of {target.name}:\n"
                     + _re2.sub(r"(?m)^\s*\d+\s*\|\s?", "", render_slices(slices)))
    stack = f"{incident.error_message}"
    test_cmd = (svc.test_command or "").strip()
    if (not test_cmd and target.suffix.lower() in (".js", ".jsx", ".ts", ".tsx")
            and (repo / "package.json").is_file()):
        test_cmd = "npm run build"
        incident_engine.add_event(db, incident.id, "CODEFIX_VERIFY",
                                  "no test_command configured — verifying with `npm run build`")
    runtime_env = f"{_language(target)} service '{svc.name}'"
    locus = f"{target.name}:{max(line, 1)}"

    async def propose_first():
        return await propose_multifile(
            service_name=svc.name, incident_id=incident.id,
            runtime_error=error, crash_locus=locus, stack_trace=stack,
            code_slices=model_context, runtime_env=runtime_env,
            test_command=test_cmd or "auto-detect")

    async def try_patch(proposal):
        applied = await apply_diffs(repo=ws.repo, diff_text="\n".join(proposal.patches))
        if not applied.ok:
            hint = ""
            import re as _re
            if _re.search(r"(?m)^\d+\s*\|", "\n".join(proposal.patches)):
                hint = " (your diff contains line-number prefixes like '9 | ' — remove them; use raw file lines only)"
            failures.append(applied.detail + hint)
            return False, applied.detail + hint
        if proposal.test is not None:
            test_path = materialize_at(repo=ws.repo, relpath=proposal.test.path,
                                       body=proposal.test.body)
            if test_path:
                created_test_files.append(test_path)
                incident_engine.add_event(db, incident.id, "CODEFIX_TEST",
                                          f"shipped regression test {test_path.name}")
        report = await harness_verify_custom(target=target, test_command=test_cmd,
                                               cwd=ws.repo)
        if report.ok:
            return True, "syntax + custom tests green"
        failures.append(report.failure_text)
        return False, report.failure_text

    created_test_files: list = []
    failures: list[str] = []
    proposal, provider, outcome = await propose_multifile_with_reflexion(
        propose_first, error=error, context_block=model_context,
        service_name=svc.name, incident_id=incident.id, runtime_error=error,
        crash_locus=locus, stack=stack, slices=model_context,
        runtime_env=runtime_env, test_command=test_cmd or "auto-detect",
        try_patch=try_patch)
    if outcome != "verified" or not proposal:
        await git_workspace.abandon(ws)
        for stale in created_test_files:  # ours, namespaced: safe to remove
            try:
                stale.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            incident_engine.transition(db, incident, "ESCALATED_MANUAL",
                                       message="reflexion exhausted — needs a human")
        except Exception:
            pass
        last_diff = "\n".join(proposal.patches)[:800] if proposal else ""
        if not last_diff:
            from app.diagnosis import code_diagnosis_agent as _agent
            last_diff = f"model gave no parseable output; last raw reply:\n{getattr(_agent.propose_multifile, 'last_raw', '')[:600]}"
        rounds = "\n".join(f"round {n}: {f}" for n, f in enumerate(failures[-3:]))[:1200]
        db.add(RemediationAction(incident_id=incident.id, action_type="apply_code_patch",
                                 source="automation", status="escalated",
                                 params={"file": str(target), "provider": provider},
                                 error=f"reflexion exhausted ({len(failures)} rounds):\n{rounds}"[:1500],
                                 result=f"last proposal diff (NOT applied):\n{last_diff}"[:1000],
                                 started_at=utcnow(), completed_at=utcnow()))
        db.flush()
        incident_engine.add_event(db, incident.id, "CODEFIX_ESCALATED",
                                  "2 reflexion rounds failed; branch removed, tree intact")
        if failures:
            incident_engine.add_event(db, incident.id, "CODEFIX_LAST_ERROR", failures[-1][:500])
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
    mode = (svc.remediation_policy or svc.policy_mode or "DRAFT_PR").upper()
    deploy_branch = (svc.target_branch or svc.deploy_branch
                     or await git_workspace.current_branch(repo) or "main")
    from app.core.crypto import decrypt_token
    push_token = decrypt_token(svc.git_token_enc or "")
    if mode == "AUTO_MERGE":
        await delivery_gate.deliver_merged(db, ws, incident=incident,
                                           deploy_branch=deploy_branch,
                                           test_results="syntax + scoped regression green")
    elif mode == "MANUAL_APPROVAL":
        action2 = RemediationAction(incident_id=incident.id, action_type="open_draft_pr",
                                    source="automation", status="pending",
                                    params={"branch": ws.branch, "pushed": False,
                                            "mode": "MANUAL_APPROVAL"},
                                    result=f"Held for manual approval on {ws.branch} "
                                           f"(no push attempted). Approve & Deploy merges it.",
                                    started_at=utcnow(), completed_at=utcnow())
        db.add(action2)
        db.flush()
        incident_engine.add_event(db, incident.id, "DRAFT_PR",
                                  f"held {ws.branch} for manual approval (no push)")
        audit_engine.record(db, "REMEDIATION_EXECUTED", service_id=svc.id,
                            incident_id=incident.id, actor="automation",
                            action="open_draft_pr", result="pending-manual")
        notification_engine.notify(
            db, f"Fix ready to approve on {svc.name}",
            f"Incident #{incident.id}\n{proposal.root_cause}\nBranch: {ws.branch}\n"
            f"Approve: POST /api/delivery/approve {{\"incident_id\": {incident.id}}}",
            incident_id=incident.id)
        db.commit()
        await bus.publish("notification", {"incident_id": incident.id})
    else:
        await delivery_gate.deliver_draft_pr(
            db, ws, incident=incident, root_cause=proposal.root_cause,
            stack=incident.error_message,
            test_results="syntax + scoped regression green", diff_stat=diff_stat,
            git_token=push_token)


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


def _notify_human(db: Session, incident: Incident, title: str, body: str) -> None:
    notification_engine.notify(db, f"{title} (incident #{incident.id})",
                               f"{body}\nService: {incident.service.name if incident.service else '?'}",
                               incident_id=incident.id)
