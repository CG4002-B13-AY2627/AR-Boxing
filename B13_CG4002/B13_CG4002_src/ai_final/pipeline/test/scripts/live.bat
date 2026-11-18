@echo off
setlocal

for %%I in ("%~dp0..") do set "TEST_DIR=%%~fI"
for %%I in ("%TEST_DIR%\..") do set "VENV_DIR=%%~fI\.venv"
set "PYTHON=%VENV_DIR%\Scripts\python.exe"
set "REQUIREMENTS=%TEST_DIR%\requirements.txt"
set "STAMP=%VENV_DIR%\.test-requirements.sha256"

if not exist "%PYTHON%" (
    echo ERROR: no virtual environment in %VENV_DIR%. Run src\scripts\train first. 1>&2
    exit /b 1
)

set "CURRENT_HASH="
for /f "skip=1 delims=" %%H in ('certutil -hashfile "%REQUIREMENTS%" SHA256') do (
    if not defined CURRENT_HASH set "CURRENT_HASH=%%H"
)
set "CURRENT_HASH=%CURRENT_HASH: =%"

set "STORED_HASH="
if exist "%STAMP%" set /p STORED_HASH=<"%STAMP%"

if "%CURRENT_HASH%"=="%STORED_HASH%" goto run_live

echo Installing requirements.txt
"%PYTHON%" -m pip install -r "%REQUIREMENTS%"
if errorlevel 1 exit /b 1
>"%STAMP%" echo %CURRENT_HASH%

:run_live
"%PYTHON%" "%TEST_DIR%\live.py" %*
exit /b %errorlevel%
