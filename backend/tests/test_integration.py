"""Integration + API: service CRUD, AI-offline fallback, SSE, full crash->recover loop."""
import asyncio
import time

import tests.conftest  # noqa: F401
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models import Incident, Service
from app.diagnosis import ai_diagnoser
from app.main import app


def _client():
    return TestClient(app)


def _admin_headers(c):
    """First user becomes admin; log in and return auth headers."""
    c.post("/api/auth/register", json={"username": "tester", "email": "tester@x.io",
                                         "password": "testerpass123", "confirm_password": "testerpass123"})
    r = c.post("/api/auth/login", json={"username": "tester", "password": "testerpass123"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_auth_first_user_is_admin_and_rbac():
    with _client() as c:
        assert c.get("/api/auth/status").json()["registration_open"] is True
        h = _admin_headers(c)
        assert c.get("/api/auth/status").json()["registration_open"] is False
        # second registration is closed (open-signup off in tests)
        assert c.post("/api/auth/register",
                      json={"username": "latecomer", "email": "late@x.io",
                            "password": "xpass12345", "confirm_password": "xpass12345"}).status_code == 403
        # mismatched passwords rejected even for open... (closed here, so craft direct check below)
        assert c.post("/api/auth/login",
                      json={"username": "tester", "password": "nope"}).status_code == 401
        # unauthenticated reads rejected
        assert c.get("/api/services").status_code in (401, 403)
        # admin can list users, viewer cannot create services
        assert c.get("/api/auth/users", headers=h).status_code == 200
        c.post("/api/auth/users", headers=h,
               json={"username": "viewer1", "email": "viewer1@x.io",
                     "password": "viewerpass1", "confirm_password": "viewerpass1", "role": "viewer"})
        vh = {"Authorization": f"Bearer {c.post('/api/auth/login', json={'username': 'viewer1', 'password': 'viewerpass1'}).json()['token']}"}
        assert c.post("/api/services", headers=vh, json={"name": "nope"}).status_code == 403
        assert c.get("/api/services", headers=vh).status_code == 200


def test_password_change_and_admin_reset():
    with _client() as c:
        h = _admin_headers(c)
        c.post("/api/auth/users", headers=h,
               json={"username": "pwuser", "email": "pwuser@x.io",
                     "password": "pwuserpass1", "confirm_password": "pwuserpass1", "role": "viewer"})
        pu = {"Authorization": f"Bearer {c.post('/api/auth/login', json={'username': 'pwuser', 'password': 'pwuserpass1'}).json()['token']}"}
        # change own password
        r = c.post("/api/auth/change-password", headers=pu,
                   json={"current_password": "pwuserpass1", "new_password": "newpass456",
                         "confirm_password": "newpass456"})
        assert r.status_code == 200, r.text
        assert c.post("/api/auth/login",
                      json={"username": "pwuser", "password": "newpass456"}).status_code == 200
        assert c.post("/api/auth/login",
                      json={"username": "pwuser", "password": "pwuserpass1"}).status_code == 401
        # admin resets it, user logs in with the new one
        r = c.post("/api/auth/users/pwuser/reset", headers=h, json={"new_password": "freshpass2"})
        assert r.status_code == 200, r.text
        assert c.post("/api/auth/login",
                      json={"username": "pwuser", "password": "freshpass2"}).status_code == 200
        # remember-me yields a longer-lived token
        short = c.post("/api/auth/login",
                       json={"username": "pwuser", "password": "freshpass2"}).json()["token"]
        long = c.post("/api/auth/login",
                      json={"username": "pwuser", "password": "freshpass2", "remember": True}).json()["token"]
        import jwt as pyjwt
        ds = pyjwt.decode(short, options={"verify_signature": False})
        dl = pyjwt.decode(long, options={"verify_signature": False})
        assert dl["exp"] - ds["exp"] > 20 * 24 * 3600


def test_open_signup_creates_viewer_only(monkeypatch):
    import app.core.config as config_mod
    monkeypatch.setattr(config_mod.settings, "allow_open_signup", True)
    with _client() as c:
        h = _admin_headers(c)
        r = c.post("/api/auth/register",
                   json={"username": "newbie", "email": "newbie@x.io",
                         "password": "newbiepass1", "confirm_password": "newbiepass1",
                         "role": "admin"})
        assert r.status_code == 201, r.text
        assert r.json()["role"] == "viewer"  # role request ignored: never admin via signup
        t = c.post("/api/auth/login",
                   json={"username": "newbie", "password": "newbiepass1"}).json()
        assert t["role"] == "viewer"
        vh = {"Authorization": f"Bearer {t['token']}"}
        assert c.post("/api/services", headers=vh, json={"name": "x"}).status_code == 403
        assert c.get("/api/services", headers=vh).status_code == 200
        _ = h


def test_signup_validation_and_forgot_reset_flow(monkeypatch):
    import app.api.routes.auth as auth_routes
    with _client() as c:
        h = _admin_headers(c)
        # mismatched passwords rejected
        r = c.post("/api/auth/users", headers=h,
                   json={"username": "mismatch", "email": "m@x.io",
                         "password": "aaaaaaaa", "confirm_password": "bbbbbbbb", "role": "viewer"})
        assert r.status_code == 422
        # bad gmail rejected
        r = c.post("/api/auth/users", headers=h,
                   json={"username": "badmail", "email": "not-an-email",
                         "password": "aaaaaaaa", "confirm_password": "aaaaaaaa", "role": "viewer"})
        assert r.status_code == 422
        # duplicate gmail rejected
        r = c.post("/api/auth/users", headers=h,
                   json={"username": "tester2", "email": "tester@x.io",
                         "password": "aaaaaaaa", "confirm_password": "aaaaaaaa", "role": "viewer"})
        assert r.status_code == 409
        # forgot flow: fixed code via patched RNG, wrong code fails, right code resets
        c.post("/api/auth/users", headers=h,
               json={"username": "forgotguy", "email": "forgot@x.io",
                     "password": "forgotpass1", "confirm_password": "forgotpass1", "role": "viewer"})
        monkeypatch.setattr(auth_routes.secrets, "randbelow", lambda _: 123456)
        assert c.post("/api/auth/forgot-password",
                      json={"username_or_email": "forgotguy"}).json()["ok"] is True
        bad = c.post("/api/auth/reset-password",
                     json={"username_or_email": "forgotguy", "code": "000000",
                           "new_password": "brandnew1", "confirm_password": "brandnew1"})
        assert bad.status_code == 400
        good = c.post("/api/auth/reset-password",
                      json={"username_or_email": "forgot@x.io", "code": "123456",
                            "new_password": "brandnew1", "confirm_password": "brandnew1"})
        assert good.status_code == 200, good.text
        assert c.post("/api/auth/login",
                      json={"username": "forgotguy", "password": "brandnew1"}).status_code == 200
        # code is single-use
        again = c.post("/api/auth/reset-password",
                       json={"username_or_email": "forgotguy", "code": "123456",
                             "new_password": "otherpass1", "confirm_password": "otherpass1"})
        assert again.status_code == 400
        # unknown identity still returns ok (no enumeration)
        assert c.post("/api/auth/forgot-password",
                      json={"username_or_email": "ghost"}).json()["ok"] is True


def test_service_crud_and_validation():
    with _client() as c:
        h = _admin_headers(c)
        r = c.post("/api/services", headers=h, json={"name": "crud-svc", "command": "python -m http.server 4198",
                                                     "health_check_type": "http",
                                                     "health_check_url": "http://localhost:4198"})
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        assert c.get(f"/api/services/{sid}", headers=h).status_code == 200
        # shell metacharacters must be rejected
        bad = c.post("/api/services", headers=h, json={"name": "evil", "command": "x; rm -rf /"})
        assert bad.status_code == 422
        assert c.delete(f"/api/services/{sid}", headers=h).status_code == 204


def test_ai_offline_falls_back():
    assert ai_diagnoser.available() is True  # enabled...
    result = asyncio.run(ai_diagnoser.diagnose_structured({"error": "boom"}))
    assert result is None  # ...but unreachable host degrades cleanly


def test_stop_stays_stopped_until_start():
    """Intentional stop is desired-state, not a crash: no incident, no restart."""
    import asyncio
    from app.db.models import Incident, Service
    from app.db.database import SessionLocal
    from app.engines import monitor_engine
    with _client() as c:
        h = _admin_headers(c)
        r = c.post("/api/services", headers=h, json={
            "name": "stop-test", "command": "python -m http.server 4196",
            "health_check_type": "http", "health_check_url": "http://localhost:4196",
            "health_check_interval": 1, "ai_diagnosis": False})
        sid = r.json()["id"]
        assert c.post(f"/api/services/{sid}/start", headers=h).json()["status"] == "UNKNOWN"
        stopped = c.post(f"/api/services/{sid}/stop", headers=h).json()
        assert stopped["status"] == "STOPPED"
        before = SessionLocal().query(Incident).filter(Incident.service_id == sid).count()
        for _ in range(4):
            asyncio.run(monitor_engine._tick())
        db = SessionLocal()
        try:
            svc = db.get(Service, sid)
            assert svc.status == "STOPPED"
            assert svc.enabled is False
            assert db.query(Incident).filter(Incident.service_id == sid).count() == before
        finally:
            db.close()
        # start resumes watching
        assert c.post(f"/api/services/{sid}/start", headers=h).json()["status"] == "UNKNOWN"
        db = SessionLocal()
        try:
            assert db.get(Service, sid).enabled is True
        finally:
            db.close()
        c.post(f"/api/services/{sid}/stop", headers=h)
        c.delete(f"/api/services/{sid}", headers=h)


def test_sse_wiring():
    import asyncio
    import json
    from app.utils.events import bus

    async def roundtrip():
        q = bus.subscribe()
        try:
            await bus.publish("test.event", {"n": 1})
            msg = await asyncio.wait_for(q.get(), timeout=5)
            return json.loads(msg)
        finally:
            bus.unsubscribe(q)

    data = asyncio.run(roundtrip())
    assert data == {"type": "test.event", "n": 1}
    # route is registered
    paths = app.openapi()["paths"]
    assert "/api/events/stream" in paths


def test_full_failure_lifecycle():
    """register -> start -> kill -> monitor detects -> incident -> restart -> recovered."""
    from app.engines import monitor_engine, restart_manager
    with _client() as c:
        h = _admin_headers(c)
        r = c.post("/api/services", headers=h, json={
            "name": "lifecycle-svc", "command": "python -m http.server 4197",
            "working_directory": ".", "health_check_type": "http",
            "health_check_url": "http://localhost:4197",
            "health_check_interval": 1, "max_restart_attempts": 3, "cooldown_sec": 0,
            "ai_diagnosis": False})
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        started = c.post(f"/api/services/{sid}/start", headers=h).json()
        assert started["pid"] > 0
        time.sleep(2)
        proc = restart_manager._processes.get(sid)
        assert proc and proc.poll() is None
        proc.kill()  # <-- the failure
        deadline = time.time() + 90
        resolved = None
        while time.time() < deadline:
            asyncio.run(monitor_engine._tick())
            db = SessionLocal()
            try:
                inc = db.query(Incident).filter(Incident.service_id == sid).order_by(Incident.id.desc()).first()
                if inc and inc.status == "RESOLVED":
                    resolved = inc
                    # drive the still-pending verify ticks (wait_healthy sleeps inside handler)
                    break
            finally:
                db.close()
            time.sleep(2)
        # NOTE: _tick awaits the whole handler incl. 3x2s verify, so RESOLVED lands inline
        assert resolved is not None, "incident never resolved"
        assert resolved.recovery_verified is True
        tl = c.get(f"/api/incidents/{resolved.id}/timeline", headers=h).json()
        kinds = [e["type"] for e in tl]
        for expected in ["INCIDENT_CREATED", "DIAGNOSIS_COMPLETED", "REMEDIATION_EXECUTED", "RESOLVED"]:
            assert expected in kinds, kinds
        c.post(f"/api/services/{sid}/stop", headers=h)
        c.delete(f"/api/services/{sid}", headers=h)
