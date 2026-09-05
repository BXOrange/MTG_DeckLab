@echo off
REM Development-only setup: project-local Node/ESLint plus Python dev tools.
setlocal
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0setup\install_dev.py" %*
) else (
  python "%~dp0setup\install_dev.py" %*
)
