@echo off
setlocal

for %%I in ("%~dp0..") do set "ROOT_DIR=%%~fI"
set "PYTHON=%ROOT_DIR%\pipeline\.venv\Scripts\python.exe"

if exist "%PYTHON%" goto run
echo ERROR: no environment in "%ROOT_DIR%\pipeline\.venv". Run pipeline\scripts\train once first.
exit /b 1

:run
"%PYTHON%" "%~dp0convert.py" %*
exit /b %errorlevel%
