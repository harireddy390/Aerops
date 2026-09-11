"""Client telemetry tests: public SDK ingest auth, rate limiting, Vite/React
stack translation, service key lifecycle, and a live-origin e2e simulation
(incident -> fix-client branch -> patch -> deploy webhook)."""
import asyncio
import stat
import shutil
import subprocess
from pathlib import Path

import tests.conftest  # noqa: F401
from fastapi.testclient import TestClient

import app.api.routes.telemetry as telemetry_mod
from app.db.database import SessionLocal, init_db
from app.db.models import Incident, IncidentEvent, Service
from app.diagnosis.client_stack import hints_from_stack, primary_hint, to_repo_hint
from app.engines.restart_manager import PROJECT_ROOT
from app.main import app
from app.utils import rate_limit

CLIENT_CRASH = {
    "serviceId": "WEBSVC",
    "message": "Cannot read properties of undefined (reading 'cart')",
    "error_name": "TypeError",
    "stack_trace": ("TypeError: Cannot read properties of undefined (reading 'cart')\n"
                    "    at CartTotal (https://my-app.lovable.app/assets/index-a9f2c1.js:1:245)\n"
                    "    at render (https://my-app.lovable.app/assets/vendor.js:2:10)"),
    "url": "https://my-app.lovable.app/checkout",
    "route": "/checkout",
    "userAgent": "Mozilla/5.0 test",
    "componentStack": "in CartTotal (at Cart.tsx:12)\nin CheckoutPage (at page.tsx:4)",
    "release": "1.4.2",
    "timestamp": "2026-09-11T07:00:00.000Z",
}


def _rmtree(path: Path) -> None:
    def _onerr(func, p, _):
        try:
            import os
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, ignore_errors=False, onerror=_onerr)


def _mk_service(name: str, **kw) -> Service:
    init_db()
    db = SessionLocal()
    try:
        svc = db.query(Service).filter(Service.name == name).first()
        if not svc:
            # disabled: the monitor skips these (no tick churn for other tests)
            svc = Service(name=name, working_directory=name, auto_remediation=True,
                          enabled=False)
            db.add(svc)
            db.flush()
        for key, value in kw.items():
            setattr(svc, key, value)
        if not svc.client_api_key:
            svc.client_api_key = f"key-for-{name}"
        db.commit()
        db.refresh(svc)
        key = svc.client_api_key
        sid = svc.id
    finally:
        db.close()
    rate_limit.reset()
    return sid, key


def _noop_recorder(calls: list):
    async def _noop(incident_id: int, hints: list):
        calls.append((incident_id, hints))
    return _noop


# --- stack translation (pure unit tests, no DB) -----------------------------

def test_to_repo_hint_prefers_src_paths():
    assert to_repo_hint("https://my-app.lovable.app/src/App.tsx?t=1726:15:10") == "src/App.tsx"
    assert to_repo_hint("http://localhost:5173/src/components/Cart.tsx:42:9") == "src/components/Cart.tsx"
    assert to_repo_hint("at render (src/components/Cart.tsx:42:9)") == "src/components/Cart.tsx"
    assert to_repo_hint("https://my-app.lovable.app/assets/index-a9f2c1.js:1:245") == "index-a9f2c1.js"
    assert to_repo_hint("") == ""


def test_hints_order_src_first_and_skip_vendor_noise():
    hints = hints_from_stack(CLIENT_CRASH["stack_trace"], file_path="", line=0)
    assert hints and hints[0].file_hint == "index-a9f2c1.js"
    assert all("node_modules" not in h.file_hint for h in hints)
    dev = ("Error: boom\n    at App (http://localhost:5173/src/App.tsx:15:10)\n"
           "    at render (http://localhost:5173/node_modules/react-dom/index.js:5:1)")
    assert primary_hint(dev).file_hint == "src/App.tsx"
    explicit = primary_hint(dev, file_path="https://x/src/Shop.tsx", line=3)
    assert (explicit.file_hint, explicit.line) == ("src/Shop.tsx", 3)


# --- endpoint validation ----------------------------------------------------

def test_client_sdk_served_publicly():
    with TestClient(app) as c:  # no auth
        r = c.get("/sdk/aeroops.js")
        assert r.status_code == 200, r.text
        assert "application/javascript" in r.headers["content-type"]
        assert "AeroOps.init" in r.text and "unhandledrejection" in r.text


def test_client_validates_service_id(monkeypatch):
    monkeypatch.setattr(telemetry_mod, "run_client_remediation", _noop_recorder([]))
    with TestClient(app) as c:
        assert c.post("/api/telemetry/client", json={}).status_code == 422
        assert c.post("/api/telemetry/client", json={"message": "x"}).status_code == 422
        r = c.post("/api/telemetry/client", json={"serviceId": "no-such-svc", "message": "x"})
        assert r.status_code == 404, r.text


def test_client_auth_key_flow(monkeypatch):
    calls: list = []
    monkeypatch.setattr(telemetry_mod, "run_client_remediation", _noop_recorder(calls))
    _mk_service("client-auth-svc", published_url="https://my-app.lovable.app",
                client_api_key="secret-key-1")
    with TestClient(app) as c:
        base = {**CLIENT_CRASH, "serviceId": "client-auth-svc"}
        assert c.post("/api/telemetry/client", json=base).status_code == 401
        assert c.post("/api/telemetry/client", json={**base, "apiKey": "wrong"}).status_code == 401
        assert c.post("/api/telemetry/client", json={**base, "apiKey": "secret-key-1"}).status_code == 200
        r = c.post("/api/telemetry/client", json={**base, "serviceId": "secret-key-1"})
        assert r.status_code == 200, r.text  # key itself works as identifier
        h = c.post("/api/telemetry/client", json=base, headers={"X-AeroOps-Key": "secret-key-1"})
        assert h.status_code == 200, h.text


def test_client_keyless_legacy_service_uses_public_identifier(monkeypatch):
    monkeypatch.setattr(telemetry_mod, "run_client_remediation", _noop_recorder([]))
    _mk_service("client-legacy-svc", client_api_key="")
    db = SessionLocal()
    try:  # keep it keyless: helper fills a placeholder, clear it back
        db.query(Service).filter(Service.name == "client-legacy-svc").update({"client_api_key": ""})
        db.commit()
    finally:
        db.close()
    with TestClient(app) as c:
        r = c.post("/api/telemetry/client",
                   json={**CLIENT_CRASH, "serviceId": "client-legacy-svc"})
        assert r.status_code == 200, r.text


def test_client_rate_limiting(monkeypatch):
    monkeypatch.setattr(telemetry_mod, "run_client_remediation", _noop_recorder([]))
    _mk_service("client-flood-svc", client_api_key="flood-key")
    with TestClient(app) as c:
        ok = 0
        limited = 0
        for _ in range(35):
            r = c.post("/api/telemetry/client",
                       json={**CLIENT_CRASH, "serviceId": "flood-key"})
            if r.status_code == 200:
                ok += 1
            elif r.status_code == 429:
                limited += 1
                assert "Retry-After" in r.headers
        assert ok == 30 and limited == 5, (ok, limited)


def test_client_creates_frontend_incident_and_dedups(monkeypatch):
    calls: list = []
    monkeypatch.setattr(telemetry_mod, "run_client_remediation", _noop_recorder(calls))
    sid, _ = _mk_service("client-inc-svc", published_url="https://my-app.lovable.app",
                         client_api_key="inc-key")
    with TestClient(app) as c:
        first = c.post("/api/telemetry/client",
                       json={**CLIENT_CRASH, "serviceId": "inc-key"}).json()
        assert first["deduped"] is False
        assert first["file_hint"] == "index-a9f2c1.js"
        second = c.post("/api/telemetry/client",
                        json={**CLIENT_CRASH, "serviceId": "inc-key"}).json()
        assert second["deduped"] is True and second["incident_id"] == first["incident_id"]
        db = SessionLocal()
        try:
            inc = db.get(Incident, first["incident_id"])
            assert inc.type == "frontend" and inc.service_id == sid
            assert inc.status == "DIAGNOSED" and "[client]" in inc.error_message
            assert "lovable.app/checkout" in inc.failure_reason
            assert len(calls) == 1 and calls[0][0] == inc.id  # pipeline triggered once
        finally:
            db.close()


# --- service key lifecycle ---------------------------------------------------

def test_service_registration_key_lifecycle():
    """Key minting without touching auth endpoints (order-independent)."""
    import pydantic
    import pytest

    from app.api.routes.services import create_service, rotate_client_key
    from app.schemas import ServiceCreate

    with pytest.raises(pydantic.ValidationError):
        ServiceCreate(name="x", published_url="ftp://x")
    with pytest.raises(pydantic.ValidationError):
        ServiceCreate(name="x", deploy_webhook_url="nota-url")
    init_db()
    db = SessionLocal()
    try:
        out = create_service(ServiceCreate(
            name="client-shop", published_url="https://my-app.lovable.app",
            deploy_webhook_url="https://hooks.example/deploy-1"),
            db, {"username": "tester"})
        assert len(out.client_api_key) >= 20
        assert out.published_url == "https://my-app.lovable.app"
        assert out.deploy_webhook_url == "https://hooks.example/deploy-1"
        old = out.client_api_key
        out2 = rotate_client_key(out.id, db, {"username": "tester"})
        assert out2.client_api_key and out2.client_api_key != old
    finally:
        db.query(Service).filter(Service.name == "client-shop").delete()
        db.commit()
        db.close()


# --- repo sync helper --------------------------------------------------------

def test_sync_repo_notes_without_touching(tmp_path):
    from app.remediation import git_workspace
    note = asyncio.run(git_workspace.sync_repo(tmp_path))
    assert "not a git repo" in note
    d = tmp_path / "repo"
    d.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.io"], cwd=d, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
    (d / "f.txt").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=d, check=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=d, check=True)
    assert "no remote" in asyncio.run(git_workspace.sync_repo(d, target_branch="main"))
    (d / "f.txt").write_text("dirty\n")
    assert "dirty" in asyncio.run(git_workspace.sync_repo(d, target_branch="main"))


# --- end-to-end simulation ----------------------------------------------------

def _client_repo(name: str = ".tmp-cliente2e") -> Path:
    d = PROJECT_ROOT / name
    if d.exists():
        _rmtree(d)
    (d / "src").mkdir(parents=True)
    (d / "src" / "App.js").write_text("const n = user.profile.name;\nconsole.log(n);\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.io"], cwd=d, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
    subprocess.run(["git", "add", "-A"], cwd=d, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=d, check=True)
    return d


def test_client_e2e_incident_branch_patch_webhook(monkeypatch):
    import app.remediation.code_pipeline as pipe
    import app.remediation.delivery_gate as gate
    from app.db.database import SessionLocal
    from app.diagnosis.code_diagnosis_agent import MultiProposal, RegressionTest
    from app.engines import incident_engine

    DIFF = ("--- a/src/App.js\n+++ b/src/App.js\n@@ -1,2 +1,2 @@\n"
            "-const n = user.profile.name;\n+const n = user?.profile?.name ?? 'guest';\n console.log(n);\n")
    d = _client_repo()
    hooks: list = []
    pipeline_calls: list = []
    # capture the background wiring; the pipeline itself is driven explicitly
    # below (never twice against the same repo in one test).
    monkeypatch.setattr(telemetry_mod, "run_client_remediation",
                        _noop_recorder(pipeline_calls))
    monkeypatch.setattr("httpx.post", lambda url, **kw: hooks.append((url, kw)) or type("R", (), {"status_code": 200})())
    try:
        init_db()
        db = SessionLocal()
        try:
            svc = db.query(Service).filter(Service.name == "lovable-e2e").first()
            if not svc:
                svc = Service(name="lovable-e2e", command="", working_directory=".tmp-cliente2e",
                              workspace_frontend="src", auto_remediation=True,
                              test_command="python --version", remediation_policy="AUTO_MERGE",
                              published_url="https://my-app.lovable.app",
                              client_api_key="e2e-live-key",
                              deploy_webhook_url="https://hooks.example/deploy-9",
                              enabled=False)  # monitor skips it; pipeline still runs
                db.add(svc)
                db.commit()
            else:
                for k, v in {"command": "", "working_directory": ".tmp-cliente2e",
                             "workspace_frontend": "src", "auto_remediation": True,
                             "test_command": "python --version", "remediation_policy": "AUTO_MERGE",
                             "published_url": "https://my-app.lovable.app",
                             "client_api_key": "e2e-live-key",
                             "deploy_webhook_url": "https://hooks.example/deploy-9",
                             "enabled": False}.items():
                    setattr(svc, k, v)
                db.commit()
        finally:
            db.close()

        with TestClient(app) as c:
            r = c.post("/api/telemetry/client", json={
                "serviceId": "e2e-live-key",
                "error_name": "TypeError",
                "message": "Cannot read properties of undefined (reading 'profile')",
                "stack_trace": ("TypeError: Cannot read properties of undefined\n"
                                "    at App (https://my-app.lovable.app/src/App.js:1:11)"),
                "url": "https://my-app.lovable.app/",
                "componentStack": "in App (at App.js:1)",
                "release": "9.9.9"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["file_hint"] == "src/App.js"
            iid = body["incident_id"]
        assert len(pipeline_calls) == 1 and pipeline_calls[0][0] == iid
        assert pipeline_calls[0][1][0]["file_hint"] == "src/App.js"  # wiring: POST -> pipeline

        async def fake_multi(**kwargs):
            return (MultiProposal(
                root_cause="null deref in App", upstream_origin="N/A - Direct Call",
                crash_site="src/App.js:1", strategy="guard with optional chaining",
                patches=[DIFF],
                test=RegressionTest(path="App.check.aeroops.test.js", language="javascript",
                                    body="const n = undefined?.profile?.name ?? 'guest';\n"
                                         "if (n !== 'guest') throw new Error('x');\n")), "mock:test")
        monkeypatch.setattr(pipe, "propose_multifile", fake_multi)
        asyncio.run(pipe.run_client_remediation(
            iid, [{"file_hint": "src/App.js", "line": 1, "column": 11}]))

        assert "?? 'guest'" in (d / "src" / "App.js").read_text()  # patch landed on main
        assert hooks and hooks[0][0] == "https://hooks.example/deploy-9"  # rebuild fired
        db = SessionLocal()
        try:
            inc = db.get(Incident, iid)
            assert inc.status == "RESOLVED", inc.status  # merged + verified, operator notified
            types = [e.event_type for e in
                     db.query(IncidentEvent).filter(IncidentEvent.incident_id == iid).all()]
            for want in ("REPO_SYNCED", "CODEFIX_BRANCH", "CODEFIX_APPLIED",
                         "MERGED", "DEPLOY_TRIGGERED"):
                assert want in types, types
            branch = next(e.message for e in
                          db.query(IncidentEvent).filter(IncidentEvent.incident_id == iid,
                                                        IncidentEvent.event_type == "CODEFIX_BRANCH").all())
            assert "aeroops/fix-client-" in branch, branch  # ephemeral client branch
        finally:
            db.close()
    finally:
        _rmtree(d)
