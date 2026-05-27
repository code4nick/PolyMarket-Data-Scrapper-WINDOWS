@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv" (
    python -m venv .venv
)

set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo Virtual environment python not found at .venv\Scripts\python.exe
    exit /b 1
)

rem Dependencies are no longer auto-installed on each launch for faster startup.
rem If requirements change, run manually:
rem   .\.venv\Scripts\python.exe -m pip install -r requirements.txt

set "UI_COLD_START=true"

start "" "http://127.0.0.1:8000"
"%PYTHON_EXE%" ui.py
