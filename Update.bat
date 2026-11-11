@echo off
setlocal
REM Run from a copy, so replacing this file mid-update cannot confuse the rest of the steps.
if /I not "%~1"=="--go" (
  copy /Y "%~f0" "%TEMP%\Update-Stems-Studio.bat" >nul
  if errorlevel 1 goto run_here
  "%TEMP%\Update-Stems-Studio.bat" --go "%~dp0"
  exit /b
)
cd /d "%~2"
goto start

:run_here
cd /d "%~dp0"

:start
title Update Stems Studio

REM Every update follows the main copy, not a one-off branch.
set "BRANCH=main"
set "PY=%CD%\.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=%CD%\.venv\Scripts\python.exe"

echo Closing Stems Studio if it is open...
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\tools\close-stems-studio.ps1" -Root "%CD%"

echo.
echo Getting the newest Stems Studio...
where git >nul 2>nul
if errorlevel 1 goto zip_update
if not exist "%CD%\.git" goto zip_update

git fetch origin
if errorlevel 1 goto fail_fetch

git rev-parse --verify %BRANCH% >nul 2>nul
if errorlevel 1 (
  git checkout -b %BRANCH% origin/%BRANCH%
) else (
  git checkout %BRANCH%
)
if errorlevel 1 goto fail_gitwork

git pull --ff-only origin %BRANCH%
if errorlevel 1 goto fail_gitwork
goto post_update

:zip_update
set "CONSOLE_PY=%CD%\.venv\Scripts\python.exe"
if not exist "%CONSOLE_PY%" goto fail_python
"%CONSOLE_PY%" -c "import sys, updater; r = updater.apply_zip_update(); print(r.get('message', '')); sys.exit(0 if r.get('ok') else 1)"
if errorlevel 1 goto fail_fetch

:post_update
if not exist "%PY%" goto fail_python

echo.
echo Putting "Update Stems Studio" on the Desktop...
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\tools\make-shortcut.ps1" -Target "%PY%" -Script "%CD%\app.py"
if errorlevel 1 echo   ^(The shortcut could not be created. The app will still open.^)

echo.
echo Opening Stems Studio...
start "" "%PY%" "%CD%\app.py"
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
