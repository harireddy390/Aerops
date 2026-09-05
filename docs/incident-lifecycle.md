# AeroOps incident lifecycle

`OPEN → INVESTIGATING → DIAGNOSED → REMEDIATING → RECOVERING → RESOLVED`
(side states: `ACKNOWLEDGED`, `FAILED`)

| Step | Engine | Evidence |
|---|---|---|
| Detect | monitor (2 consecutive failed probes) | service status → CRASHED/UNHEALTHY |
| Capture | log collector | `logs` rows + LOGS_CAPTURED event |
| Incident | incident engine | INCIDENT_CREATED + audit |
| Diagnose | rules (sync) then AI (background) | DIAGNOSIS_COMPLETED + `diagnoses` rows |
| Decide | policy engine | REMEDIATION_DECISION event (allowed/denied + reason) |
| Remediate/Restart | remediation + restart manager | REMEDIATION_EXECUTED + audit, cooldown + attempt budget |
| Verify | restart manager | N consecutive healthy checks inside a budget |
| Recover | monitor | status RECOVERED + RECOVERY_VERIFIED audit |
| Record | incident engine | RESOLVED + duration_sec |
| Notify | notification engine | dashboard row (+ webhook best-effort) |

Restart budget: `max_restart_attempts` (default 3) then incident FAILED, no infinite loops.
Hard stops: non-terminal incidents/statuses are re-queued to OPEN/UNKNOWN on boot.
