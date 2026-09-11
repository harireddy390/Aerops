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

## Service registration fields (code-remediation)
- `repo_path_or_url` — local path or git URL of the service repo (optional).
- `git_token` — write-only GitHub token, Fernet-encrypted at rest (`git_token_enc`,
  `fernet:` prefix; plaintext refused). Decrypted only at push time, sent as a
  per-command `http.extraHeader`, never in URLs or logs. Never returned by the API.
- `target_branch` — deploy branch (default `main`).
- `workspace_frontend` / `workspace_backend` — subpaths within the repo (defaults
  `./frontend` / `./backend`).
- `test_command` — service's own test command, e.g. `pytest -q`, `npm test`
  (plain command + args only; `; & | \` $ > <` and parens rejected).
- `remediation_policy` — delivery mode: `AUTO_MERGE` (merge + push + rebuild hook +
  restart + verify), `DRAFT_PR` (push if a remote exists, else hold branch for
  1-click approve), `MANUAL_APPROVAL` (hold branch, no push). Legacy `policy_mode`
  (`AUTO_MERGE` / `DRAFT_PR`) still accepted as fallback.
- Live web apps: `published_url` (e.g. `https://my-app.lovable.app`), `client_api_key`
  (public beacon key, auto-minted at registration, rotatable via
  `POST /api/services/{id}/rotate-key`), `deploy_webhook_url` (Vercel/Netlify/Render
  rebuild hook fired after a merged fix). Keyless services keep working with the
  public service identifier alone. Migration: `d3f1a2b4c5e6_client_web_apps.py`.
- Migration (repos): `02bd6c816f98_service_repo_tracking.py`.

## Multi-file remediation schema (v2)
- Context: `collect_context()` ships the primary crash window (±20 lines) plus
  slices of up to 3 imported helpers (definition ±15 lines), max 4 files / 6000
  chars (`app/diagnosis/code_context.py`). Rendered with `PRIMARY CRASH FILE` /
  `RELATED FILE` tags, line-number prefixes stripped before the model sees them.
- Prompt: `build_v2_prompt()` sends `[SERVICE] [INCIDENT_ID] [RUNTIME_ERROR]
  [CRASH_LOCUS] [STACK_TRACE] [RELEVANT_CODE_SLICES] [ENVIRONMENT & HARNESS]`.
- Model reply is pure delimited text (no JSON):
  `<<<DIAGNOSIS>>>` (Root Cause / Upstream Origin / Crash Site / Remediation
  Strategy), `<<<PATCHES>>>` (one unified diff per file, `git apply`-clean),
  `<<<REGRESSION_TEST>>>` (File / Language / ` ```test ` body). Parsed by
  `parse_multifile()` into `MultiProposal` (max 5 patches).
- Apply: `apply_diffs()` applies each file section through the 4-pass gate
  (exact → renumbered → whitespace-tolerant → exact-content for CRLF), max 5
  files; first failure aborts and the fix branch is abandoned. Path escapes
  (`..`, absolute) rejected.
- Verify: syntax tier + service `test_command` (`verify_with_command()`), 60s
  budget, argv-only, stdin DEVNULL. Reflexion retries twice with harness stderr
  fed back in; exhaustion escalates with the branch removed.
- Reference fixture: `demo-services/multifull` (crash in `app.py`, bug in
  `helpers.py`: `cfg["rate"]` → `cfg.get("rate", 0)`). Verified live:
  `backend: python -m pytest tests/ -q` → 60 passed; deterministic e2e
  (context → parse → workspace → multi-diff → harness → commit → abandon) green.

## Live web apps (published SPAs)
- Embed one snippet (Service Detail → **Embed Telemetry**, 1-click copy):
  `<script src="http://localhost:8000/sdk/aeroops.js" data-service-id="..." data-api-key="..."></script>`
  (or `AeroOps.init({ serviceId, endpoint: '…/api/telemetry/client', apiKey, release })`).
  Zero dependencies; captures `onerror` + `onunhandledrejection` + React boundary
  forwards (`AeroOps.report(err, { componentStack })`); per-crash 1/min + 10/min
  global debounce in the snippet, 30/min per service+IP on the server (429 +
  `Retry-After`).
- `POST /api/telemetry/client` (no operator session; key header `X-AeroOps-Key` /
  `X-Api-Key` / Bearer or body `apiKey`, else public identifier) validates
  `serviceId` (id, name, or key), translates Vite/React stacks (`/src/…` preferred,
  hashed `assets/…` basenames kept) into the triage pipeline, then runs the
  autonomous fix: repo sync → map to `workspace_frontend`/`backend` → Phase-3
  multi-file prompt on `aeroops/fix-client-*` → `test_command` (JS defaults to
  `npm run build`) → `AUTO_MERGE` merges, pushes with credentials, fires the
  rebuild hook and notifies, `DRAFT_PR` pushes the branch for Approve & Deploy.
  The legacy `POST /api/telemetry/crash` auto-register flow is unchanged.

## How to run / test / deploy
See `docs/setup.md`. Quick checks: `cd backend; python -m pytest tests/ -q` ·
`cd frontend; npx tsc --noEmit && npm run build` · `docker compose up --build`.
