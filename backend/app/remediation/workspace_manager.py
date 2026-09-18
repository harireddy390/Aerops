"""Automated Git Workspace Manager.

Automatically manages cloned remote repositories inside `workspaces/svc_{service_id}`.
Ensures zero manual cloning: user enters a GitHub URL, and AeroOps clones and syncs
the repo securely in the background using the encrypted service token.
"""
from __future__ import annotations

import asyncio
import base64
import os
import shutil
from pathlib import Path
import subprocess

from app.core.crypto import decrypt_token
from app.core.logging import get_logger
from app.engines.restart_manager import PROJECT_ROOT

log = get_logger("workspace-manager")

WORKSPACES_DIR = (PROJECT_ROOT / "workspaces").resolve()


def is_remote_url(url_or_path: str) -> bool:
    text = (url_or_path or "").strip().lower()
    return text.startswith(("http://", "https://", "git@", "ssh://"))


def workspace_dir_for(service_id: int) -> Path:
    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    return (WORKSPACES_DIR / f"svc_{service_id}").resolve()


async def _git_exec(cwd: Path, *args: str, git_token: str = "", timeout: int = 60) -> tuple[int, str]:
    """Execute git command with optional per-invocation token header (never logged)."""
    cmd = ["git"]
    if git_token:
        creds = base64.b64encode(f"x-access-token:{git_token}".encode()).decode()
        cmd.extend(["-c", f"http.extraHeader=AUTHORIZATION: basic {creds}"])
    cmd.extend(args)

    def _run() -> tuple[int, str]:
        try:
            cp = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd.exists() else None,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
            out = ((cp.stdout or b"") + (cp.stderr or b"")).decode("utf-8", "replace")
            return cp.returncode, out[-1500:]
        except subprocess.TimeoutExpired:
            return 124, "git timed out"
        except Exception as exc:
            return -1, f"git execution failed: {exc}"

    return await asyncio.to_thread(_run)


async def ensure_workspace(service, *, git_token: str = "") -> Path:
    """Ensure a local workspace exists for the service.
    
    If service.repo_path_or_url is a remote git URL:
      - Clones into workspaces/svc_{id} if absent.
      - Fetches and syncs target branch if present.
    Otherwise:
      - Resolves local working_directory under PROJECT_ROOT.
    """
    repo_url = (getattr(service, "repo_path_or_url", "") or "").strip()
    token = git_token or decrypt_token(getattr(service, "git_token_enc", "") or "")
    branch = getattr(service, "target_branch", "") or getattr(service, "deploy_branch", "") or "main"

    if not is_remote_url(repo_url):
        # Local path
        workdir = getattr(service, "working_directory", "") or "."
        return (PROJECT_ROOT / workdir).resolve()

    ws_dir = workspace_dir_for(service.id)

    # 1. Clone if not present
    if not (ws_dir / ".git").is_dir():
        log.info(f"cloning remote repo {repo_url} into {ws_dir.name} on branch {branch}")
        if ws_dir.exists():
            shutil.rmtree(ws_dir, ignore_errors=True)
        ws_dir.mkdir(parents=True, exist_ok=True)

        code, out = await _git_exec(
            PROJECT_ROOT,
            "clone",
            "--depth", "20",
            "-b", branch,
            repo_url,
            str(ws_dir),
            git_token=token,
            timeout=120,
        )
        if code != 0:
            log.warning(f"failed to shallow clone {repo_url}: {out}")
            # Try full clone without branch flag if branch name differed
            code, out = await _git_exec(
                PROJECT_ROOT,
                "clone",
                repo_url,
                str(ws_dir),
                git_token=token,
                timeout=120,
            )
            if code != 0:
                raise RuntimeError(f"Could not clone repository: {out[-300:]}")

    # 2. Refresh origin if already present
    else:
        log.info(f"refreshing existing workspace {ws_dir.name}")
        await _git_exec(ws_dir, "fetch", "--prune", "origin", branch, git_token=token, timeout=30)

    # Update service working_directory relative to PROJECT_ROOT
    try:
        rel = ws_dir.relative_to(PROJECT_ROOT)
        service.working_directory = str(rel).replace("\\", "/")
    except Exception:
        pass

    return ws_dir
