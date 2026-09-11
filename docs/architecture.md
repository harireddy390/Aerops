# AeroOps architecture

```
React TS console (:5173) ──REST + SSE──▶ FastAPI (:8000)
                                            ├─ Monitor Engine (asyncio task, 1s tick)
                                            │    ├─ health_engine (process psutil / http httpx)
                                            │    ├─ metrics_engine (throttled writes, 7d retention)
                                            │    └─ on failure → incident pipeline
                                            ├─ Incident Engine (strict state machine, transitions only)
                                            ├─ Log Collector (bounded tails → logs table)
                                            ├─ Diagnosis Engine (rules sync → AI background task)
                                            │    ├─ rule_engine (deterministic, offline-safe)
                                            │    └─ ai_diagnoser (Ollama, structured JSON, never fatal)
                                            ├─ Safety/Policy Engine (allowlist gate; AI only recommends)
                                            ├─ Remediation Engine (restart_service, restart_dependency,
                                            │    clear_temp, rollback_config, retry_health_check)
                                            ├─ Restart Manager (subprocess registry, no shell=True,
                                            │    cooldown, max attempts, N-consecutive verify)
                                            ├─ Notification Engine (dashboard+log always; webhook best-effort)
                                            ├─ Audit Engine (every lifecycle event)
                                            └─ SQLAlchemy → SQLite (DATABASE_URL swap → Postgres)
```

Key invariants:
- Status changes only from monitor events or audited operator actions.
- AI output is data; the policy engine decides; only allowlisted actions execute.
- Slow AI never blocks restart: rules decide fast, AI enriches async.
- Every engine failure is isolated per service; AeroOps never crashes with a demo.

## Code remediation (multi-file, Phase 2–3)
Crash report → isolated fix branch (`git_workspace.open_workspace`, dirty-tree
refusal) → `collect_context` (primary ±20 lines + ≤3 imported helpers ±15 lines,
≤4 files / 6000 chars) → `propose_multifile` (v2 delimited contract:
`<<<DIAGNOSIS>>>` / `<<<PATCHES>>>` unified diffs / `<<<REGRESSION_TEST>>>`) →
`apply_diffs` (per-file 4-pass gate, ≤5 files, traversal-proof) → shipped test
via `materialize_at` (never overwrites) → `verify_with_command` (syntax +
`test_command`, argv-only, 60s) → reflexion (≤2 retries with stderr feedback) →
delivery gate (`AUTO_MERGE` merge + stop-then-start + verify, `DRAFT_PR` push or
hold, `MANUAL_APPROVAL` hold). Any gate failure abandons the branch and
escalates; the running process never sees an unverified tree.
