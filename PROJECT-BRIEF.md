# AeroOps — agent briefing (read this first, then continue the user's task)

## What this is
AeroOps: AI-assisted, self-healing service monitoring. Monitor loop:
detect → capture → incident → diagnose (rules, then OpenAI→Ollama) →
policy gate → safe remediate → restart → verify → recover → record → notify.
Dark past is gone: current UI is a LIGHT enterprise theme per reference.

## Layout (C:\AeroOps-Project)
- `backend/` FastAPI :8000 — `app/` (api/routes, core, db, engines×8, diagnosis,
  remediation, monitoring, schemas, utils), `tests/`, `migrations/` (Alembic),
  `requirements.txt`, `.env` (SECRETS — never print, commit, or paste these)
- `frontend/` React+TS+Vite+Tailwind, dev port 5174+ (5173 belongs to user's
  other project — never occupy it), builds to `dist/`
- `demo-services/` (healthy/crash/memory/dependency), `docs/`, `scripts/`
  (`resume-aeroops.ps1` boots everything), `docker-compose.yml`
- Legacy Node MVP (`server.js`, `monitor.js`) still present; platform is primary

## Run / verify (PowerShell)
- Backend: `cd backend; python -m uvicorn app.main:app --port 8000`
- Console: `cd frontend; npm run dev` (uses first free port from 5174)
- Tests: `cd backend; python -m pytest tests/ -q` (must stay green)
- Frontend: `cd frontend; npx tsc --noEmit; npm run build`
- Full reset: `powershell -ExecutionPolicy Bypass -File scripts/resume-aeroops.ps1`

## Standing rules (do not break)
- Backend unchanged unless the task needs it; frontend freely.
- NEVER fake data: every number comes from the API/DB. Empty → "No data available".
- No `shell=True`, no AI-executed commands; remediation only via policy allowlist.
- Auth: JWT + roles (admin/operator/viewer); SSE via `?token=`.
- After changes: run relevant tests + build; fix errors before reporting.
- Never print secrets from `backend/.env`. Never commit `.env`.
- Confirm destructive actions; keep replies short and factual.

## State & roadmap (updated: auth v2 + light theme live)
- Working: monitoring, incidents, rules+OpenAI+Ollama diagnosis, Gmail alerts,
  auth/team, light UI, Docker files (daemon untested), docs in `docs/`.
- Auth: signup (username+gmail+double password) / signin / forgot-code flow;
  open signup ON (viewer-only); users `boss`+`harireddy` are admins.
- UI: light enterprise theme, sidebar Alerts=/notifications Reports=/audit,
  Ctrl+K palette, time filter, login at /login. Console runs :5174+ (5173 is
  the user's other project — never occupy it). Dev server must RESTART on
  tailwind.config change (HMR is not enough).
- Known: OpenAI key valid but $0 credit (auto-fallback covers); test users
  `boss`/`friend` exist in live DB; demo processes orphan on hard backend kill
  (monitor re-detects on boot).
- Next ideas: `docs/roadmap-10x.md` (Slack adapter, Postgres, status page, SLOs).
