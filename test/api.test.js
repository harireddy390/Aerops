const assert = require('node:assert');
const { spawn } = require('node:child_process');

const PORT = process.env.PORT || 3000;
let child;

async function get(p) {
  const r = await fetch(`http://localhost:${PORT}${p}`);
  return { status: r.status, body: await r.text() };
}

async function main() {
  child = spawn('node', ['server.js'], { cwd: __dirname + '/..', stdio: 'ignore' });
  // wait for boot
  for (let i = 0; i < 30; i++) {
    try {
      const r = await fetch(`http://localhost:${PORT}/health`);
      if (r.ok) break;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  let pass = 0;
  const t = async (name, fn) => { await fn(); pass++; console.log(`ok - ${name}`); };

  await t('GET /', async () => {
    const r = await get('/');
    assert.equal(r.status, 200);
    assert.match(r.body, /AeroOps/);
  });
  await t('GET /health', async () => {
    const r = await fetch(`http://localhost:${PORT}/health`).then((x) => x.json());
    assert.equal(r.status, 'ok');
  });
  await t('GET /api/status (sqlite store)', async () => {
    const r = await fetch(`http://localhost:${PORT}/api/status`).then((x) => x.json());
    assert.equal(r.status, 'ok');
    assert.equal(r.store, 'sqlite');
    assert.ok(typeof r.restarts === 'number');
    assert.ok(Array.isArray(r.crashes));
  });
  await t('GET /dashboard', async () => {
    const r = await get('/dashboard');
    assert.equal(r.status, 200);
    assert.match(r.body, /AeroOps/);
  });
  await t('GET /app (react frontend)', async () => {
    const r = await get('/app/');
    assert.equal(r.status, 200);
    assert.match(r.body, /div|html/i);
  });
  await t('lib/db readable', async () => {
    const db = require('../lib/db');
    assert.ok(typeof db.getRestarts() === 'number');
    assert.ok(Array.isArray(db.getCrashes(5)));
  });
  console.log(`\n${pass} tests passed`);
}

main().then(async () => { try { child.kill('SIGTERM'); } catch {} await new Promise((r) => setTimeout(r, 500)); try { child.kill('SIGKILL'); } catch {} process.exit(0); }).catch((e) => { console.error('FAIL:', e); try { child.kill('SIGKILL'); } catch {} process.exit(1); });
