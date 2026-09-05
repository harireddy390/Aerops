const http = require('http');
const https = require('https');
const { execFile } = require('child_process');

function postJson(urlStr, obj, timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr);
    const lib = u.protocol === 'https:' ? https : http;
    const body = JSON.stringify(obj);
    const req = lib.request(
      { hostname: u.hostname, port: u.port, path: u.pathname, method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) }, timeout: timeoutMs },
      (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => { try { resolve(JSON.parse(data)); } catch (e) { reject(e); } });
      }
    );
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(new Error('ollama timeout')); });
    req.write(body);
    req.end();
  });
}

function heuristic(crashText) {
  const t = crashText || '';
  if (t.includes("Cannot read properties of undefined") || t.includes("reading 'profile'") || t.includes('user.profile.name')) {
    return { cause: "Dereferenced undefined `user.profile.name` in /crash async timer.", fix: 'Guard the value: `if (!user?.profile) return;` or wrap timer in try/catch so it does not become uncaughtException.' };
  }
  if (t.includes('EADDRINUSE')) return { cause: 'Port already in use.', fix: 'Kill old node process or change config.json port.' };
  if (t.includes('uncaughtException')) return { cause: 'Uncaught exception crashed process.', fix: 'Add try/catch + validation at throw site; keep process exit(1) so monitor restarts.' };
  return { cause: 'Unknown — see crash log tail.', fix: 'Check crashes.jsonl + monitor.log, add guard + test.' };
}

function ollamaCli(prompt, model, timeoutMs = 60000) {
  return new Promise((resolve) => {
    execFile('ollama', ['run', model, prompt], { timeout: timeoutMs, windowsHide: true }, (err, stdout) => {
      if (err) return resolve(null);
      resolve(String(stdout || '').trim().slice(0, 2000) || null);
    });
  });
}

async function diagnose(crashText) {
  const h = heuristic(crashText);
  let cfg = {};
  try { cfg = require('../config.json'); } catch {}
  const model = cfg.ollamaModel || 'qwen2.5-coder:7b';
  const host = (cfg.ollamaHost || 'http://localhost:11434').replace(/\/$/, '');
  const prompt = `You are a Node.js on-call engineer. Diagnose this crash in 5 lines max: cause + fix.\n\nCRASH:\n${String(crashText).slice(0, 3000)}`;

  // 1) try Ollama HTTP API
  try {
    const r = await postJson(`${host}/api/generate`, { model, prompt, stream: false }, 45000);
    if (r && r.response) return { cause: h.cause, fix: h.fix, ai: String(r.response).slice(0, 2000), model, source: 'ollama-http' };
  } catch {}
  // 2) try ollama CLI
  try {
    const out = await ollamaCli(prompt, model, 45000);
    if (out) return { cause: h.cause, fix: h.fix, ai: out, model, source: 'ollama-cli' };
  } catch {}
  return { ...h, ai: null, model, source: 'heuristic' };
}

module.exports = { diagnose, heuristic };
