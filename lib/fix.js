const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');

function backup(file) {
  const bak = `${file}.bak-${Date.now()}`;
  fs.copyFileSync(file, bak);
  return bak;
}

// Safe auto-fix for the known /crash pattern. Returns {fixed, detail, backup}
function autoFix(serverFile) {
  const src = fs.readFileSync(serverFile, 'utf8');
  // Already guarded?
  if (src.includes('user?.profile')) return { fixed: false, detail: 'Already guarded (user?.profile present).' };
  const vulnerable = 'console.log(user.profile.name)';
  if (!src.includes(vulnerable)) return { fixed: false, detail: 'Pattern not found — manual fix needed.' };
  const bak = backup(serverFile);
  const patched = src.replace(
    'let user = undefined;\n    console.log(user.profile.name);',
    'let user = undefined;\n    if (!user?.profile) { console.log("[AeroOps] guarded undefined user.profile — crash prevented"); return; }\n    console.log(user.profile.name);'
  );
  if (patched === src) return { fixed: false, detail: 'Replace failed.' };
  fs.writeFileSync(serverFile, patched);
  return { fixed: true, detail: 'Guarded user.profile with optional chaining.', backup: bak };
}

function syntaxCheck(file) {
  return new Promise((resolve) => {
    execFile('node', ['--check', file], (err) => resolve(!err));
  });
}

module.exports = { autoFix, syntaxCheck };
