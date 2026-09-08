# AeroOps AI setup — makes sure Ollama + model + opencode are ready.
# Usage:  powershell -ExecutionPolicy Bypass -File "C:\AeroOps-Project\scripts\setup-ai.ps1"
$model = 'qwen2.5-coder:7b'
echo '== AeroOps AI setup =='

echo '[1/4] ollama installed?'
try { ollama --version | Select-Object -First 1 }
catch { echo '  MISSING — install from https://ollama.com/download and rerun'; exit 1 }

echo '[2/4] ollama serve running?'
$up = $false
try { Invoke-WebRequest http://localhost:11434/api/tags -UseBasicParsing -TimeoutSec 5 | Out-Null; $up = $true } catch {}
if (-not $up) {
  echo '  starting ollama serve...'
  Start-Process ollama -ArgumentList 'serve' -WindowStyle Hidden
  for ($i = 0; $i -lt 15 -and -not $up; $i++) {
    Start-Sleep -Seconds 2
    try { Invoke-WebRequest http://localhost:11434/api/tags -UseBasicParsing -TimeoutSec 5 | Out-Null; $up = $true } catch {}
  }
}
if ($up) { echo '  serve OK :11434' } else { echo '  serve NOT up — open Ollama app manually once'; exit 1 }

echo "[3/4] model $model present?"
$has = (ollama list 2>$null | Select-String ([regex]::Escape($model)) | Measure-Object).Count -gt 0
if (-not $has) { echo '  pulling (one time, ~4.7GB)...'; ollama pull $model } else { echo '  model OK' }

echo '[4/4] opencode ready?'
try { opencode --version | Select-Object -First 1 }
catch { echo '  MISSING — npm install -g opencode, then rerun'; exit 1 }

echo ''
echo 'AI stack ready. Backend .env already points at it (OLLAMA_BASE_URL + OLLAMA_MODEL).'
echo 'In VS Code: Terminal -> `cd C:\AeroOps-Project; opencode` -> `Read PROJECT-BRIEF.md, then continue.`'
