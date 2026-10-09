@echo off
title Stems Studio - Audio Workstation & AI Separator
echo ======================================================================
echo          Stems Studio - Multi-Track Audio Workstation
echo   Featuring 6-Stem AI Separation (Nepali Folk & Acoustic Models)
echo ======================================================================
echo.

set PYTHON_EXE=C:\Users\bacha\.gemini\antigravity-ide\scratch\venv\python.exe

if not exist "%PYTHON_EXE%" (
    echo Python virtual environment not found. Using system python...
    set PYTHON_EXE=python
)

echo Starting Stems Studio server on http://localhost:8099 ...
start "" http://localhost:8099

"%PYTHON_EXE%" "%~dp0server.py"

pause
