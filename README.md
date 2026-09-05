# AeroOps — AI-assisted, self-healing service monitoring

AeroOps watches your services. When one fails it runs the full loop automatically:
**detect → capture → incident → diagnose (rules, then local AI) → policy decision →
safe remediation → restart → verify → recover → record → notify** — all visible live
in the operations console.

## Two things in this repo
- **Platform (new, primary):** Python FastAPI + React TS console. Backend `:8000`, console `:5173`.
- **Legacy Node MVP (v1.2.0, kept working):** `npm start` → `:3000`. Its crashable
  server was reused as `demo-services/crash-service`.

## 60-second demo
1. `cd backend; pip install -r requirements.txt; python -m uvicorn app.main:app --port 8000`
2. `cd frontend; npm install; npm run dev` → open http://localhost:5173
3. Open a service → **Simulate Failure** (or `POST /api/demo/simulate-failure?service_id=1`)
4. Watch: incident opens → rule diagnosis → restart → health checks → **RECOVERED**,
   timeline + AI second opinion + audit trail, no refresh needed (SSE).

## Features
- Multi-service process/HTTP monitoring (psutil + httpx), metrics charts
- Strict incident state machine, log capture (bounded), timeline view
- Rule engine (14 patterns) + optional Ollama AI (structured JSON, background, safe fallback)
- Policy allowlist: AI recommends, engine decides; no arbitrary execution, ever
- Restart budgets + cooldowns, N-consecutive recovery verification, warm-restart re-queue
- Dashboard/services/incidents/logs/diagnostics/remediation/metrics/notifications/audit/settings
- SQLite now (Alembic migrations), Postgres-ready via `DATABASE_URL`
- Docker Compose, structured JSON logs, `/api/system/health`, pytest suite

## Docs
`docs/architecture.md` · `incident-lifecycle.md` · `api.md` · `security.md` · `setup.md`

## How to run / test / deploy
See `docs/setup.md`. Quick checks: `cd backend; python -m pytest tests/ -q` ·
`cd frontend; npx tsc --noEmit && npm run build` · `docker compose up --build`.
