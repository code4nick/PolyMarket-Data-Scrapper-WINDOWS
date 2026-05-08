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

# Non-Windows fallback (keeps script usable elsewhere)
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -r requirements.txt >/dev/null
PYTHONPATH=src python run_daily.py
python ui.py