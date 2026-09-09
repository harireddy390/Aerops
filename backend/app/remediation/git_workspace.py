"""Git-native workspace: isolate every auto-fix on its own branch.

Live processes keep running untouched HEAD while the fix is built and
verified aside. Failure => branch deleted, tree restored to exact HEAD.
Success => conventional commit, ready for the delivery gate.
All git invocations are argv lists (never shell), cwd-confined, time-boxed.
"""
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

GIT_TIMEOUT_SEC = 30


@dataclass
class Workspace:
    repo: Path
    branch: str
    base_ref: str  # HEAD the branch forked from


async def _git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT_SEC) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(repo),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return 124, "git timed out"
    text = (out or b"").decode("utf-8", "replace")[-2000:]
    return proc.returncode or 0, text


def is_repo(path: Path) -> bool:
    return (path / ".git").is_dir()


async def status_clean(repo: Path) -> tuple[bool, str]:
    code, out = await _git(repo, "status", "--porcelain")
    if code != 0:
        return False, f"git status failed: {out[-200:]}"
    return (out.strip() == ""), out.strip()[:500]


async def current_branch(repo: Path) -> str:
    code, out = await _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() if code == 0 else ""


async def open_workspace(repo: Path, incident_id: int, fingerprint: str) -> Workspace:
    """Fork an isolated fix branch. Raises RuntimeError on any safety violation."""
    repo = repo.resolve()
    if not is_repo(repo):
        raise RuntimeError(f"not a git repo: {repo}")
    clean, dirty = await status_clean(repo)
    if not clean:
        raise RuntimeError(f"working tree dirty, refusing to touch it: {dirty[:200]}")
    code, head = await _git(repo, "rev-parse", "HEAD")
    if code != 0:
        raise RuntimeError(f"cannot read HEAD: {head[-200:]}")
    head = head.strip()
    branch = f"aeroops/fix-{incident_id}-{fingerprint[:8] or head[:8]}"
    await _git(repo, "branch", "-D", branch)  # stale retry from an earlier run
    code, out = await _git(repo, "checkout", "-b", branch, head)
    if code != 0:
        raise RuntimeError(f"cannot create fix branch: {out[-200:]}")
    return Workspace(repo=repo, branch=branch, base_ref=head)


async def commit_fix(ws: Workspace, *, incident_id: int, fingerprint: str,
                     root_cause: str, model: str) -> tuple[bool, str]:
    code, out = await _git(ws.repo, "add", "-A")
    if code != 0:
        return False, f"git add failed: {out[-200:]}"
    code, diff_stat = await _git(ws.repo, "diff", "--cached", "--stat")
    if code != 0 or not diff_stat.strip():
        return False, "nothing to commit (patch produced no diff)"
    msg = (f"fix(aeroops): auto-remediate {fingerprint}\n\n"
           f"Incident: #{incident_id}\nRoot-Cause: {root_cause[:200]}\n"
           f"Diagnosis-Model: {model}")
    code, out = await _git(ws.repo, "commit", "-m", msg)
    if code != 0:
        return False, f"git commit failed: {out[-300:]}"
    return True, diff_stat.strip()[:500]


async def abandon(ws: Workspace) -> str:
    """Delete the fix branch, restore tracked tree to exact base commit.
    Leaves HEAD detached at base (a safe, exact state); the delivery gate
    checks out the deploy branch when it takes over. Deliberately NO
    `git clean`: untracked user files are never ours to delete."""
    try:
        base = ws.base_ref
        code, cur = await _git(ws.repo, "rev-parse", "--abbrev-ref", "HEAD")
        if cur.strip() == ws.branch:
            await _git(ws.repo, "checkout", "-q", base)
        code, out = await _git(ws.repo, "branch", "-D", ws.branch)
        await _git(ws.repo, "reset", "--hard", "-q", base)
        return "abandoned" if code == 0 else f"branch delete said: {out[-200:]}"
    except Exception as exc:
        return f"abandon best-effort: {exc}"


async def merge_fast_forward(ws: Workspace, deploy_branch: str) -> tuple[bool, str]:
    """Fast-forward deploy_branch to the fix commit. No merge commits, no force."""
    code, cur = await _git(ws.repo, "rev-parse", "--abbrev-ref", "HEAD")
    try:
        code, out = await _git(ws.repo, "checkout", "-q", deploy_branch)
        if code != 0:
            return False, f"cannot checkout {deploy_branch}: {out[-200:]}"
        code, out = await _git(ws.repo, "merge", "--ff-only", "-q", ws.branch)
        if code != 0:
            await _git(ws.repo, "merge", "--abort")
            return False, f"not fast-forwardable (diverged): {out[-200:]}"
        code, out = await _git(ws.repo, "branch", "-d", ws.branch)
        return True, f"merged {ws.branch} into {deploy_branch}"
    finally:
        # leave the tree on the deploy branch either way
        await _git(ws.repo, "checkout", "-q", deploy_branch)
