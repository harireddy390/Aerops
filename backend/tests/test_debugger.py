"""Automated-debugger tests: stack parsing, fingerprints, evidence rules."""
import tests.conftest  # noqa: F401
from app.db.database import SessionLocal, init_db
from app.db.models import Service
from app.diagnosis import rule_engine
from app.diagnosis.stackparse import fingerprint, parse
from app.engines import incident_engine

PY_TB = """Traceback (most recent call last):
  File "/app/server.py", line 42, in handle
    process(payload)
  File "/app/worker.py", line 17, in process
    db.save(item)
ModuleNotFoundError: No module named 'psycopg'
"""

NODE_TB = """[AeroOps Server] uncaughtException: TypeError: Cannot read properties of undefined (reading 'profile')
    at Timeout._onTimeout (C:\\AeroOps-Project\\server.js:46:22)
    at listOnTimeout (node:internal/timers:605:17)
"""


def test_parse_python_traceback():
    ev = parse(PY_TB)
    assert ev.language == "python"
    assert ev.exc_type == "ModuleNotFoundError"
    assert ev.location.startswith("worker.py:17")
    assert len(ev.fingerprint) == 12


def test_parse_node_stack_skips_internals():
    ev = parse(NODE_TB)
    assert ev.language == "node"
    assert ev.exc_type == "TypeError"
    assert ev.location.startswith("server.js:46")
    assert all("node:internal" not in f.file for f in ev.frames)


def test_fingerprint_stable_and_specific():
    a = parse(PY_TB).fingerprint
    assert a == parse(PY_TB).fingerprint
    assert a != parse(PY_TB.replace("worker.py", "other.py")).fingerprint
    assert fingerprint("", None) == ""


def test_detailed_rules_name_evidence():
    ev = parse(PY_TB)
    rule, evidence = rule_engine.diagnose_detailed(PY_TB, ev)
    assert rule.root_cause == "Missing Python dependency"
    assert "psycopg" in rule.explanation
    assert "worker.py:17" in rule.explanation
    rule2, _ = rule_engine.diagnose_detailed(NODE_TB, parse(NODE_TB))
    assert "profile" in rule2.explanation and "server.js:46" in rule2.explanation


def test_incident_stores_fingerprint_and_counts_repeats():
    init_db()
    db = SessionLocal()
    try:
        svc = Service(name="fp-test", command="x")
        db.add(svc)
        db.commit()
        i1 = incident_engine.create_incident(db, service_id=svc.id, type="crash",
                                             severity="critical", error_message="boom",
                                             fingerprint="abc123")
        i2 = incident_engine.create_incident(db, service_id=svc.id, type="crash",
                                             severity="critical", error_message="boom",
                                             fingerprint="abc123")
        assert i1.fingerprint == "abc123"
        # open-incident reuse returns the same row for a repeat crash
        assert i2.id == i1.id
        db.commit()
    finally:
        db.close()
