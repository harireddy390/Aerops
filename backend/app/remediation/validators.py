"""Validators for remediation params (path traversal / injection guards)."""
from pathlib import Path

from app.core.exceptions import PolicyDenied


def validate_temp_dir(path: str, project_root: Path) -> Path:
    target = (project_root / path).resolve()
    if project_root.resolve() not in target.parents:
        raise PolicyDenied("temp dir escapes project root")
    if len(target.parts) <= len(project_root.resolve().parts):
        raise PolicyDenied("refusing to clear project root itself")
    return target
