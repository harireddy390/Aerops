"""Realistic-AI tests: OpenAI degrades without key, chain falls back to rules,
email never sends unconfigured and never breaks notify."""
import asyncio

import tests.conftest  # noqa: F401
from app.db.database import SessionLocal, init_db
from app.db.models import Service
from app.diagnosis import openai_diagnoser
from app.engines import diagnosis_engine, notification_engine


def test_openai_no_key_returns_none():
    assert openai_diagnoser.configured() is False
    assert asyncio.run(openai_diagnoser.diagnose_structured({"error": "boom"})) is None


def test_chain_falls_back_to_rules_without_providers():
    async def go():
        return await diagnosis_engine.ai_opinion({"error": "EADDRINUSE Navarro"})
    # key absent + ollama host dead (conftest) -> (None, "")
    opinion, provider = asyncio.run(go())
    assert opinion is None and provider == ""


def test_email_unconfigured_is_safe():
    assert notification_engine.email_configured() is False
    assert notification_engine.send_email("t", "b") is False
    init_db()
    db = SessionLocal()
    try:
        svc = Service(name="mail-test", command="x")
        db.add(svc)
        db.commit()
        note = notification_engine.notify(db, "hello", "world")
        assert note.channel == "dashboard" and note.delivered is True
        db.commit()
    finally:
        db.close()


def test_rules_record_model_field():
    from app.engines import incident_engine
    init_db()
    db = SessionLocal()
    try:
        svc = Service(name="model-field-test", command="x")
        db.add(svc)
        db.commit()
        inc = incident_engine.create_incident(db, service_id=svc.id, type="crash",
                                              severity="critical", error_message="boom")
        diag = diagnosis_engine.diagnose_rules(db, inc, log_text="boom")
        assert diag.source == "rule" and diag.model == "rules"
        db.commit()
    finally:
        db.close()
