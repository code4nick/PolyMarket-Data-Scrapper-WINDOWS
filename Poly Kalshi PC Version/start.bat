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

"%PYTHON_EXE%" -m pip install -r requirements.txt >nul
if errorlevel 1 exit /b 1

set "PYTHONPATH=src"
"%PYTHON_EXE%" run_daily.py
if errorlevel 1 exit /b 1

start "" "http://127.0.0.1:8000"
"%PYTHON_EXE%" ui.py
