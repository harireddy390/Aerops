"""Pydantic schemas: every API input validated here."""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

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
    expected_content: str = Field(default="", max_length=500)
    health_check_interval: int = Field(default=5, ge=1, le=3600)
    timeout_sec: int = Field(default=5, ge=1, le=120)
    restart_policy: str = Field(default="on-failure", pattern="^(always|on-failure|never)$")
    max_restart_attempts: int = Field(default=3, ge=0, le=20)
    cooldown_sec: int = Field(default=5, ge=0, le=3600)
    auto_remediation: bool = True
    ai_diagnosis: bool = True
    notifications_enabled: bool = True
    policy_mode: str = Field(default="DRAFT_PR", pattern="^(AUTO_MERGE|DRAFT_PR)$")
    deploy_branch: str = ""
    repo_path_or_url: str = Field(default="", max_length=500)
    git_token: str = Field(default="", max_length=2000)  # write-only, encrypted at rest
    target_branch: str = Field(default="main", max_length=120)
    workspace_frontend: str = Field(default="./frontend", max_length=200)
    workspace_backend: str = Field(default="./backend", max_length=200)
    test_command: str = Field(default="", max_length=500)
    remediation_policy: str = Field(default="DRAFT_PR",
                                    pattern="^(AUTO_MERGE|DRAFT_PR|MANUAL_APPROVAL)$")
    published_url: str = Field(default="", max_length=500)
    client_api_key: str = Field(default="", max_length=64)
    deploy_webhook_url: str = Field(default="", max_length=500)
    enabled: bool = True

    @field_validator("test_command")
    @classmethod
    def _no_shell(cls, v: str) -> str:
        bad = [";", "&", "|", "`", "$", ">", "<", "\n", "(", ")"]
        if any(ch in v for ch in bad):
            raise ValueError("test_command must be a plain command with arguments, no shell syntax")
        return v

    @field_validator("published_url", "deploy_webhook_url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class ServiceUpdate(BaseModel):
    description: str | None = None
    type: str | None = Field(default=None, pattern="^(process|http)$")
    command: str | None = None
    working_directory: str | None = None
    env_config: dict | None = None
    health_check_type: str | None = Field(default=None, pattern="^(process|http)$")
    health_check_url: str | None = None
    expected_content: str | None = Field(default=None, max_length=500)
    health_check_interval: int | None = Field(default=None, ge=1, le=3600)
    timeout_sec: int | None = Field(default=None, ge=1, le=120)
    restart_policy: str | None = Field(default=None, pattern="^(always|on-failure|never)$")
    max_restart_attempts: int | None = Field(default=None, ge=0, le=20)
    cooldown_sec: int | None = Field(default=None, ge=0, le=3600)
    auto_remediation: bool | None = None
    ai_diagnosis: bool | None = None
    notifications_enabled: bool | None = None
    policy_mode: str | None = Field(default=None, pattern="^(AUTO_MERGE|DRAFT_PR)$")
    deploy_branch: str | None = None
    repo_path_or_url: str | None = Field(default=None, max_length=500)
    git_token: str | None = Field(default=None, max_length=2000)
    target_branch: str | None = Field(default=None, max_length=120)
    workspace_frontend: str | None = Field(default=None, max_length=200)
    workspace_backend: str | None = Field(default=None, max_length=200)
    test_command: str | None = Field(default=None, max_length=500)
    remediation_policy: str | None = Field(default=None,
                                           pattern="^(AUTO_MERGE|DRAFT_PR|MANUAL_APPROVAL)$")
    published_url: str | None = Field(default=None, max_length=500)
    client_api_key: str | None = Field(default=None, max_length=64)
    deploy_webhook_url: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None

    @field_validator("test_command")
    @classmethod
    def _no_shell_update(cls, v: str | None) -> str | None:
        if v is None:
            return v
        bad = [";", "&", "|", "`", "$", ">", "<", "\n", "(", ")"]
        if any(ch in v for ch in bad):
            raise ValueError("test_command must be a plain command with arguments, no shell syntax")
        return v

    @field_validator("published_url", "deploy_webhook_url")
    @classmethod
    def _http_url_update(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


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
    expected_content: str = ""
    restart_policy: str
    max_restart_attempts: int
    auto_remediation: bool
    ai_diagnosis: bool
    policy_mode: str = "DRAFT_PR"
    deploy_branch: str = ""
    repo_path_or_url: str = ""
    target_branch: str = "main"
    workspace_frontend: str = "./frontend"
    workspace_backend: str = "./backend"
    test_command: str = ""
    remediation_policy: str = "DRAFT_PR"
    published_url: str = ""
    client_api_key: str = ""
    deploy_webhook_url: str = ""
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
    fingerprint: str = ""

    model_config = {"from_attributes": True}


class DiagnoseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class RemediationRequest(BaseModel):
    action_type: str
    params: dict = {}
