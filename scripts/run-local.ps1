$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".venv")) { py -3.12 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:CONTROL_URL = "http://127.0.0.1:8080"
$env:CORS_ORIGINS = "*"
$env:LOCAL_DB = (Join-Path (Get-Location) "minehub.db")
& .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8080
