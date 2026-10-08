@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%~dp0..\..\..\..") do set "SRC_DIR=%%~fI"
set "PYTHON=%SRC_DIR%\.venv\Scripts\python.exe"

if exist "%PYTHON%" goto run
echo ERROR: no environment in "%SRC_DIR%\.venv". Run src\scripts\train once first.
exit /b 1

:run
cd /d "%SCRIPT_DIR%"
"%PYTHON%" convert.py %*
exit /b %errorlevel%
