@echo off
title Stems Studio
cd /d "%~dp0"

echo ======================================================================
echo   Stems Studio
echo ======================================================================
echo.

set "LEGACY_PY=C:\Users\bacha\.gemini\antigravity-ide\scratch\venv\python.exe"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if exist "%LEGACY_PY%" goto use_legacy
if exist "%VENV_PY%" goto use_venv
goto setup

:use_legacy
set "PY=%LEGACY_PY%"
goto run

:use_venv
set "PY=%VENV_PY%"
goto run

:setup
echo First-time setup: installing the stem maker.
echo This happens only once and can take several minutes. Please wait...
echo.

set "BASE_PY=python"
where py >nul 2>nul
if errorlevel 1 goto make_venv
py -3.11 --version >nul 2>nul
if errorlevel 1 goto make_venv
set "BASE_PY=py -3.11"

:make_venv
%BASE_PY% -m venv "%~dp0.venv"
if errorlevel 1 goto fail
set "PY=%VENV_PY%"

"%PY%" -m pip install --upgrade pip

where nvidia-smi >nul 2>nul
if errorlevel 1 goto install_rest
echo NVIDIA graphics card found - installing the GPU version of PyTorch...
"%PY%" -m pip install "torch<2.9" "torchaudio<2.9" --index-url https://download.pytorch.org/whl/cu121

:install_rest
"%PY%" -m pip install -r "%~dp0separator\requirements.txt"
if errorlevel 1 goto fail
echo.
echo Setup finished.
echo.
goto run

:run
rem Stop any older copy still holding port 8099 so the new server code is the one that runs.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8099 .*LISTENING"') do taskkill /f /pid %%p >nul 2>nul

echo Starting Stems Studio at http://localhost:8099
echo Keep this window open while you use the app. Close it to quit.
echo.
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8099"
"%PY%" "%~dp0server.py"
echo.
echo Stems Studio has stopped.
pause
exit /b 0

:fail
echo.
echo Setup did not finish. Please copy the messages above and send them over.
pause
exit /b 1
