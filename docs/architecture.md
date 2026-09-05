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
