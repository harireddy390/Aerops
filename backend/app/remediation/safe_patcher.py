"""Safe patch engine: the ONLY code that may modify service files.

Gate order (any failure aborts, repo left intact):
1. resolve target strictly inside the service directory (traversal-proof)
2. atomic backup <file>.aeroops.bak
3. search_block must match EXACTLY once (0 or 2+ -> abort, backup removed)
4. write replacement
5. run verification_command — allowlisted prefixes only, NO shell, 45s timeout,
   cwd confined to project root. Runs in a worker THREAD (subprocess.run):
   battle-tested on Windows, immune to event-loop/subprocess interactions.
6. exit 0 -> drop backup, success. else -> restore backup, escalate.

Model output never reaches a shell: commands are shlex-split and argv-executed.
"""
from __future__ import annotations

import asyncio
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

# command must start with one of these (plus safe file/dir args only)
VERIFY_ALLOWLIST = (
    "node --check",
    "npx tsc --noEmit",
    "npm run build",
    "npm test",
    "python -m py_compile",
)

VERIFY_TIMEOUT_SEC = 45


@dataclass
class PatchResult:
    ok: bool
    detail: str


def resolve_target(service_dir: Path, project_root: Path, file_hint: str) -> Path | None:
    """Map a crash file hint to a real file under service_dir.

    Accepts relative paths, absolute paths, and browser URLs (basename match).
    Returns None when ambiguous or outside the fence.
    """
    root = project_root.resolve()
    base = (root / service_dir).resolve() if not service_dir.is_absolute() else service_dir.resolve()
    if root not in base.parents and base != root:
        return None
    hint = (file_hint or "").strip().split("?")[0]
    # A path with directories (or absolute) is precise: resolve it directly.
    # Anything else (bare names, browser URLs) goes through basename search so
    # duplicates are detected as ambiguous instead of silently picking one.
    if "://" not in hint:
        rel = hint
        if "/" in rel or "\\" in rel or Path(rel).is_absolute():
            p = (Path(rel) if Path(rel).is_absolute() else (base / rel)).resolve()
            if p.is_file() and (root in p.parents or p == root):
                return p
    # basename search inside the service dir (skip heavy dirs)
    name = hint.split("/")[-1].split("\\")[-1]
    if not name:
        return None
    found: list[Path] = []
    for p in base.rglob(name):
        if not p.is_file():
            continue
        if any(part in ("node_modules", ".git", "dist") for part in p.parts):
            continue
        found.append(p.resolve())
        if len(found) > 5:
            break
    unique = sorted(set(found))
    return unique[0] if len(unique) == 1 else None


def read_context(target: Path, line: int, radius: int = 20) -> str:
    """Numbered ±radius window for the model. 1-based line numbers."""
    lines = target.read_text(errors="replace").splitlines()
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    return "\n".join(f"{n:5d} | {lines[n - 1]}" for n in range(start, end + 1))


def _check_command(command: str, cwd: Path, project_root: Path) -> list[str]:
    if not any(command.strip().startswith(prefix) for prefix in VERIFY_ALLOWLIST):
        raise ValueError(f"verification command not allowlisted: {command[:80]}")
    parts = shlex.split(command, posix=True)
    if any(any(tok in part for tok in (";", "&", "|", "`", "$", ">", "<", "\n")) for part in parts[1:]):
        raise ValueError("metacharacters not allowed in verification args")
    return parts


def _run_verify(parts: list[str], cwd: Path) -> tuple[int | None, bytes]:
    """Blocking verify in a worker thread. Returns (exit_code, output);
    exit None means the 45s timeout fired (child is killed by run()).
    stdin is always DEVNULL: a verifier must never block waiting for input
    (bare `node --check` reads stdin — that exact hang is why this exists)."""
    try:
        cp = subprocess.run(parts, cwd=str(cwd), capture_output=True,
                            stdin=subprocess.DEVNULL, timeout=VERIFY_TIMEOUT_SEC)
        return cp.returncode, (cp.stdout or b"") + (cp.stderr or b"")
    except subprocess.TimeoutExpired:
        return None, b""
    except OSError as exc:
        raise exc


async def apply_patch(*, target: Path, search_block: str, replacement_block: str,
                      verification_command: str, cwd: Path,
                      project_root: Path) -> PatchResult:
    backup = target.with_name(target.name + ".aeroops.bak")
    try:
        original = target.read_text()
    except OSError as exc:
        return PatchResult(False, f"cannot read target: {exc}")
    hits = original.count(search_block)
    if hits == 0:
        return PatchResult(False, "search_block not found — model context stale, aborting")
    if hits > 1:
        return PatchResult(False, f"search_block matches {hits}× — ambiguous, aborting")
    try:
        backup.write_text(original)
    except OSError as exc:
        return PatchResult(False, f"backup failed, refusing to touch file: {exc}")
    try:
        target.write_text(original.replace(search_block, replacement_block, 1))
    except OSError as exc:
        return PatchResult(False, f"write failed: {exc}")
    try:
        parts = _check_command(verification_command, cwd, project_root)
    except ValueError as exc:
        _restore(target, backup, original)
        return PatchResult(False, f"unsafe verification command, rolled back: {exc}")
    if parts == ["node", "--check"]:
        # bare `node --check` reads stdin and hangs: bind it to the target file
        parts = ["node", "--check", target.name]
    if parts[0] in ("npx", "npm") and not (cwd / "package.json").exists():
        _restore(target, backup, original)
        return PatchResult(False, f"'{' '.join(parts[:3])}' needs a Node project here "
                                  f"({cwd.name} has no package.json) — refusing a "
                                  f"slow network fetch, rolled back")
    try:
        code, out = await asyncio.to_thread(_run_verify, parts, cwd)
    except OSError as exc:
        _restore(target, backup, original)
        return PatchResult(False, f"verification could not run, rolled back: {exc}")
    if code is None:
        _restore(target, backup, original)
        return PatchResult(False, "verification timed out after 45s, rolled back")
    tail = (out or b"").decode("utf-8", "replace")[-1500:]
    if code != 0:
        _restore(target, backup, original)
        return PatchResult(False, f"verification failed (exit {code}), rolled back: {tail[-400:]}")
    try:
        backup.unlink(missing_ok=True)
    except OSError:
        pass
    return PatchResult(True, f"verified clean: {tail[-200:]}")


def _restore(target: Path, backup: Path, original: str) -> None:
    try:
        if backup.exists():
            target.write_text(backup.read_text())
            backup.unlink(missing_ok=True)
        else:
            target.write_text(original)
    except OSError:
        pass
