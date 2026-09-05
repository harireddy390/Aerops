# AeroOps in the real world

## What it does for you, concretely
1. **Watches anything with a URL or a start command** — your Node/Python API, a
   client's WordPress, a public API you depend on, a cron script, a home-lab
   server. HTTP checks measure status + response time; process checks watch PID,
   CPU and memory.
2. **Catches failures in seconds** — 2 missed checks → incident with logs
   attached. No more "customer told us before we knew".
3. **Explains the failure** — rules instantly (port busy, dependency down, out
   of memory…), OpenAI/Ollama for the weird ones, all stored with confidence.
4. **Fixes the easy ones itself** — restarts with budgets + cooldowns, verifies
   with repeat health checks, and only then marks RESOLVED.
5. **Pages you by email** — crash, diagnosis, action, result, recovery time.
6. **Proves it all** — timeline + audit log per incident. "What broke, why,
   what ran, did it work" is always one click away.

## Daily uses
- **Your own apps**: register each with its start command; AeroOps babysits them.
- **Dependencies**: register payment/SMS/map APIs as HTTP services; know about
  outages before your users do (restart off, notify on).
- **Client sites**: one console, many sites, branded incident emails.
- **Before deploys**: hit Simulate Failure on staging, confirm recovery < 10s.
- **Weekly review**: Incidents page → repeat root causes → fix the code, not
  the symptoms. Diagnostics page shows your top offenders.

## Rules of thumb
- HTTP checks every 30–60s for internet targets, 5s for local critical ones.
- `max_restart_attempts: 3`, cooldown ≥ 5s. Never "always/∞".
- Viewers for stakeholders, operators for teammates, admin for you (Settings).
- Rotate `JWT_SECRET` + App Passwords every few months; they live in
  `backend/.env` only.
