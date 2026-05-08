$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

# Create venv if missing
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment python not found at .venv\Scripts\python.exe"
}

# Install/update dependencies
& $pythonExe -m pip install -r requirements.txt | Out-Null

# Run data refresh first
$env:PYTHONPATH = "src"
& $pythonExe run_daily.py
if ($LASTEXITCODE -ne 0) {
    throw "run_daily.py failed."
}

# Open local dashboard in default browser
Start-Process "http://127.0.0.1:8000"

# Start UI server (foreground)
& $pythonExe ui.py
