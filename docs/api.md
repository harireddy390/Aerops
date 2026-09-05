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
