@echo off
setlocal
title Update Stems Studio
cd /d "%~dp0"

REM The new window lives on this branch until it is part of the normal copy.
set "BRANCH=cursor/compact-layout-dac8"
set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"

echo Closing Stems Studio if it is open...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\close-stems-studio.ps1" -Root "%~dp0"

echo.
echo Getting the newest Stems Studio...
where git >nul 2>nul
if errorlevel 1 goto fail_git
if not exist "%~dp0.git" goto fail_git

git fetch origin
if errorlevel 1 goto fail_fetch

git checkout -B %BRANCH% origin/%BRANCH%
if errorlevel 1 goto fail_gitwork

git pull --ff-only origin %BRANCH%
if errorlevel 1 goto fail_gitwork

if not exist "%PY%" goto fail_python

echo.
echo Putting "Update Stems Studio" on the Desktop...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\make-shortcut.ps1" -Target "%PY%" -Script "%~dp0app.py"
if errorlevel 1 echo   (The shortcut could not be created. The app will still open.)

echo.
echo Opening Stems Studio...
start "" "%PY%" "%~dp0app.py"
exit /b 0

:fail_git
echo.
echo Git is not available in this folder, so the update cannot download.
echo Install Git, then double-click Update Stems Studio again.
goto fail

:fail_fetch
echo.
echo The download did not finish. Check the internet connection and try again.
goto fail

:fail_gitwork
echo.
echo The update did not finish. If the message above says you have local changes,
echo close whatever is editing the folder and double-click this again.
goto fail

:fail_python
echo.
echo The app's Python is missing. Double-click Install.bat in this folder first.
goto fail

:fail
echo.
pause
exit /b 1
