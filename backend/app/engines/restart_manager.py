"""Restart manager: owns service subprocesses. No shell=True, ever."""
import asyncio
import os
import shlex
import subprocess
import time
from pathlib import Path

import psutil

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("restart")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_processes: dict[int, subprocess.Popen] = {}


def _split(command: str) -> list[str]:
    if any(ch in command for ch in [";", "&", "|", "`", "$", ">", "<", "\n"]):
        raise ValueError("shell metacharacters not allowed")
    return shlex.split(command, posix=os.name != "nt")


def is_running(service_id: int) -> tuple[bool, int | None]:
    proc = _processes.get(service_id)
    if proc and proc.poll() is None:
        return True, proc.pid
    # fall through to psutil check by stored pid
    return False, None


def start(service_id: int, command: str, workdir: str, env: dict) -> int:
    if not command:
        raise ValueError("service has no command configured")
    running, pid = is_running(service_id)
    if running:
        return pid  # idempotent
    target = (PROJECT_ROOT / (workdir or ".")).resolve()
    if PROJECT_ROOT.resolve() not in target.parents and target != PROJECT_ROOT.resolve():
        raise ValueError("working directory escapes project root")
    target.mkdir(parents=True, exist_ok=True)
    merged = {**os.environ, **(env or {})}
    parts = _split(command)
    # let node demos reuse the workspace's node_modules without bundling their own
    node_mods = PROJECT_ROOT / "node_modules"
    if parts[0] == "node" and node_mods.is_dir() and "NODE_PATH" not in merged:
        merged["NODE_PATH"] = str(node_mods)
    log_file = PROJECT_ROOT / f".run-{service_id}.log"
    fh = open(log_file, "ab")
    proc = subprocess.Popen(parts, cwd=str(target), env=merged,
                            stdout=fh, stderr=subprocess.STDOUT)
    _processes[service_id] = proc
    log.info(f"service {service_id} started pid={proc.pid}: {command[:120]}")
    return proc.pid


def stop(service_id: int, timeout: int = 10) -> bool:
    proc = _processes.get(service_id)
    if not proc or proc.poll() is not None:
        return True
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.info(f"service {service_id} stopped")
    return True


def exit_code(service_id: int) -> int | None:
    proc = _processes.get(service_id)
    return proc.poll() if proc else None


def proc_info(pid: int | None) -> dict:
    if not pid:
        return {"cpu": 0.0, "mem_mb": 0.0, "uptime_sec": 0}
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            return {"cpu": round(p.cpu_percent(interval=None), 1),
                    "mem_mb": round(p.memory_info().rss / 1e6, 1),
                    "uptime_sec": int(time.time() - p.create_time())}
    except psutil.NoSuchProcess:
        return {"cpu": 0.0, "mem_mb": 0.0, "uptime_sec": 0}


async def wait_healthy(check_fn, *, attempts: int | None = None,
                       interval: int | None = None, budget_sec: int = 60,
                       startup_grace_sec: int = 3) -> bool:
    """Recovery verification: N CONSECUTIVE passes within a budget.
    Startup grace first (process booting is not failure)."""
    attempts = attempts or settings.recovery_verify_checks
    interval = interval or settings.recovery_verify_interval
    await asyncio.sleep(startup_grace_sec)
    deadline = time.monotonic() + budget_sec
    streak = 0
    while time.monotonic() < deadline:
        try:
            ok = await check_fn()
        except Exception:
            ok = False
        streak = streak + 1 if ok else 0
        if streak >= attempts:
            return True
        await asyncio.sleep(interval)
    return False
