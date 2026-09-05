const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');

function sendWebhook(url, payload, timeoutMs = 5000) {
  return new Promise((resolve) => {
    try {
      const u = new URL(url);
      const lib = u.protocol === 'https:' ? https : http;
      const body = JSON.stringify(payload);
      const req = lib.request(
        { hostname: u.hostname, port: u.port || (u.protocol === 'https:' ? 443 : 80), path: u.pathname + u.search, method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) }, timeout: timeoutMs },
        (res) => { res.resume(); res.on('end', () => resolve(true)); }
      );
      req.on('error', () => resolve(false));
      req.on('timeout', () => { req.destroy(); resolve(false); });
      req.write(body);
      req.end();
    } catch {
      resolve(false);
    }
  });
}

async function alert(title, description, fields = []) {
  const cfg = require('../config.json');
  const line = `[${new Date().toISOString()}] ALERT: ${title} — ${description}`;
  console.log(line);
  try {
    fs.appendFileSync(path.join(__dirname, '..', cfg.logFile || 'monitor.log'), line + '\n');
  } catch {}

  if (!cfg.alertWebhook) return { logged: true, webhook: false };
  const payload = { content: `**${title}**\n${description}`, embeds: [{ title, description, fields, timestamp: new Date().toISOString() }] };
  const ok = await sendWebhook(cfg.alertWebhook, payload);
  return { logged: true, webhook: ok };
}

module.exports = { alert, sendWebhook };
