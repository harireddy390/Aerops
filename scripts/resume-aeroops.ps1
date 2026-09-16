# AeroOps morning starter — run this any time to bring the whole project up.
# Usage:  powershell -ExecutionPolicy Bypass -File "C:\AeroOps-Project\scripts\resume-aeroops.ps1"
$proj = if ($PSScriptRoot) { (Split-Path -Parent $PSScriptRoot) } else { 'C:\AeroOps-Project' }
$api = 'http://localhost:8000'

function Free-Port($port) {
  foreach ($c in (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) {
    try {
      $p = Get-Process -Id $c.OwningProcess -ErrorAction Stop
      echo "  freeing :$port (was $($p.ProcessName) pid=$($p.Id))"
      Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    } catch {}
  }
}

echo '== AeroOps resume =='
echo '[1/5] freeing :8000 :5174 :5175 (your :5173 project is never touched)'
Free-Port 8000; Free-Port 5174; Free-Port 5175
Start-Sleep -Seconds 2

echo '[2/5] starting backend :8000'
Start-Process powershell -ArgumentList '-NoExit','-Command', "cd '$proj\backend'; python -m uvicorn app.main:app --port 8000"

echo '[3/5] starting console (takes the first free port from 5174)'
Start-Process powershell -ArgumentList '-NoExit','-Command', "cd '$proj\frontend'; npm run dev"

echo '[4/5] waiting for API...'
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
  try { (Invoke-WebRequest "$api/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode | Out-Null; $ok = $true; break }
  catch { Start-Sleep -Seconds 2 }
}
if ($ok) { echo '  backend OK' } else { echo '  backend NOT up — check the backend window for errors' }

echo '[5/5] opening VS Code'
try { Start-Process code -ArgumentList $proj -ErrorAction Stop }
catch { echo '  (VS Code CLI not on PATH — open it manually at C:\AeroOps-Project)' }

$msg = 'Continue the AeroOps project in C:\AeroOps-Project — FastAPI backend :8000, React console :5174+, SQLite. Everything was working.'
Set-Clipboard $msg
echo ''
echo 'All up. This resume note is copied — paste it to me in a new chat:'
echo "  $msg"
