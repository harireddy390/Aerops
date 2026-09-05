const path = require('path');
const fs = require('fs');
const { DatabaseSync } = require('node:sqlite');

function dbPath() {
  let cfg = {};
  try { cfg = require('../config.json'); } catch {}
  return path.join(__dirname, '..', cfg.dbFile || 'aeroops.db');
}

let db = null;

function init() {
  if (db) return db;
  db = new DatabaseSync(dbPath());
  db.exec(`
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS crashes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      time TEXT NOT NULL,
      code INTEGER,
      tail TEXT,
      cause TEXT,
      fix TEXT,
      ai TEXT,
      model TEXT,
      source TEXT
    );
  `);
  const row = db.prepare("SELECT value FROM meta WHERE key='startTime'").get();
  if (!row) db.prepare("INSERT INTO meta(key,value) VALUES('startTime',?)").run(new Date().toISOString());
  if (!db.prepare("SELECT value FROM meta WHERE key='restarts'").get()) {
    db.prepare("INSERT INTO meta(key,value) VALUES('restarts','0')").run();
  }
  migrateLegacy();
  return db;
}

function migrateLegacy() {
  try {
    const count = db.prepare('SELECT COUNT(*) c FROM crashes').get().c;
    if (count > 0) return;
    const sj = path.join(__dirname, '..', 'state.json');
    if (!fs.existsSync(sj)) return;
    const s = JSON.parse(fs.readFileSync(sj, 'utf8'));
    if (s.restarts) db.prepare("UPDATE meta SET value=? WHERE key='restarts'").run(String(s.restarts));
    for (const c of (s.crashes || []).slice(-50)) {
      db.prepare('INSERT INTO crashes(time,code,tail,cause,fix,ai,model,source) VALUES(?,?,?,?,?,?,?,?)').run(
        c.time || new Date().toISOString(), c.code ?? null, (c.tail || '').slice(0, 4000),
        (c.diagnosis && c.diagnosis.cause) || null, (c.diagnosis && c.diagnosis.fix) || null,
        (c.diagnosis && c.diagnosis.ai) || null, (c.diagnosis && c.diagnosis.model) || null,
        (c.diagnosis && c.diagnosis.source) || null
      );
    }
    console.log(`[db] migrated ${s.crashes ? s.crashes.length : 0} legacy crashes from state.json`);
  } catch (e) { console.log('[db] migrate skip:', e.message); }
}

function recordCrash({ time, code, tail, diagnosis }) {
  init();
  db.prepare('INSERT INTO crashes(time,code,tail,cause,fix,ai,model,source) VALUES(?,?,?,?,?,?,?,?)').run(
    time, code ?? null, (tail || '').slice(0, 4000),
    (diagnosis && diagnosis.cause) || null, (diagnosis && diagnosis.fix) || null,
    (diagnosis && diagnosis.ai) || null, (diagnosis && diagnosis.model) || null,
    (diagnosis && diagnosis.source) || null
  );
  bumpRestarts();
}

function bumpRestarts() {
  init();
  const cur = Number(db.prepare("SELECT value FROM meta WHERE key='restarts'").get()?.value || 0) + 1;
  db.prepare("UPDATE meta SET value=? WHERE key='restarts'").run(String(cur));
  return cur;
}

function getRestarts() {
  init();
  return Number(db.prepare("SELECT value FROM meta WHERE key='restarts'").get()?.value || 0);
}

function getCrashes(limit = 10) {
  init();
  return db.prepare('SELECT * FROM crashes ORDER BY id DESC LIMIT ?').all(limit);
}

module.exports = { init, recordCrash, bumpRestarts, getRestarts, getCrashes };
