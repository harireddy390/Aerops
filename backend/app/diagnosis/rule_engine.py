"""Rule engine: deterministic diagnosis. Always runs first; works offline."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.diagnosis.stackparse import CrashEvidence


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
        "Required module is not installed.", 0.9, "install_dependency", "low", "warning")),
    ("cannot find module", RuleResult("Missing JS dependency",
        "Required node module is not installed.", 0.9, "install_dependency", "low", "warning")),
    ("permission denied", RuleResult("Insufficient permissions",
        "Process lacks filesystem/OS permissions.", 0.85, "retry_health_check", "high", "warning")),
    ("eacces", RuleResult("Insufficient permissions",
        "Access denied by OS.", 0.85, "retry_health_check", "high", "warning")),
    ("timeout", RuleResult("Health check timeout",
        "Service did not respond in time; overloaded or hung.", 0.7,
        "restart_service", "medium", "warning")),
    ("missing expected text", RuleResult("Content check failed",
        "Server answers but the page lacks expected content — blank render, "
        "broken deploy, or wrong route. Needs a human: verify the deploy.", 0.8,
        "retry_health_check", "medium", "warning")),
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


def extract_package(text: str) -> str:
    """Pull the missing module name out of ModuleNotFound/Cannot-find errors."""
    m = re.search(r"no module named ['\"]([\w.\-]+)['\"]", text or "", re.I)
    if m:
        return m.group(1).split(".")[0]
    m = re.search(r"cannot find module ['\"]([^'\"]+)['\"]", text or "", re.I)
    if m:
        return m.group(1)
    return ""


def diagnose_detailed(text: str, ev: CrashEvidence) -> tuple[RuleResult, str]:
    """Rules sharpened with stack evidence: names the module, port, property and
    exact crash site. Returns (result, evidence_line)."""
    base = diagnose(text)
    loc = f" at {ev.location}" if ev.location else ""
    lowered = (text or "").lower()

    m = re.search(r"no module named ['\"]([\w.\-]+)['\"]", text, re.I)
    if m:
        return (RuleResult("Missing Python dependency",
            f"Import of '{m.group(1)}' failed{loc}; installing it into the service env.", 0.95,
            "install_dependency", "low", "warning"),
            f"missing module: {m.group(1)}")
    m = re.search(r"cannot find module ['\"]([^'\"]+)['\"]", text, re.I)
    if m:
        return (RuleResult("Missing JS dependency",
            f"Require of '{m.group(1)}' failed{loc}; installing it.", 0.95,
            "install_dependency", "low", "warning"),
            f"missing module: {m.group(1)}")
    m = re.search(r"(?:EADDRINUSE|address already in use)[^\d]*:?(\d{2,5})?", lowered)
    if "eaddrinuse" in lowered or "address already in use" in lowered:
        port = f" port {m.group(1)}" if m and m.group(1) else ""
        return (RuleResult("Port conflict",
            f"Bind failed{port}{loc}; another process holds it.", 0.94,
            "restart_service", "low", "critical"),
            f"port conflict{port}")
    m = re.search(r"reading '([\w$]+)'", text)
    if "cannot read propert" in lowered:
        prop = f" property '{m.group(1)}'" if m else ""
        return (RuleResult("Null dereference",
            f"Code read{prop} of undefined/null{loc}; guard the value.", 0.88,
            "restart_service", "low", "critical"),
            f"null dereference{prop}")
    if ev.exc_type and ev.exc_type not in ("Unknown failure", ""):
        return (RuleResult(base.root_cause,
            f"{base.explanation} Evidence: {ev.exc_type}{loc}.".strip(), base.confidence,
            base.recommended_action, base.risk_level, base.severity),
            f"{ev.exc_type}{loc}")
    return base, "no specific evidence"
