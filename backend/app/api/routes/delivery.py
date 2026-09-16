"""1-click Approve & Deploy: merge a pending fix branch, restart, verify."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.exceptions import NotFound
from app.core.security import require_role
from app.db.database import get_db
from app.db.models import Incident, RemediationAction
from app.engines import incident_engine
from app.remediation import delivery_gate, git_workspace
from app.remediation.delivery_gate import workspace_for

router = APIRouter(prefix="/api/delivery", tags=["delivery"])


class Approve(BaseModel):
    incident_id: int


@router.post("/approve")
async def approve(payload: Approve | None = None, incident_id: int | None = None,
                  user: dict = Depends(require_role("admin", "operator")),
                  db: Session = Depends(get_db)):
    target_id = incident_id or (payload.incident_id if payload else None)
    if not target_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="incident_id is required (query parameter or JSON body)")
    inc = db.get(Incident, target_id)
    if not inc:
        raise NotFound("incident not found")
    pr = (db.query(RemediationAction)
          .filter(RemediationAction.incident_id == incident_id,
                  RemediationAction.action_type == "open_draft_pr")
          .order_by(RemediationAction.id.desc()).first())
    if not pr or not (pr.params or {}).get("branch"):
        raise NotFound("no pending fix branch for this incident")
    repo = workspace_for(inc.service.working_directory or ".")
    ws = git_workspace.Workspace(repo=repo, branch=pr.params["branch"], base_ref="")
    deploy = inc.service.deploy_branch or await git_workspace.current_branch(repo) or "main"
    incident_engine.add_event(db, inc.id, "APPROVED",
                              f"{user['username']} approved {ws.branch}")
    healthy = await delivery_gate.deliver_merged(db, ws, incident=inc,
                                                 deploy_branch=deploy,
                                                 test_results="operator-approved deploy")
    return {"merged": True, "healthy": healthy, "branch": ws.branch}


@router.get("/pending")
def pending(db: Session = Depends(get_db)):
    rows = (db.query(RemediationAction)
            .filter(RemediationAction.action_type == "open_draft_pr",
                    RemediationAction.status == "pending")
            .order_by(RemediationAction.id.desc()).limit(50).all())
    return [{"incident_id": r.incident_id, "branch": (r.params or {}).get("branch"),
             "result": (r.result or "")[:300]} for r in rows]
