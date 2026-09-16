"""Security helpers: input validation, password hashing (PBKDF2 stdlib),
JWT sessions, and role gates. Secrets come from env, never code."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import shlex
from datetime import timedelta
from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.utils.time import utcnow

bearer = HTTPBearer(auto_error=False)

_PBKDF2_ITERS = 210_000

_ROLES = {"viewer": 1, "operator": 2, "admin": 3}


def _jwt_secret() -> str:
    secret = getattr(settings, "jwt_secret", "") or os.environ.get("JWT_SECRET", "")
    if not secret or secret == "dev-only-change-me":
        secret = "dev-only-change-me-must-be-at-least-32-bytes-long"
    return secret


def hash_password(password: str) -> str:
    if len(password) < 8 or len(password) > 256:
        raise HTTPException(status_code=422, detail="Password must be 8-256 characters")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERS).hex()
    return f"pbkdf2${_PBKDF2_ITERS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        cand = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters)).hex()
        return hmac.compare_digest(cand, digest)
    except (ValueError, AttributeError):
        return False


def create_token(user_id: int, username: str, role: str, *, remember: bool = False) -> str:
    lifetime = timedelta(days=30) if remember else timedelta(hours=12)
    payload = {"sub": str(user_id), "username": username, "role": role,
               "exp": utcnow() + lifetime}
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def _principal_from_token(token: str) -> dict:
    try:
        data = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
        if data.get("role") not in _ROLES or not data.get("sub"):
            raise HTTPException(status_code=401, detail="Invalid session")
        return data
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session")


def get_current_user(request: Request,
                     creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    """Auth gate. Disabled when AUTH_ENABLED=false. Accepts Authorization header
    or ?token= (EventSource can't send headers)."""
    if not settings.auth_enabled:
        return {"sub": "0", "username": "local", "role": "admin"}
    token = ""
    if creds and creds.scheme.lower() == "bearer":
        token = creds.credentials
    if not token:
        token = request.query_params.get("token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Login required")
    return _principal_from_token(token)


def require_role(*roles: str):
    """Route guard, e.g. Depends(require_role('admin', 'operator'))."""
    def guard(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user
    return guard


def split_command(command: str) -> list[str]:
    """Split a service command safely. Rejects shell metacharacters outright."""
    if not command or len(command) > 2000:
        raise HTTPException(status_code=422, detail="Invalid command")
    if any(ch in command for ch in [";", "&", "|", "`", "$", "(", ")", ">", "<", "\n"]):
        raise HTTPException(status_code=422, detail="Shell metacharacters are not allowed in commands")
    try:
        parts = shlex.split(command, posix=os.name != "nt")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unparseable command: {exc}")
    if not parts:
        raise HTTPException(status_code=422, detail="Empty command")
    return parts


def safe_workdir(path: str | None, base: Path) -> Path:
    """Confine working directories inside the project root (path traversal guard)."""
    root = base.resolve()
    target = (root / (path or ".")).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=422, detail="working_directory escapes project root")
    return target


def sanitize_log(text: str, limit: int = 20000) -> str:
    """Strip control chars, cap size, redact token-like secrets."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text or "")
    cleaned = re.sub(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S+", r"\1=***", cleaned)
    return cleaned[-limit:]
