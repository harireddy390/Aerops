"""Autonomous code-fix tests: parser, resolver guards, patcher gates, pipeline."""
import asyncio
import shutil
from pathlib import Path

import tests.conftest  # noqa: F401
from fastapi.testclient import TestClient

from app.db.database import SessionLocal, init_db
from app.db.models import Incident, RemediationAction, Service
from app.diagnosis.code_diagnosis_agent import parse_proposal
from app.engines.restart_manager import PROJECT_ROOT
from app.main import app
from app.remediation import code_pipeline, safe_patcher

BUGGY = "const name = user.profile.name;\nconsole.log(name);\n"


def _tmp_service_dir() -> Path:
    d = PROJECT_ROOT / ".tmp-patchtest"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir()
    (d / "widget.js").write_text(BUGGY)
    return d


def test_parser_accepts_clean_json_and_mess():
    good = '{"root_cause": "null deref", "search_block": "a", "replacement_block": "b", "verification_command": "node --check"}'
    assert parse_proposal(good).root_cause == "null deref"
    messy = 'Here you go:\n```json\n{"root_cause": "x", "search_block": "a", "replacement_block": "b", "verification_command": "npm test"}\n```'
    assert parse_proposal(messy).verification_command == "npm test"
    assert parse_proposal("no json here") is None
    assert parse_proposal('{"root_cause": "x", "search_block": "a", "replacement_block": "", "verification_command": "npm test"}') is None  # escalate
    assert parse_proposal('{"root_cause": "x"}') is None


def test_resolver_guards():
    d = _tmp_service_dir()
    try:
        assert safe_patcher.resolve_target(Path(".tmp-patchtest"), PROJECT_ROOT, "widget.js") == (d / "widget.js").resolve()
        assert safe_patcher.resolve_target(Path(".tmp-patchtest"), PROJECT_ROOT, "../../server.js") is None
        assert safe_patcher.resolve_target(Path(".tmp-patchtest"), PROJECT_ROOT, "missing.js") is None
        # ambiguous: two same-named files -> refuse
        (d / "sub").mkdir()
        (d / "sub" / "widget.js").write_text("x")
        assert safe_patcher.resolve_target(Path(".tmp-patchtest"), PROJECT_ROOT, "widget.js") is None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_patcher_gates_and_rollback(tmp_path=None):
    d = _tmp_service_dir()
    target = d / "widget.js"
    try:
        # 0 matches -> abort, file untouched
        r = asyncio.run(safe_patcher.apply_patch(
            target=target, search_block="nope", replacement_block="x",
            verification_command="node --check", cwd=d, project_root=PROJECT_ROOT))
        assert r.ok is False and target.read_text() == BUGGY
        # ambiguous -> abort
        r = asyncio.run(safe_patcher.apply_patch(
            target=target, search_block="name", replacement_block="x",
            verification_command="node --check", cwd=d, project_root=PROJECT_ROOT))
        assert r.ok is False
        # evil verification command -> abort
        r = asyncio.run(safe_patcher.apply_patch(
            target=target, search_block="const name", replacement_block="const name = 1;",
            verification_command="rm -rf /", cwd=d, project_root=PROJECT_ROOT))
        assert r.ok is False and target.read_text() == BUGGY
        # failing verification -> rollback restores original
        r = asyncio.run(safe_patcher.apply_patch(
            target=target, search_block="const name = user.profile.name;",
            replacement_block="const name = user.profile.name(\n",
            verification_command="node --check widget.js", cwd=d, project_root=PROJECT_ROOT))
        assert r.ok is False and target.read_text() == BUGGY
        assert not (d / "widget.js.aeroops.bak").exists()
        # good patch -> applied, backup dropped
        r = asyncio.run(safe_patcher.apply_patch(
            target=target, search_block="const name = user.profile.name;",
            replacement_block="const name = user?.profile?.name ?? 'guest';",
            verification_command="node --check widget.js", cwd=d, project_root=PROJECT_ROOT))
        assert r.ok is True
        assert "?? 'guest'" in target.read_text()
        assert not (d / "widget.js.aeroops.bak").exists()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_bare_node_check_cannot_hang():
    import time
    d = _tmp_service_dir()
    target = d / "widget.js"
    try:
        t0 = time.monotonic()
        r = asyncio.run(safe_patcher.apply_patch(
            target=target, search_block="const name = user.profile.name;",
            replacement_block="const name = user?.profile?.name ?? 'guest';",
            verification_command="node --check", cwd=d, project_root=PROJECT_ROOT))
        dt = time.monotonic() - t0
        assert r.ok is True, r.detail
        assert dt < 20, f"verifier stalled ({dt:.0f}s)"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_pipeline_applies_mocked_proposal(monkeypatch):
    from app.diagnosis.code_diagnosis_agent import CodeFixProposal
    init_db()
    d = _tmp_service_dir()
    db = SessionLocal()
    try:
        svc = db.query(Service).filter(Service.name == "patchdemo").first()
        if not svc:
            svc = Service(name="patchdemo", command="node widget.js",
                          working_directory=".tmp-patchtest", auto_remediation=True)
            db.add(svc)
            db.commit()
        from app.engines import incident_engine
        inc = incident_engine.create_incident(db, service_id=svc.id, type="frontend",
                                              severity="critical", error_message="TypeError boom",
                                              fingerprint="deadbeef1234")
        db.commit()
        iid = inc.id

        async def fake_propose(**kwargs):
            return (CodeFixProposal(root_cause="null deref",
                                    search_block="const name = user.profile.name;",
                                    replacement_block="const name = user?.profile?.name ?? 'guest';",
                                    verification_command="node --check widget.js"), "mock:test")
        monkeypatch.setattr(code_pipeline, "propose_fix", fake_propose)
        asyncio.run(code_pipeline.run_code_remediation(iid, "widget.js", 1))
        acts = db.query(RemediationAction).filter(
            RemediationAction.incident_id == iid,
            RemediationAction.action_type == "apply_code_patch").all()
        assert len(acts) == 1 and acts[0].status == "succeeded"
        assert "?? 'guest'" in (d / "widget.js").read_text()
    finally:
        db.close()
        shutil.rmtree(d, ignore_errors=True)


def test_new_payload_shape_accepted():
    with TestClient(app) as c:
        r = c.post("/api/telemetry/crash", json={
            "service_id": "tsshape", "error_name": "TypeError",
            "message": "Cannot read properties of undefined (reading 'map')",
            "file_path": "https://x.example/app.js", "line_number": 10,
            "column_number": 3,
            "stack_trace": "TypeError: boom\n    at f (https://x.example/app.js:10:3)"})
        assert r.status_code == 200, r.text
        assert r.json()["location"].startswith("app.js:10")
