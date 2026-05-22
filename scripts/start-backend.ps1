$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"

if (-not (Test-Path .venv)) {
    python -m venv .venv
}
.\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created backend/.env — add your OPENAI_API_KEY for full AI (demo mode works without it)."
}

New-Item -ItemType Directory -Force -Path data | Out-Null
Write-Host "Starting backend http://127.0.0.1:8000"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
