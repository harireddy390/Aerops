"""Safety/policy engine. AI RECOMMENDS; this module DECIDES. Allowlist only."""
from __future__ import annotations

from dataclasses import dataclass

SAFE_ACTIONS = {
    "restart_service": "low",
    "restart_dependency": "medium",
    "install_dependency": "medium",
    "apply_code_patch": "medium",
    "clear_temp": "medium",
    "rollback_config": "medium",
    "retry_health_check": "low",
}

UNSAFE_PATTERNS = ("shell", "exec", "rm ", "del ", "registry", "firewall", "download", "curl ", "wget ")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def evaluate(action_type: str, *, auto_remediation: bool, risk_level: str = "low") -> Decision:
    """Gate every remediation. Unknown or AI-freeform actions are denied by default."""
    if action_type not in SAFE_ACTIONS:
        return Decision(False, f"'{action_type}' is not in the allowlisted safe actions")
    lowered = action_type.lower()
    if any(p in lowered for p in UNSAFE_PATTERNS):
        return Decision(False, "action matches an unsafe pattern")
    if not auto_remediation:
        return Decision(False, "auto-remediation is disabled for this service")
    if risk_level == "high" and action_type != "restart_service":
        return Decision(False, "high-risk actions need operator approval")
    return Decision(True, "allowlisted safe action within policy")
