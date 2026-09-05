# Making AeroOps 10x — prioritized roadmap

**Now (biggest wins first)**
1. **Watch 5+ real services**, not demos — value scales with coverage.
2. **Add OpenAI credit** — sharper diagnoses on unknown failures (~$0.0001 each).
3. **Tune policies per service** — intervals, budgets, cooldowns per criticality.
4. **Weekly incident review** — kill repeat root causes in code.

**Next (one weekend each)**
5. **PostgreSQL** — change `DATABASE_URL`; migrations already Alembic-managed.
6. **Slack/Discord adapter** — same pattern as the email adapter (~40 lines).
7. **Public status page** — read-only view backed by `/api/metrics/summary`.
8. **Uptime SLOs** — % healthy per service per 30d from `service_metrics`.
9. **JWT_SECRET rotation + HTTPS** — Caddy/Nginx in front for real deployments.

**Later (architecture already supports)**
10. **Remote agents** — tiny poller on each server reporting to central API.
11. **Prometheus export** — `/metrics` from existing tables.
12. **Docker/K8s checks** — new `health_check_type`, same incident pipeline.
13. **Deployment rollback action** — new allowlisted remediation + validator.
14. **Mobile push** — ntfy/ntfy.sh adapter in the notification engine.
15. **Multi-tenant teams** — scope services/incidents by organization.

Rule: every addition rides the existing loop (detect→diagnose→policy→act→
verify→audit). If a feature bypasses policy or audit, it doesn't ship.
