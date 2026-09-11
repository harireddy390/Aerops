# AeroOps API

Services: `GET/POST /api/services`, `GET/PUT/DELETE /api/services/{id}`,
`POST /api/services/{id}/{start,stop,restart}`, `GET .../metrics`, `GET .../logs`.
Incidents: `GET /api/incidents[?status&service_id]`, `GET /api/incidents/{id}`,
`POST .../acknowledge`, `GET .../timeline`, `POST .../remediate {action_type, params}`.
Ops: `GET /api/logs`, `/api/diagnostics`, `/api/remediation`, `/api/notifications`,
`/api/audit`, `/api/metrics/summary`, `POST /api/diagnose {text}`,
`POST /api/demo/simulate-failure?service_id=`, `GET /api/system/health`, `GET /api/health`.
Realtime: `GET /api/events/stream` (SSE: service.status, incident.created,
diagnosis.completed, diagnosis.ai, restart.started, service.recovered, notification, metrics).

All inputs are Pydantic-validated; errors are `{error, detail}` with proper codes
(404 not_found, 409 conflict, 422 validation, 403 policy_denied).

## Service registration (code-remediation fields)
`POST /api/services` accepts the base fields plus:
- `repo_path_or_url` (str, ≤500) — local path or git URL. Optional.
- `git_token` (str, ≤2000, write-only) — stored Fernet-encrypted as
  `git_token_enc` (`fernet:` prefix; empty or non-prefixed values decrypt to
  `""`). Never serialized back. Same field on `PUT`.
- `target_branch` (str, default `main`), `workspace_frontend` (default
  `./frontend`), `workspace_backend` (default `./backend`).
- `test_command` (str, ≤500) — plain command + args only; rejects
  `; & | \` $ > < newline ( )`. Runs shlex-split, never shelled, 60s budget.
- `remediation_policy`: `AUTO_MERGE` | `DRAFT_PR` (default) | `MANUAL_APPROVAL`.
  Legacy `policy_mode` (`AUTO_MERGE` | `DRAFT_PR`) kept as fallback.
- Delivery: `AUTO_MERGE` merges + pushes (credentials via per-command
  `http.extraHeader`) + fires `deploy_webhook_url` + restarts + verifies;
  `DRAFT_PR` pushes when a remote exists (token via per-command
  `http.extraHeader`) and records the PR body, else holds the branch `pending`;
  `MANUAL_APPROVAL` holds the branch with no push.
  Approve: `POST /api/delivery/approve {"incident_id": N}`.
- Live web apps: `published_url` (http(s) URL, ≤500), `client_api_key`
  (auto-minted when empty, ≤64, returned by the API for the embed snippet),
  `deploy_webhook_url` (http(s) URL, ≤500). Rotate: `POST /api/services/{id}/rotate-key`.

## Client telemetry (published web apps)
- SDK: `GET /sdk/aeroops.js` (public, `application/javascript`, 1h cache).
  `AeroOps.init({ serviceId, endpoint, apiKey?, release? })` or zero-config via
  `data-service-id` / `data-api-key` / `data-endpoint` / `data-release`
  attributes; `AeroOps.report(err, { componentStack? })` forwards React
  boundary catches (also via `aeroops:report` events).
- `POST /api/telemetry/client` (public, no operator session): `serviceId`
  (numeric id, name, or the key itself; 422 when missing, 404 when unknown),
  `message` / `error_name`, `stack_trace`, `file_path` / `line_number` /
  `column_number`, `url` / `route`, `userAgent`, `componentStack`, `release`,
  `timestamp`. Auth: `X-AeroOps-Key` / `X-Api-Key` / Bearer header or body
  `apiKey` must match `client_api_key` when the service has one (401
  otherwise); keyless services accept the public identifier. Flood guard:
  30/min per service+IP (429 + `Retry-After`); repeats dedupe into the open
  incident (10-min fingerprint window) like `/crash`.
