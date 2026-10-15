@echo off
setlocal
title Stems Studio - Setup
cd /d "%~dp0"

echo ======================================================================
echo   Stems Studio - setup
echo   Safe to run again at any time. It only installs what is missing.
echo ======================================================================
echo.

REM The app always runs from its own private environment (.venv in this folder),
REM never from some other Python on the PC. Python 3.12 is used because PyTorch
REM ships GPU builds for it.
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PY=%VENV_PY%"
if exist "%VENV_PY%" goto check_gpu_torch

:make_venv
echo Step 1 of 4: creating a private Python 3.12 environment...
where py >nul 2>nul
if %errorlevel% neq 0 goto try_uv
py -3.12 --version >nul 2>nul
if %errorlevel% neq 0 goto try_uv
py -3.12 -m venv "%~dp0.venv"
if %errorlevel% equ 0 goto venv_ready

:try_uv
set "UV="
where uv >nul 2>nul
if not errorlevel 1 set "UV=uv"
if not defined UV (
    python -m uv --version >nul 2>nul
    if not errorlevel 1 set "UV=python -m uv"
)
if not defined UV (
    echo Installing the uv tool, which can fetch Python 3.12 for us...
    python -m pip install --user uv
    python -m uv --version >nul 2>nul
    if not errorlevel 1 set "UV=python -m uv"
)
if not defined UV goto fail_python
%UV% venv "%~dp0.venv" --python 3.12 --managed-python --seed
if %errorlevel% neq 0 goto fail_python

:venv_ready
if not exist "%VENV_PY%" goto fail_python
"%VENV_PY%" -m pip install --upgrade pip

:check_gpu_torch
where nvidia-smi >nul 2>nul
if errorlevel 1 goto no_gpu
"%PY%" -c "import sys, torch; sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>nul
if not errorlevel 1 goto check_parts
echo Step 2 of 4: NVIDIA graphics card found. Installing the GPU version of PyTorch...
echo (about 2.5 GB the first time - please be patient)
"%PY%" -m pip uninstall -y torch torchaudio >nul 2>nul
"%PY%" -m pip install "torch==2.5.1" "torchaudio==2.5.1" --index-url https://download.pytorch.org/whl/cu124
if errorlevel 1 goto fail_pip
goto check_parts

:no_gpu
echo No NVIDIA graphics card found. The stem maker will run on the CPU (slower).

:check_parts
"%PY%" -c "import demucs, yt_dlp, static_ffmpeg, soundfile, numpy" >nul 2>nul
if not errorlevel 1 goto pitch_parts
echo Step 3 of 4: installing the stem maker. This can take several minutes...
"%PY%" -m pip install -r "%~dp0separator\requirements.txt"
if errorlevel 1 goto fail_pip

:pitch_parts
"%PY%" -c "import swift_f0, soxr, mutagen" >nul 2>nul
if not errorlevel 1 goto roformer_parts
echo Installing the extras (pitch detector, key finder, lyrics)...
"%PY%" -m pip install -r "%~dp0separator\requirements-extras.txt"
if errorlevel 1 echo   (Could not install it. The app still works; some features will be simpler or switched off.)

:roformer_parts
if exist "%~dp0.venv-roformer\Lib\site-packages\audio_separator" goto chord_parts
echo.
echo Optional: "cleaner vocals" makes the vocal stem with a better model, so less
echo guitar leaks into it. It adds a few hundred MB now and a 600 MB model the first
echo time you use it.
choice /c YN /n /m "Install it now? [Y/N] "
if errorlevel 2 goto chord_parts
"%PY%" "%~dp0tools\install_roformer.py"
if errorlevel 1 echo   (Could not install it. The app still works without it.)

:chord_parts
"%PY%" "%~dp0tools\install_chord_guessers.py" --all-ready >nul 2>nul
if not errorlevel 1 goto make_shortcut
echo.
echo Optional: "more chord guessers" adds Chordino, madmom, autochord and BTC next to
echo the app's own chord guess, so you can compare them. It adds under 100 MB.
echo Any that are already installed are kept.
choice /c YN /n /m "Install them now? [Y/N] "
if errorlevel 2 goto make_shortcut
"%PY%" "%~dp0tools\install_chord_guessers.py"
if errorlevel 1 echo   (Some could not be installed. The app still works; the menu marks them.)

:make_shortcut
echo Step 4 of 4: creating the Desktop shortcuts...
set "PYDIR="
for %%I in ("%PY%") do set "PYDIR=%%~dpI"
set "GUI_PY=%PYDIR%pythonw.exe"
if not exist "%GUI_PY%" set "GUI_PY=%PY%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\make-shortcut.ps1" -Target "%GUI_PY%" -Script "%~dp0app.py"
if errorlevel 1 goto fail_shortcut

echo.
echo Checking the compute device the app will use...
"%PY%" -c "import torch; print('  GPU: ' + torch.cuda.get_device_name(0) if torch.cuda.is_available() else '  CPU only (no usable CUDA GPU)')"
echo.
echo All done.
echo Open "Stems Studio" from your Desktop or Start menu.
echo Double-click "Update Stems Studio" (the green arrow) when you want the newest window.
echo.
pause
exit /b 0

:fail_python
echo.
echo Could not create the Python environment. Install Python from python.org
echo (tick "Add python.exe to PATH"), then run this file again. Python 3.12 is
echo fetched automatically.
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
