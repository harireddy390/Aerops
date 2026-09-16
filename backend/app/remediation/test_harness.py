"""Dual-tier verification harness: syntax first, scoped regression second.

- Phase 1 (15s): parser/linter for the file's language.
- Phase 2 (60s): targeted tests collocated with the change
  (widget.test.js next to widget.js, or `npm test -- <name>`).
- argv execution only, stdin DEVNULL, truncated output (2000 chars).
"""
from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SYNTAX_TIMEOUT_SEC = 15
TEST_TIMEOUT_SEC = 60
OUT_LIMIT = 2000

SYNTAX_BY_SUFFIX = {
    ".py": ["python", "-m", "py_compile"],
    ".js": ["node", "--check"],
    ".jsx": ["node", "--check"],
    ".ts": ["npx", "tsc", "--noEmit"],
    ".tsx": ["npx", "tsc", "--noEmit"],
}


@dataclass
class TierResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class VerifyReport:
    ok: bool
    tiers: list[TierResult] = field(default_factory=list)

    @property
    def failure_text(self) -> str:
        return "\n".join(f"[{t.name}] {t.detail}" for t in self.tiers if not t.ok)[:2000]


async def _run(argv: list[str], cwd: Path, timeout: int) -> tuple[int | None, str]:
    def _call() -> tuple[int | None, str]:
        try:
            cp = subprocess.run(argv, cwd=str(cwd), capture_output=True,
                                stdin=subprocess.DEVNULL, timeout=timeout)
            out = ((cp.stdout or b"") + (cp.stderr or b"")).decode("utf-8", "replace")
            return cp.returncode, out[-OUT_LIMIT:]
        except subprocess.TimeoutExpired as exc:
            part = ((exc.stdout or b"") + (exc.stderr or b"")).decode("utf-8", "replace")
            return None, f"TIMEOUT after {timeout}s: {part[-500:]}"
        except OSError as exc:
            return -1, f"cannot execute: {exc}"

    try:
        return await asyncio.to_thread(_call)
    except Exception as exc:
        return -1, f"harness error: {exc}"


def _check_argv(parts: list[str]) -> list[str]:
    if any(any(tok in part for tok in (";", "&", "|", "`", "$", ">", "<", "\n")) for part in parts):
        raise ValueError("metacharacters not allowed")
    return parts


async def phase_syntax(target: Path) -> TierResult:
    base = SYNTAX_BY_SUFFIX.get(target.suffix.lower())
    if not base:
        return TierResult("syntax", True, f"no parser for {target.suffix or '?'} — skipped")
    argv = _check_argv([*base, target.name])
    code, out = await _run(argv, target.parent, SYNTAX_TIMEOUT_SEC)
    if code is None:
        return TierResult("syntax", False, "syntax check timed out (15s)")
    if code != 0:
        return TierResult("syntax", False, f"exit {code}: {out[-800:]}")
    return TierResult("syntax", True, out[-200:] or "clean")


def _discover_tests(target: Path) -> list[list[str]]:
    """Scoped tests only: collocated <name>.test.* / test_<name>.py, else
    `npm test -- <stem>` filtered run. Never the whole suite blindly."""
    stem = target.stem
    parent = target.parent
    found: list[list[str]] = []
    for pat in (f"{stem}.test.js", f"{stem}.test.ts", f"{stem}.test.jsx",
                f"{stem}.test.tsx", f"test_{stem}.py", f"{stem}_test.py",
                f"{stem}.aeroops.test.js", f"{stem}.aeroops.test.ts",
                f"test_{stem}_aeroops.py"):
        if (parent / pat).exists():
            if pat.endswith(".py"):
                found.append(["python", "-m", "pytest", "-q", pat])
            else:
                found.append(["npx", "jest", pat])
    if not found and (parent / "package.json").exists():
        found.append(["npm", "test", "--", stem])
    return found[:3]


async def phase_regression(target: Path) -> TierResult:
    suites = _discover_tests(target)
    if not suites:
        return TierResult("regression", True, "no collocated tests — skipped (syntax gate stands)")
    import shutil
    failures: list[str] = []
    ran = 0
    for argv in suites:
        if argv[0] in ("npx", "npm") and not (target.parent / "package.json").exists():
            continue
        if argv[0] == "npx" and not (target.parent / "node_modules" / ".bin" / "jest").exists() \
                and not shutil.which("jest"):
            continue  # never trigger network fetches from the harness
        code, out = await _run(_check_argv(argv), target.parent, TEST_TIMEOUT_SEC)
        ran += 1
        if code is None:
            failures.append(f"{' '.join(argv[:3])}: TIMEOUT (60s)")
        elif code != 0:
            failures.append(f"{' '.join(argv[:3])}: exit {code}: {out[-800:]}")
    if ran == 0:
        return TierResult("regression", True, "no runnable scoped tests — skipped")
    if failures:
        return TierResult("regression", False, " | ".join(failures)[:1500])
    return TierResult("regression", True, f"{ran} scoped suite(s) green")


async def verify(target: Path) -> VerifyReport:
    tiers = [await phase_syntax(target)]
    if tiers[0].ok:
        tiers.append(await phase_regression(target))
    else:
        tiers.append(TierResult("regression", False, "skipped: syntax failed"))
    return VerifyReport(ok=all(t.ok for t in tiers), tiers=tiers)


async def run_custom_tests(*, cwd: Path, command: str) -> TierResult:
    """Run the service's own configured test command (validated at
    registration; shlex-split, never shelled). 60s budget."""
    try:
        parts = shlex.split(command, posix=os.name != "nt")
    except ValueError as exc:
        return TierResult("custom-tests", False, f"unparseable test_command: {exc}")
    if not parts:
        return TierResult("custom-tests", False, "empty test_command")
    if any(any(tok in part for tok in (";", "&", "|", "`", "$", ">", "<", "\n"))
           for part in parts):
        return TierResult("custom-tests", False, "test_command failed safety screen")
    code, out = await _run(parts, cwd, TEST_TIMEOUT_SEC)
    if code is None:
        return TierResult("custom-tests", False, f"test command timed out (60s): {command[:80]}")
    if code != 0:
        return TierResult("custom-tests", False, f"exit {code}: {out[-1200:]}")
    return TierResult("custom-tests", True, out[-300:] or "green")


async def verify_with_command(*, target: Path, test_command: str,
                              cwd: Path) -> VerifyReport:
    """Syntax tier, then the service's own test command (or scoped discovery
    when none is configured)."""
    tiers = [await phase_syntax(target)]
    if not tiers[0].ok:
        tiers.append(TierResult("regression", False, "skipped: syntax failed"))
        return VerifyReport(ok=False, tiers=tiers)
    if (test_command or "").strip():
        tiers.append(await run_custom_tests(cwd=cwd, command=test_command))
    else:
        tiers.append(await phase_regression(target))
    return VerifyReport(ok=all(t.ok for t in tiers), tiers=tiers)
