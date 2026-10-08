@echo off
rem Standard-library build helpers; no virtualenv activation or installation.
setlocal DisableDelayedExpansion
set "BUILD_PYTHON="
for %%I in ("%~dp0..") do set "SRC_DIR=%%~fI"
if exist "%SRC_DIR%\.venv\Scripts\python.exe" set "BUILD_PYTHON=%SRC_DIR%\.venv\Scripts\python.exe"
if defined BUILD_PYTHON goto run
for %%P in (python py python3) do (
    %%P -c "import sys" >nul 2>&1
    if not errorlevel 1 if not defined BUILD_PYTHON set "BUILD_PYTHON=%%P"
)
if not defined BUILD_PYTHON (
    echo ERROR: Python 3 is required to run the build helpers. >&2
    exit /b 1
)
:run
"%BUILD_PYTHON%" "%~dp0build_support.py" %*
exit /b %errorlevel%
