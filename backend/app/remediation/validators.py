"""Validators for remediation params (path traversal / injection guards)."""
import re
from pathlib import Path

from app.core.exceptions import PolicyDenied

_PACKAGE_RE = re.compile(r"^(?:@[a-z0-9][a-z0-9._\-]*/)?[a-zA-Z0-9][a-zA-Z0-9._\-]{0,100}$")


def validate_temp_dir(path: str, project_root: Path) -> Path:
    target = (project_root / path).resolve()
    if project_root.resolve() not in target.parents:
        raise PolicyDenied("temp dir escapes project root")
    if len(target.parts) <= len(project_root.resolve().parts):
        raise PolicyDenied("refusing to clear project root itself")
    return target


def validate_package(name: str) -> str:
    """A dependency name is data, never a command: strict allowlist, no flags,
    no URLs, no version specifiers that smuggle shell."""
    name = (name or "").strip()
    if not name or not _PACKAGE_RE.match(name):
        raise PolicyDenied(f"refusing to install '{name}': not a plain package name")
    if name.startswith(("-", ".")) or ".." in name or ";" in name or "&" in name:
        raise PolicyDenied(f"refusing to install '{name}'")
    if "://" in name or name.endswith((".tgz", ".tar.gz", ".zip", ".git")):
        raise PolicyDenied("only registry package names, never URLs/archives")
    return name


def validate_service_dir(workdir: str, project_root: Path) -> Path:
    target = (project_root / (workdir or ".")).resolve()
    if project_root.resolve() not in target.parents and target != project_root.resolve():
        raise PolicyDenied("service directory escapes project root")
    return target
