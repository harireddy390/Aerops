"""Central configuration. Environment variables win over defaults. No secrets hardcoded."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "AeroOps"
    api_port: int = 8000
    log_level: str = "INFO"

    # sqlite:///./aeroops.db is relative to backend/ cwd. Use absolute URL for Postgres later.
    database_url: str = "sqlite:///./aeroops.db"

    default_health_interval: int = 5
    max_restart_attempts: int = 3
    restart_cooldown_sec: int = 5
    monitor_enabled: bool = True
    recovery_verify_checks: int = 3
    recovery_verify_interval: int = 2

    ollama_enabled: bool = True
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    ollama_timeout_sec: int = 45
    # code-fix generations are long; diagnosis stays snappy
    ollama_code_timeout_sec: int = 180

    # Cloud AI (optional primary). Key lives in backend/.env only.
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_sec: int = 30

    # Gmail SMTP (optional). Use a Google App Password, never your login password.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    mail_from: str = ""
    mail_to: str = ""

    metrics_retention_days: int = 7
    log_tail_lines: int = 200
    cors_origins: str = "http://localhost:5173,http://localhost:5174,http://localhost:3000"

    # Auth is ON: first registered user becomes admin, then registration closes.
    auth_enabled: bool = True
    # When true, anyone can sign up — but only ever as viewer.
    # Admins/operators are promoted in Settings → Team.
    allow_open_signup: bool = True
    seed_demos: bool = True


settings = Settings()
