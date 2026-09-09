# AEROOPS — Full Blueprint (idea → architecture → deployment)

## 1. Core idea (one paragraph)
AeroOps is a self-healing operations console: it watches software services,
and when one fails it automatically detects, captures evidence, diagnoses
(rules first, AI second), decides safely (policy gate), fixes what is safely
fixable (restart, install missing dependency, clear temp), verifies recovery
with repeat health checks, records the whole story, and emails the operator.
Humans handle code-logic bugs with precise forensics; machines handle everything
operational. Goal: cut manual troubleshooting and recovery time to near zero.

## 2. The loop (never bypassed)
MONITOR → DETECT → CAPTURE → DIAGNOSE → DECIDE → REMEDIATE → RESTART →
VERIFY → RECOVER → RECORD → NOTIFY. Every step audited. AI recommends, the
policy engine decides, only allowlisted actions execute.

## 3. Architecture (as built)
```
React+TS console (:5174) ──REST+SSE──▶ FastAPI (:8000)
  Dashboard Services Incidents Logs Diagnostics Remediation Metrics Alerts Reports Settings
                                            ├─ Monitor Engine (asyncio 1s tick, per-service intervals)
                                            ├─ Health (process psutil / HTTP httpx / content-text check)
                                            ├─ Incidents (strict state machine + re-queue, no strands)
                                            ├─ Logs (bounded tails, linked to incidents)
                                            ├─ Diagnosis (stack parser → rules → OpenAI→Ollama→rules)
                                            ├─ Policy (allowlist; AI never executes)
                                            ├─ Remediation (restart, install_dependency, clear_temp,
                                            │   rollback_config, retry_health_check) + chained restart
                                            ├─ Restart Manager (subprocess registry, cooldowns, budgets,
                                            │   N-consecutive verification with startup grace)
                                            ├─ Notifications (dashboard+log always; Gmail SMTP; webhook)
                                            ├─ Audit (every lifecycle event with actor+result)
                                            ├─ Metrics (throttled writes, 7-day retention, aggregates)
                                            └─ SQLAlchemy → SQLite (Alembic migrations) → Postgres later
```
Auth: JWT + roles (admin/operator/viewer), PBKDF2 passwords, open viewer
signup, email-code password reset, SSE via ?token=.

## 4. Data model (10 tables)
services (desired-state enabled flag, expected_content, policies) →
incidents (fingerprint, attempts, verified, duration) → incident_events,
diagnoses (source+model), remediation_actions, service_metrics, logs,
notifications, audit_logs, users, password_resets.

## 5. What "done" looks like (acceptance, all proven live)
kill pid → incident <15s → forensics names exception+file:line → fix runs →
N× healthy → RESOLVED with duration → email received. Repeated: 7–11s
recoveries, dependency auto-install proven (wcwidth), blank-page detection
proven, stop-holds + start-resumes proven.

## 6. Deployment path (local → prod)
- NOW: local processes (resume-aeroops.ps1), SQLite, Ollama local, Gmail SMTP.
- NEXT: `docker compose up --build` (files ready, daemon untested on this box).
- PROD: VPS (Ubuntu) + Docker + Caddy/Nginx HTTPS + free domain/DDNS +
  `DATABASE_URL=postgresql://…` (Alembic already manages schema) +
  `JWT_SECRET`, SMTP, `OPENAI_API_KEY` via env + UptimeRobot watching
  `/api/health` + nightly `aeroops.db`/pg_dump copy to Desktop backup.
- LATER: Postgres, Redis fan-out, remote agents, Prometheus /metrics,
  Slack adapter, public status page, SLOs, mobile push, multi-tenant.

## 7. Open items / risks
- OpenAI $0 credit (fallback covers; top up anytime, zero config change).
- Docker daemon off on this machine (compose validated, images unbuilt).
- Demo orphans on hard backend kill (re-detected on boot by design).
- Secrets live in backend/.env + chat history (rotate when convenient).
- checking-1 service has a broken start command (owner fix in Services page).

## 8. Build order actually followed
foundation → DB → services → monitor → health → incidents → logs → restart →
verify → rules → AI → policy → remediation → notify → API → SSE → frontend →
details → logs/diag/remediation pages → failure simulation → tests → docker →
docs → security → debugger → content checks → auto-heal → auth → light theme →
telemetry → code-fix → **Phase 2: git worktrees, dual-tier harness, reflexion,
delivery gates (AUTO_MERGE/DRAFT_PR + Approve & Deploy)**.
