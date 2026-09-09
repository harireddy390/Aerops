# AeroOps browser reporter

Report client-side crashes (blank screens, uncaught exceptions, rejected
promises, React render failures) straight into AeroOps incidents.

## Install (2 minutes, any site)

1. Copy `aeroops-reporter.js` into your frontend's public dir.
2. Before `</body>`:
```html
<script src="/aeroops-reporter.js"></script>
<script>
  AeroOpsReporter.init({
    endpoint: 'https://your-aeroops-host/api/telemetry/crash',
    service: 'my-web-app',
    release: '1.4.2' // optional
  });
</script>
```
3. React: wrap the tree (see `AeroErrorBoundary.tsx`):
```tsx
<AeroErrorBoundary><App /></AeroErrorBoundary>
```

## What happens per crash
- Browser dedupes identical crashes to 1/minute; AeroOps dedupes repeats
  server-side into the same open incident.
- AeroOps parses the stack → file:line → fingerprint → rule diagnosis →
  incident + dashboard + email. No auto-restart (browsers can't be restarted
  from here) — a human fixes and deploys.

## Security note
The endpoint accepts unauthenticated reports by design (browsers can't hold
API secrets) but **only ever creates incidents** — it cannot trigger actions.
For production, proxy it through your own backend or front it with a WAF
rate limit; a per-service ingest token is on the roadmap.

## Try it against a synthetic crash (2 minutes)
1. Start AeroOps: `cd backend; python -m uvicorn app.main:app --port 8000`.
2. In any React app:
```tsx
import { initAeroOps, AeroOpsErrorBoundary } from './aeroops-reporter'
initAeroOps({ endpoint: 'http://localhost:8000', service: 'demo-shop' })
// ...then crash on purpose:
function Boom() {
  const user = undefined as unknown as { profile: { name: string } }
  return <h1>{user.profile.name}</h1> // throws on render
}
// <AeroOpsErrorBoundary><Boom /></AeroOpsErrorBoundary>
```
3. Open the crashing page → incident appears in AeroOps with file:line,
   fingerprint and rule diagnosis. If the crashing file lives in a directory
   registered as that service's working directory, the code-fix pipeline
   proposes a guarded patch, verifies it, and applies or rolls back.
4. No React handy? POST the payload yourself:
```powershell
$body = @{service_id='demo-shop'; error_name='TypeError';
  message="Cannot read properties of undefined (reading 'name')";
  file_path='widget.js'; line_number=2; column_number=20;
  stack_trace="TypeError: x`n    at greet (widget.js:2:20)"} | ConvertTo-Json
Invoke-RestMethod -Method Post http://localhost:8000/api/telemetry/crash `
  -ContentType 'application/json' -Body $body
```
