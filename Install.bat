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
echo Step 1 of 4: checking Python 3.12 environment...

REM 1. Try py.exe launcher if present
where py >nul 2>nul
if not errorlevel 1 (
    py -3.12 --version >nul 2>nul
    if not errorlevel 1 (
        py -3.12 -m venv "%~dp0.venv"
        if not errorlevel 1 goto venv_ready
    )
)

REM 2. Try python.exe in PATH (ensure it is 3.12 and not a Windows Store redirector)
for /f "delims=" %%I in ('where python 2^>nul') do (
    "%%I" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
    if not errorlevel 1 (
        "%%I" -m venv "%~dp0.venv"
        if not errorlevel 1 goto venv_ready
    )
)

REM 3. Check standard Python 3.12 user and system directories
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv "%~dp0.venv"
    if not errorlevel 1 goto venv_ready
)
if exist "%ProgramFiles%\Python312\python.exe" (
    "%ProgramFiles%\Python312\python.exe" -m venv "%~dp0.venv"
    if not errorlevel 1 goto venv_ready
)

REM 4. No Python 3.12 found: automatically download and install signed Python 3.12 for the user!
echo.
echo ======================================================================
echo   Python 3.12 was not found on this system.
echo   Automatically installing Python 3.12 (one-time setup)...
echo ======================================================================
echo.

REM Try winget first if available
where winget >nul 2>nul
if not errorlevel 1 (
    echo Installing Python 3.12 via Windows Package Manager (winget)...
    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv "%~dp0.venv"
        if not errorlevel 1 goto venv_ready
    )
    if exist "%ProgramFiles%\Python312\python.exe" (
        "%ProgramFiles%\Python312\python.exe" -m venv "%~dp0.venv"
        if not errorlevel 1 goto venv_ready
    )
)

REM Fallback: Download official signed Python 3.12 installer directly from python.org
if not exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" if not exist "%ProgramFiles%\Python312\python.exe" (
    echo Downloading official Python 3.12 installer from python.org...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe', '%TEMP%\python-3.12-installer.exe')"
    if exist "%TEMP%\python-3.12-installer.exe" (
        echo Installing Python 3.12 quietly...
        start /wait "" "%TEMP%\python-3.12-installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1
        timeout /t 3 /nobreak >nul
    )
)

REM Check if Python 3.12 is available now
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv "%~dp0.venv"
    if not errorlevel 1 goto venv_ready
)
if exist "%ProgramFiles%\Python312\python.exe" (
    "%ProgramFiles%\Python312\python.exe" -m venv "%~dp0.venv"
    if not errorlevel 1 goto venv_ready
)
where py >nul 2>nul
if not errorlevel 1 (
    py -3.12 -m venv "%~dp0.venv"
    if not errorlevel 1 goto venv_ready
)

REM 5. Last resort: try uv if present
set "UV="
where uv >nul 2>nul
if not errorlevel 1 set "UV=uv"
if not defined UV (
    python -m uv --version >nul 2>nul
    if not errorlevel 1 set "UV=python -m uv"
)
if defined UV (
    %UV% venv "%~dp0.venv" --python 3.12 --managed-python --seed
    if not errorlevel 1 goto venv_ready
)

if not exist "%VENV_PY%" goto fail_python

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
if not errorlevel 1 goto init_ffmpeg
echo Step 3 of 4: installing the stem maker. This can take several minutes...
"%PY%" -m pip install -r "%~dp0separator\requirements.txt"
if errorlevel 1 goto fail_pip

:init_ffmpeg
"%PY%" -c "import static_ffmpeg; static_ffmpeg.add_paths()" >nul 2>nul

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
