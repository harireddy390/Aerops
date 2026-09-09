"""Browser telemetry tests: ingest, forensics, dedup, passive services."""
import tests.conftest  # noqa: F401
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models import Incident, Service
from app.main import app

BROWSER_CRASH = {
    "service": "webshop",
    "kind": "error-boundary",
    "message": "Cannot read properties of undefined (reading 'cart')",
    "file": "https://shop.example/assets/app-9f2.js",
    "line": 421,
    "column": 17,
    "stack": ("TypeError: Cannot read properties of undefined (reading 'cart')\n"
              "    at CartTotal (https://shop.example/assets/app-9f2.js:421:17)\n"
              "    at render (https://shop.example/assets/vendor.js:88:3)"),
    "url": "https://shop.example/checkout",
    "userAgent": "test",
}


def test_telemetry_creates_service_incident_forensics():
    with TestClient(app) as c:  # no auth: public ingest by design
        r = c.post("/api/telemetry/crash", json=BROWSER_CRASH)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deduped"] is False
        assert body["location"].startswith("app-9f2.js:421")
        assert len(body["fingerprint"]) == 12
        db = SessionLocal()
        try:
            inc = db.get(Incident, body["incident_id"])
            assert inc.type == "frontend" and inc.status == "DIAGNOSED"
            assert "cart" in (inc.diagnoses[0].explanation)
            svc = db.get(Service, inc.service_id)
            assert svc.name == "webshop" and svc.restart_policy == "never"
        finally:
            db.close()


def test_telemetry_dedups_repeats():
    with TestClient(app) as c:
        first = c.post("/api/telemetry/crash", json={**BROWSER_CRASH, "service": "webshop2"}).json()
        second = c.post("/api/telemetry/crash", json={**BROWSER_CRASH, "service": "webshop2"}).json()
        assert second["deduped"] is True
        assert second["incident_id"] == first["incident_id"]


def test_passive_service_never_alarms():
    import asyncio
    from app.engines import health_engine
    db = SessionLocal()
    try:
        svc = Service(name="passive-x", type="http", health_check_type="http",
                      health_check_url="")
        snap = asyncio.run(health_engine.check(svc))
        assert snap["ok"] is True and snap["status"] == "HEALTHY"
    finally:
        db.close()
