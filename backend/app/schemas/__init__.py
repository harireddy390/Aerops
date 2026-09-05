"""Pydantic schemas: every API input validated here."""
from datetime import datetime

from pydantic import BaseModel, Field

STATUSES = {"HEALTHY", "WARNING", "DEGRADED", "UNHEALTHY", "CRASHED", "RESTARTING", "RECOVERING", "RECOVERED", "UNKNOWN", "STOPPED"}
INCIDENT_STATUSES = {"OPEN", "INVESTIGATING", "DIAGNOSED", "REMEDIATING", "RECOVERING", "RESOLVED", "FAILED", "ACKNOWLEDGED"}


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    type: str = Field(default="process", pattern="^(process|http)$")
    command: str = ""
    working_directory: str = "."
    env_config: dict = {}
    health_check_type: str = Field(default="process", pattern="^(process|http)$")
    health_check_url: str = ""
    health_check_interval: int = Field(default=5, ge=1, le=3600)
    timeout_sec: int = Field(default=5, ge=1, le=120)
    restart_policy: str = Field(default="on-failure", pattern="^(always|on-failure|never)$")
    max_restart_attempts: int = Field(default=3, ge=0, le=20)
    cooldown_sec: int = Field(default=5, ge=0, le=3600)
    auto_remediation: bool = True
    ai_diagnosis: bool = True
    notifications_enabled: bool = True
    enabled: bool = True


class ServiceUpdate(BaseModel):
    description: str | None = None
    type: str | None = Field(default=None, pattern="^(process|http)$")
    command: str | None = None
    working_directory: str | None = None
    env_config: dict | None = None
    health_check_type: str | None = Field(default=None, pattern="^(process|http)$")
    health_check_url: str | None = None
    health_check_interval: int | None = Field(default=None, ge=1, le=3600)
    timeout_sec: int | None = Field(default=None, ge=1, le=120)
    restart_policy: str | None = Field(default=None, pattern="^(always|on-failure|never)$")
    max_restart_attempts: int | None = Field(default=None, ge=0, le=20)
    cooldown_sec: int | None = Field(default=None, ge=0, le=3600)
    auto_remediation: bool | None = None
    ai_diagnosis: bool | None = None
    notifications_enabled: bool | None = None
    enabled: bool | None = None


class ServiceOut(BaseModel):
    id: int
    name: str
    description: str
    type: str
    status: str
    pid: int | None
    restart_count: int
    health_check_type: str
    health_check_url: str
    restart_policy: str
    max_restart_attempts: int
    auto_remediation: bool
    ai_diagnosis: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IncidentOut(BaseModel):
    id: int
    service_id: int
    type: str
    severity: str
    status: str
    error_message: str
    exit_code: int | None
    restart_attempts: int
    recovery_verified: bool
    detected_at: datetime
    resolved_at: datetime | None
    duration_sec: float | None

    model_config = {"from_attributes": True}


class DiagnoseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class RemediationRequest(BaseModel):
    action_type: str
    params: dict = {}
