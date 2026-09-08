"""Dependency auto-heal tests: validators, policy, extraction, safe failure."""
import asyncio

import pytest

import tests.conftest  # noqa: F401
from app.core.exceptions import PolicyDenied
from app.db.database import SessionLocal, init_db
from app.db.models import Service
from app.diagnosis.rule_engine import diagnose, extract_package
from app.engines import incident_engine, remediation_engine
from app.remediation import policies, validators


def test_extract_package():
    assert extract_package("ModuleNotFoundError: No module named 'psycopg'") == "psycopg"
    assert extract_package("No module named 'a.b.c'") == "a"
    assert extract_package("Error: Cannot find module 'left-pad'") == "left-pad"
    assert extract_package("random noise") == ""


def test_validators():
    assert validators.validate_package("requests") == "requests"
    assert validators.validate_package("@scope/pkg") == "@scope/pkg"
    for evil in ["", "x; rm -rf /", "../../etc", "-U", "http://x/y.tgz",
                 "pkg.tar.gz", "$(evil)", "a|b", "pkg==1.0;curl"]:
        with pytest.raises(PolicyDenied):
            validators.validate_package(evil)
    with pytest.raises(PolicyDenied):
        validators.validate_service_dir("../../..", __import__("pathlib").Path(".").resolve())


def test_policy_and_rule_recommend_install():
    assert policies.evaluate("install_dependency", auto_remediation=True).allowed
    assert not policies.evaluate("install_dependency", auto_remediation=False).allowed
    assert diagnose("ModuleNotFoundError: No module named 'x'").recommended_action == "install_dependency"


def test_install_without_package_fails_safe():
    init_db()
    db = SessionLocal()
    try:
        svc = Service(name="dep-test", command="python app.py", working_directory=".")
        db.add(svc)
        db.commit()
        inc = incident_engine.create_incident(db, service_id=svc.id, type="crash",
                                              severity="warning", error_message="boom")
        action = asyncio.run(remediation_engine.execute(db, inc, "install_dependency",
                                                        source="automation", params={}))
        assert action.status in ("failed", "denied")
        db.commit()
    finally:
        db.close()
