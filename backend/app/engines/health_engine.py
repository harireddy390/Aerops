"""Health engine: derives service status from probe results. Event-driven only."""
from app.db.models import Service
from app.monitoring.monitors import http_probe, process_alive


async def check(service: Service) -> dict:
    """Run one health evaluation. Returns snapshot dict; caller persists status changes."""
    if service.health_check_type == "http" and service.health_check_url:
        ok, ms, detail = await http_probe(service.health_check_url, service.timeout_sec or 5)
        status = "HEALTHY" if ok else "UNHEALTHY"
        return {"ok": ok, "status": status, "response_ms": ms, "detail": detail}
    alive = process_alive(service.pid)
    return {"ok": alive, "status": "HEALTHY" if alive else "CRASHED",
            "response_ms": None, "detail": "process running" if alive else "process not running"}
