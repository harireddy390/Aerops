"""Health engine: derives service status from probe results. Event-driven only."""
import httpx

from app.db.models import Service
from app.monitoring.monitors import http_probe, process_alive


async def check(service: Service) -> dict:
    """Run one health evaluation. Returns snapshot dict; caller persists status changes."""
    if service.health_check_type == "http" and service.health_check_url:
        ok, ms, detail = await http_probe(service.health_check_url, service.timeout_sec or 5)
        if ok and service.expected_content:
            found = await _contains(service.health_check_url, service.expected_content,
                                    service.timeout_sec or 5)
            if not found:
                return {"ok": False, "status": "UNHEALTHY", "response_ms": ms,
                        "detail": f"HTTP 200 but page is missing expected text "
                                  f"'{service.expected_content[:80]}' (blank/wrong content?)"}
            detail += " + content ok"
        status = "HEALTHY" if ok else "UNHEALTHY"
        return {"ok": ok, "status": status, "response_ms": ms, "detail": detail}
    alive = process_alive(service.pid)
    return {"ok": alive, "status": "HEALTHY" if alive else "CRASHED",
            "response_ms": None, "detail": "process running" if alive else "process not running"}


async def _contains(url: str, needle: str, timeout: int) -> bool:
    """Bounded body fetch for content checks. Never raises.

    Compares against rendered BODY text only: <head> (titles/meta), scripts
    and styles are stripped, so a blank client-rendered page with a healthy
    <title> still fails the check instead of hiding behind metadata.
    """
    import re

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url) as r:
                if r.status_code >= 500:
                    return False
                chunks: list[bytes] = []
                size = 0
                async for chunk in r.aiter_bytes(65536):
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > 200_000:
                        break
                html = b"".join(chunks).decode("utf-8", "ignore")
    except Exception:
        return False
    body = re.sub(r"<head.*?</head>", " ", html, flags=re.S | re.I)
    body = re.sub(r"<(script|style).*?</\1>", " ", body, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", " ", text)
    return needle.lower() in text.lower()
