#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# On Windows (Git Bash/MSYS/Cygwin), delegate to PowerShell launcher.
case "${OSTYPE:-}" in
  msys*|cygwin*|win32*)
    powershell.exe -ExecutionPolicy Bypass -File ./start.ps1
    exit $?
    ;;
esac

# macOS / Linux
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

# Dependencies are no longer auto-installed on each launch for faster startup.
# If requirements change, run manually:
#   python -m pip install -r requirements.txt

# Cold-start UI: Flask starts immediately; UI will trigger refresh.
export UI_COLD_START=true
PYTHONPATH=src python3 ui.py
