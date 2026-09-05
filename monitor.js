const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

function loadCfg() {
  delete require.cache[require.resolve('./config.json')];
  let c = require('./config.json');
  if (process.env.PORT) c.port = Number(process.env.PORT);
  if (process.env.ALERT_WEBHOOK) c.alertWebhook = process.env.ALERT_WEBHOOK;
  if (process.env.AUTO_FIX) c.autoFix = process.env.AUTO_FIX === 'true';
  return c;
}
let cfg = loadCfg();
const PORT = cfg.port || 3000;
const LOG_FILE = path.join(__dirname, cfg.logFile || 'monitor.log');
const RESTART_DELAY_MS = cfg.restartDelayMs || 2000;
const MAX_RESTARTS = cfg.maxRestarts || 20;

const { alert } = require('./lib/alert');
const { diagnose } = require('./lib/diagnose');
const state = require('./lib/state');

let restarts = 0;
try { restarts = state.loadState().restarts || 0; } catch {}

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  process.stdout.write(`[AeroOps Monitor] ${msg}\n`);
  try { fs.appendFileSync(LOG_FILE, line); } catch {}
}

function healthCheck() {
  return new Promise((resolve) => {
    const req = http.get(`http://localhost:${PORT}/health`, { timeout: 2000 }, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

function startServer() {
  log(`Starting server.js... (restart #${restarts})`);
  const server = spawn('node', ['server.js'], { cwd: __dirname, stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  server.stdout.on('data', (d) => { process.stdout.write(d); output += d; if (output.length > 8000) output = output.slice(-8000); });
  server.stderr.on('data', (d) => { process.stderr.write(d); output += d; if (output.length > 8000) output = output.slice(-8000); });

  server.on('error', (err) => { log(`Failed to spawn server: ${err.message}`); });

  server.on('close', async (code) => {
    cfg = loadCfg(); // pick up config changes without monitor restart
    const RESTART_DELAY_MS = cfg.restartDelayMs || 2000;
    const MAX_RESTARTS = cfg.maxRestarts || 20;
    restarts += 1;
    state.bumpRestart();
    const crashText = output.slice(-3000);
    log(`Server stopped with exit code ${code}.`);
    // AI diagnosis (local ollama, heuristic fallback)
    let diagnosis = null;
    try { diagnosis = await diagnose(crashText || `exit code ${code}`); } catch (e) { diagnosis = { cause: String(e), fix: 'see logs' }; }
    const entry = { time: new Date().toISOString(), code, tail: crashText.slice(-1000), diagnosis };
    state.recordCrash(entry);
    try { require('./lib/db').recordCrash(entry); } catch (e) { log(`DB write failed: ${e.message}`); }
    log(`Diagnosis: ${diagnosis.cause} | Fix: ${diagnosis.fix}${diagnosis.ai ? ' | AI: ' + diagnosis.ai.slice(0, 200) : ''}`);
    // Optional auto-fix (opt-in via config.json autoFix:true)
    if (cfg.autoFix) {
      try {
        const { autoFix, syntaxCheck } = require('./lib/fix');
        const r = autoFix(path.join(__dirname, 'server.js'));
        if (r.fixed && (await syntaxCheck(path.join(__dirname, 'server.js')))) {
          log(`Auto-fix applied: ${r.detail} (backup ${r.backup})`);
        } else {
          log(`Auto-fix skipped: ${r.detail}`);
        }
      } catch (e) { log(`Auto-fix error: ${e.message}`); }
    }
    await alert('AeroOps crash detected', `Exit ${code} on :${PORT}. ${diagnosis.cause}`, [
      { name: 'Fix', value: String(diagnosis.fix).slice(0, 1000) },
      ...(diagnosis.ai ? [{ name: 'AI', value: String(diagnosis.ai).slice(0, 1000) }] : []),
    ]);
    if (restarts > MAX_RESTARTS) {
      log(`Max restarts (${MAX_RESTARTS}) exceeded. Giving up.`);
      await alert('AeroOps giving up', `Max restarts exceeded.`);
      process.exit(1);
    }
    log(`Restarting in ${RESTART_DELAY_MS / 1000} seconds...`);
    setTimeout(startServer, RESTART_DELAY_MS);
  });
}

process.on('SIGINT', () => { log('Monitor shutting down.'); process.exit(0); });

log('AeroOps Monitor online (alerts + local-AI diagnosis + dashboard).');
startServer();

setInterval(async () => {
  const ok = await healthCheck();
  if (!ok) log('Health check FAILED (server not responding on /health).');
}, cfg.healthCheckIntervalMs || 15000);
