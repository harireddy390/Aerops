"""Relational model. Foreign keys + indexes on service_id / status / timestamps / severity."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.utils.time import utcnow


def _now() -> datetime:
    return utcnow()


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(20), default="process")  # process | http
    command: Mapped[str] = mapped_column(Text, default="")
    working_directory: Mapped[str] = mapped_column(String(500), default=".")
    env_config: Mapped[dict] = mapped_column(JSON, default=dict)
    health_check_type: Mapped[str] = mapped_column(String(20), default="process")  # process | http
    health_check_url: Mapped[str] = mapped_column(String(500), default="")
    expected_content: Mapped[str] = mapped_column(String(500), default="")
    health_check_interval: Mapped[int] = mapped_column(Integer, default=5)
    timeout_sec: Mapped[int] = mapped_column(Integer, default=5)
    restart_policy: Mapped[str] = mapped_column(String(20), default="on-failure")  # always|on-failure|never
    max_restart_attempts: Mapped[int] = mapped_column(Integer, default=3)
    cooldown_sec: Mapped[int] = mapped_column(Integer, default=5)
    auto_remediation: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_diagnosis: Mapped[bool] = mapped_column(Boolean, default=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="UNKNOWN", index=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    restart_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    incidents: Mapped[list["Incident"]] = relationship(back_populates="service", cascade="all, delete-orphan")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40), default="crash")
    severity: Mapped[str] = mapped_column(String(20), default="critical", index=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    fingerprint: Mapped[str] = mapped_column(String(32), default="", index=True)
    restart_attempts: Mapped[int] = mapped_column(Integer, default=0)
    recovery_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    service: Mapped[Service] = relationship(back_populates="incidents")
    events: Mapped[list["IncidentEvent"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    diagnoses: Mapped[list["Diagnosis"]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    actions: Mapped[list["RemediationAction"]] = relationship(back_populates="incident", cascade="all, delete-orphan")


class IncidentEvent(Base):
    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    incident: Mapped[Incident] = relationship(back_populates="events")


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # rule | ai | rule+ai
    model: Mapped[str] = mapped_column(String(80), default="")  # e.g. gpt-4o-mini, qwen2.5-coder:7b, rules
    root_cause: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    recommended_action: Mapped[str] = mapped_column(String(60), default="restart_service")
    risk_level: Mapped[str] = mapped_column(String(10), default="low")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    incident: Mapped[Incident] = relationship(back_populates="diagnoses")


class RemediationAction(Base):
    __tablename__ = "remediation_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(20), default="automation")  # automation | operator | ai-recommendation
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    incident: Mapped[Incident] = relationship(back_populates="actions")


class ServiceMetric(Base):
    __tablename__ = "service_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), index=True)
    cpu_pct: Mapped[float] = mapped_column(Float, default=0.0)
    mem_mb: Mapped[float] = mapped_column(Float, default=0.0)
    response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class ServiceLog(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), index=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True)
    stream: Mapped[str] = mapped_column(String(10), default="stdout")
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), default="dashboard")  # dashboard|log|webhook|...
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event: Mapped[str] = mapped_column(String(40), index=True)
    service_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    incident_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(40), default="system")
    action: Mapped[str] = mapped_column(String(80), default="")
    result: Mapped[str] = mapped_column(String(40), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


Index("ix_metrics_service_time", ServiceMetric.service_id, ServiceMetric.timestamp)


class User(Base):
    """Console operator. Roles: admin (everything) > operator (act, no user mgmt)
    > viewer (read-only). Passwords: PBKDF2-HMAC-SHA256, never plaintext."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # admin|operator|viewer
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PasswordReset(Base):
    """Single-use 6-digit email codes for forgotten passwords. Codes are stored
    hashed; expire in 15 min; max 5 attempts each."""

    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
