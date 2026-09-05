const fs = require('fs');
const path = require('path');

function paths() {
  const cfg = require('../config.json');
  return {
    state: path.join(__dirname, '..', cfg.stateFile || 'state.json'),
    crashes: path.join(__dirname, '..', cfg.crashLogFile || 'crashes.jsonl'),
  };
}

function loadState() {
  const { state } = paths();
  try {
    return JSON.parse(fs.readFileSync(state, 'utf8'));
  } catch {
    return { restarts: 0, crashes: [], startTime: new Date().toISOString() };
  }
}

function saveState(s) {
  const { state } = paths();
  fs.writeFileSync(state, JSON.stringify(s, null, 2));
}

function recordCrash(entry) {
  const { crashes } = paths();
  const s = loadState();
  s.crashes.push(entry);
  if (s.crashes.length > 50) s.crashes = s.crashes.slice(-50);
  saveState(s);
  try {
    fs.appendFileSync(crashes, JSON.stringify(entry) + '\n');
  } catch {}
  return s;
}

function bumpRestart() {
  const s = loadState();
  s.restarts = (s.restarts || 0) + 1;
  saveState(s);
  return s;
}

module.exports = { loadState, saveState, recordCrash, bumpRestart };
