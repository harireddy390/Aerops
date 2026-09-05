"""Process + HTTP + resource + log monitors. Small pure helpers used by engines."""
import time

import httpx
import psutil


def process_alive(pid: int | None) -> bool:
    return bool(pid) and psutil.pid_exists(pid)


async def http_probe(url: str, timeout: int) -> tuple[bool, float, str]:
    """Returns (ok, response_ms, detail). Never raises."""
    if not url:
        return False, 0.0, "no url configured"
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
            ms = (time.perf_counter() - start) * 1000
            if r.status_code < 500:
                return True, round(ms, 1), f"HTTP {r.status_code}"
            return False, round(ms, 1), f"HTTP {r.status_code}"
    except Exception as exc:
        ms = (time.perf_counter() - start) * 1000
        return False, round(ms, 1), f"{type(exc).__name__}: {exc}"[:200]


def system_snapshot() -> dict:
    return {"cpu_pct": psutil.cpu_percent(interval=None),
            "mem_pct": psutil.virtual_memory().percent}
