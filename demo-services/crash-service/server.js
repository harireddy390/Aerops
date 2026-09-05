const express = require('express');
const path = require('path');
const fs = require('fs');

function loadConfig() {
  let cfg = {};
  try { cfg = require('./config.json'); } catch {}
  // .env / env vars win over config.json
  if (process.env.PORT) cfg.port = Number(process.env.PORT);
  if (process.env.ALERT_WEBHOOK) cfg.alertWebhook = process.env.ALERT_WEBHOOK;
  if (process.env.OLLAMA_HOST) cfg.ollamaHost = process.env.OLLAMA_HOST;
  if (process.env.OLLAMA_MODEL) cfg.ollamaModel = process.env.OLLAMA_MODEL;
  if (process.env.AUTO_FIX) cfg.autoFix = process.env.AUTO_FIX === 'true';
  return cfg;
}

const cfg = loadConfig();
const PORT = cfg.port || 3000;
const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));
// Serve real React frontend build at /app when present (npm run build in frontend/)
const frontendDist = path.join(__dirname, 'frontend', 'dist');
if (fs.existsSync(path.join(frontendDist, 'index.html'))) {
  app.use('/app', express.static(frontendDist));
  app.get('/app/*', (req, res) => res.sendFile(path.join(frontendDist, 'index.html')));
}

// Minimal security + request log (no extra deps)
app.use((req, res, next) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  const t = Date.now();
  res.on('finish', () => console.log(`${req.method} ${req.url} -> ${res.statusCode} (${Date.now() - t}ms)`));
  next();
});

const BOOT = Date.now();
const VERSION = (() => { try { return require('./package.json').version; } catch { return '1.0.0'; } })();

app.get('/', (req, res) => {
  res.send('AeroOps Server is running normally. Dashboard: /dashboard');
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', uptime: process.uptime(), timestamp: new Date().toISOString(), version: VERSION });
});

app.get('/api/status', (req, res) => {
  try {
    const db = require('./lib/db');
    const crashes = db.getCrashes(10).map((c) => ({
      id: c.id, time: c.time, code: c.code,
      diagnosis: { cause: c.cause, fix: c.fix, ai: c.ai, model: c.model, source: c.source },
    }));
    return res.json({
      status: 'ok',
      version: VERSION,
      uptimeSec: Math.floor((Date.now() - BOOT) / 1000),
      processUptimeSec: Math.floor(process.uptime()),
      time: new Date().toISOString(),
      restarts: db.getRestarts(),
      autoFix: !!cfg.autoFix,
      model: cfg.ollamaModel,
      crashes,
      store: 'sqlite',
    });
  } catch {}
  let state = null;
  try { state = JSON.parse(fs.readFileSync(path.join(__dirname, cfg.stateFile || 'state.json'), 'utf8')); } catch { state = { restarts: 0, crashes: [] }; }
  res.json({
    status: 'ok',
    version: VERSION,
    uptimeSec: Math.floor((Date.now() - BOOT) / 1000),
    processUptimeSec: Math.floor(process.uptime()),
    time: new Date().toISOString(),
    restarts: state.restarts || 0,
    autoFix: !!cfg.autoFix,
    model: cfg.ollamaModel,
    crashes: (state.crashes || []).slice(-10),
  });
});

app.get('/api/logs', (req, res) => {
  try {
    const lines = fs.readFileSync(path.join(__dirname, cfg.logFile || 'monitor.log'), 'utf8').split('\n').slice(-80);
    res.json({ lines });
  } catch { res.json({ lines: [] }); }
});

app.post('/api/diagnose', async (req, res) => {
  try {
    const { diagnose } = require('./lib/diagnose');
    const text = (req.body && req.body.text) || 'user.profile.name TypeError: Cannot read properties of undefined (reading \'profile\')';
    res.json(await diagnose(text));
  } catch (e) { res.status(500).json({ error: String(e && e.message || e) }); }
});

app.post('/api/fix', async (req, res) => {
  try {
    const { autoFix, syntaxCheck } = require('./lib/fix');
    const file = path.join(__dirname, 'server.js');
    const result = autoFix(file);
    if (!result.fixed) return res.json(result);
    const ok = await syntaxCheck(file);
    if (!ok) return res.status(500).json({ fixed: false, detail: 'Patch applied but syntax check failed — restore backup.' });
    res.json({ ...result, syntax: 'ok' });
  } catch (e) { res.status(500).json({ fixed: false, detail: String(e && e.message || e) }); }
});

// Intentional crash route to test our monitor and local AI
app.get('/crash', (req, res) => {
  console.log('Crash endpoint triggered! Simulating fatal application failure...');
  setTimeout(() => {
    let user = undefined;
    console.log(user.profile.name);
  }, 100);
  res.send('Triggering fatal crash in 100ms...');
});

app.get('/dashboard', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'dashboard.html'));
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({ error: 'Not found', hint: 'Try /, /health, /dashboard, /api/status' });
});

// Global error handlers — log, don't silently die (except /crash test which is async fatal)
process.on('uncaughtException', (err) => {
  console.error('[AeroOps Server] uncaughtException:', err && err.stack || err);
  process.exit(1); // let monitor.js restart us
});

process.on('unhandledRejection', (reason) => {
  console.error('[AeroOps Server] unhandledRejection:', reason);
  process.exit(1);
});

if (require.main === module) {
  const srv = app.listen(PORT, () => {
    console.log(`AeroOps v${VERSION} live on http://localhost:${PORT} (dashboard: /dashboard)`);
  });
  const shut = () => { console.log('Shutting down...'); srv.close(() => process.exit(0)); setTimeout(() => process.exit(0), 3000); };
  process.on('SIGTERM', shut);
  process.on('SIGINT', shut);
}
module.exports = app;
