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

# Dependencies are no longer auto-installed on each launch for faster startup.
# If requirements change, run manually:
#   .\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Cold-start UI: start Flask immediately, then the UI will trigger refresh
# and show a loading overlay while it recomputes outputs.
$env:UI_COLD_START = "true"

# Open local dashboard in default browser
Start-Process "http://127.0.0.1:8000"

# Start UI server (foreground)
& $pythonExe ui.py
