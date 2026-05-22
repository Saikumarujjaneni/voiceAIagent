# Start Redis (optional), backend, voice gateway, and demo UI
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "Starting Redis via docker compose (optional)..."
docker compose up -d redis 2>$null

Write-Host "Backend: http://127.0.0.1:8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; if (-not (Test-Path .venv)) { python -m venv .venv }; .\.venv\Scripts\Activate.ps1; pip install -q -r requirements.txt; Copy-Item .env.example .env -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force -Path data | Out-Null; uvicorn app.main:app --reload --port 8000"

Start-Sleep -Seconds 3

Write-Host "Freeing ports 3000 / 8787 if already in use..."
& "$PSScriptRoot\stop-ports.ps1"

Write-Host "Voice + UI: http://127.0.0.1:3000"
npm run install:all
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; npm run dev"
