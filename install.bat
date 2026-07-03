@echo off
REM Thin wrapper around setup\install.py for Windows.
setlocal

set "PYTHON=python"
where python >nul 2>nul
if errorlevel 1 (
    set "PYTHON=py"
)

"%PYTHON%" "%~dp0setup\install.py" %*
