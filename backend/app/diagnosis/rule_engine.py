"""Rule engine: deterministic diagnosis. Always runs first; works offline."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleResult:
    root_cause: str
    explanation: str
    confidence: float
    recommended_action: str
    risk_level: str
    severity: str


# ordered: first match wins
RULES: list[tuple[str, RuleResult]] = [
    ("address already in use", RuleResult("Port conflict",
        "Process failed to bind: the configured port is already occupied.", 0.92,
        "restart_service", "low", "critical")),
    ("eaddrinuse", RuleResult("Port conflict",
        "EADDRINUSE: another process holds the port.", 0.92, "restart_service", "low", "critical")),
    ("connection refused", RuleResult("Dependency unavailable",
        "Target refused the connection; dependency may be down.", 0.85,
        "restart_dependency", "medium", "critical")),
    ("econnrefused", RuleResult("Dependency unavailable",
        "Connection refused by dependency.", 0.85, "restart_dependency", "medium", "critical")),
    ("out of memory", RuleResult("Memory exhaustion",
        "Process ran out of memory.", 0.9, "restart_service", "medium", "critical")),
    ("javascript heap out of memory", RuleResult("Memory exhaustion",
        "Node heap exhausted.", 0.9, "restart_service", "medium", "critical")),
    ("cannot read properties of undefined", RuleResult("Null dereference",
        "Code dereferenced undefined/null (missing guard or bad payload).", 0.8,
        "restart_service", "low", "critical")),
    ("cannot read property", RuleResult("Null dereference",
        "Code dereferenced undefined/null.", 0.8, "restart_service", "low", "critical")),
    ("modulenotfounderror", RuleResult("Missing Python dependency",
        "Required module is not installed.", 0.9, "retry_health_check", "low", "warning")),
    ("cannot find module", RuleResult("Missing JS dependency",
        "Required node module is not installed.", 0.9, "retry_health_check", "low", "warning")),
    ("permission denied", RuleResult("Insufficient permissions",
        "Process lacks filesystem/OS permissions.", 0.85, "retry_health_check", "high", "warning")),
    ("eacces", RuleResult("Insufficient permissions",
        "Access denied by OS.", 0.85, "retry_health_check", "high", "warning")),
    ("timeout", RuleResult("Health check timeout",
        "Service did not respond in time; overloaded or hung.", 0.7,
        "restart_service", "medium", "warning")),
    ("exit code 1", RuleResult("Process exited with error",
        "Generic failure; inspect captured logs.", 0.6, "restart_service", "low", "critical")),
]


def diagnose(text: str) -> RuleResult:
    lowered = (text or "").lower()
    for needle, result in RULES:
        if needle in lowered:
            return result
    return RuleResult("Unknown failure",
        "No deterministic rule matched; inspect logs or escalate to local AI.", 0.35,
        "restart_service", "medium", "warning")
