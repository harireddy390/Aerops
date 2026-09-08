"""Content-check tests: blank pages fail even on HTTP 200."""
import asyncio
import functools
import http.server
import threading

import tests.conftest  # noqa: F401
from app.db.database import SessionLocal, init_db
from app.db.models import Service
from app.engines import health_engine


class _H(http.server.BaseHTTPRequestHandler):
    body = b"<html><body></body></html>"  # blank-ish page, status 200

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


def _serve(port: int):
    srv = http.server.HTTPServer(("127.0.0.1", port), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_blank_page_passes_without_content_rule():
    init_db()
    db = SessionLocal()
    try:
        _serve(4194)
        svc = Service(name="blank-norule", health_check_type="http",
                      health_check_url="http://localhost:4194")
        snap = asyncio.run(health_engine.check(svc))
        assert snap["ok"] is True and snap["status"] == "HEALTHY"
    finally:
        db.close()


def test_blank_page_fails_with_content_rule():
    init_db()
    db = SessionLocal()
    try:
        _serve(4193)
        svc = Service(name="blank-rule", health_check_type="http",
                      health_check_url="http://localhost:4193",
                      expected_content="Welcome")
        snap = asyncio.run(health_engine.check(svc))
        assert snap["ok"] is False and snap["status"] == "UNHEALTHY"
        assert "missing expected text" in snap["detail"]
        from app.diagnosis.rule_engine import diagnose
        assert diagnose(snap["detail"]).root_cause == "Content check failed"
    finally:
        db.close()


def test_content_present_passes():
    _H.body = b"<html><body>Welcome home</body></html>"
    init_db()
    db = SessionLocal()
    try:
        _serve(4192)
        svc = Service(name="full-rule", health_check_type="http",
                      health_check_url="http://localhost:4192",
                      expected_content="Welcome")
        snap = asyncio.run(health_engine.check(svc))
        assert snap["ok"] is True
    finally:
        db.close()
        _H.body = b"<html><body></body></html>"
