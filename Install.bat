@echo off
setlocal
title Stems Studio - Setup
cd /d "%~dp0"

echo ======================================================================
echo   Stems Studio - setup
echo   Safe to run again at any time. It only installs what is missing.
echo ======================================================================
echo.

set "LEGACY_PY=C:\Users\bacha\.gemini\antigravity-ide\scratch\venv\python.exe"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PY="
if exist "%LEGACY_PY%" set "PY=%LEGACY_PY%"
if not defined PY if exist "%VENV_PY%" set "PY=%VENV_PY%"
if defined PY goto check_parts

:make_venv
echo Step 1 of 3: creating a private Python environment...
set "BASE_PY=python"
where py >nul 2>nul
if errorlevel 1 goto have_base
py -3.11 --version >nul 2>nul
if errorlevel 1 goto have_base
set "BASE_PY=py -3.11"
:have_base
%BASE_PY% -m venv "%~dp0.venv"
if errorlevel 1 goto fail_python
set "PY=%VENV_PY%"
"%PY%" -m pip install --upgrade pip
where nvidia-smi >nul 2>nul
if errorlevel 1 goto check_parts
echo NVIDIA graphics card found. Installing the GPU version of PyTorch...
"%PY%" -m pip install "torch<2.9" "torchaudio<2.9" --index-url https://download.pytorch.org/whl/cu121

:check_parts
"%PY%" -c "import demucs, yt_dlp, static_ffmpeg, soundfile, numpy" >nul 2>nul
if not errorlevel 1 goto make_shortcut
echo Step 2 of 3: installing the stem maker. This can take several minutes...
"%PY%" -m pip install -r "%~dp0separator\requirements.txt"
if errorlevel 1 goto fail_pip

:make_shortcut
echo Step 3 of 3: creating the Stems Studio shortcut...
set "PYDIR="
for %%I in ("%PY%") do set "PYDIR=%%~dpI"
set "GUI_PY=%PYDIR%pythonw.exe"
if not exist "%GUI_PY%" set "GUI_PY=%PY%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\make-shortcut.ps1" -Target "%GUI_PY%" -Script "%~dp0app.py"
if errorlevel 1 goto fail_shortcut

echo.
echo All done. Open "Stems Studio" from your Desktop or Start menu.
echo.
pause
exit /b 0

:fail_python
echo.
echo Could not create the Python environment. Make sure Python 3.11 is installed
echo (python.org, tick "Add python.exe to PATH"), then run this file again.
pause
exit /b 1

:fail_pip
echo.
echo The install did not finish. Please copy the messages above and send them over.
pause
exit /b 1

:fail_shortcut
echo.
echo Could not create the shortcut. You can still start the app by running:
echo   "%GUI_PY%" "%~dp0app.py"
pause
exit /b 1
