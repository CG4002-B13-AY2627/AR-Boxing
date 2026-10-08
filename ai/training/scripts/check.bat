@echo off
rem Check the export against Brevitas, both halves of it. Windows.
rem
rem   check              set up if needed, then check
rem   check --reinstall  reinstall the dependencies first, then check
rem
rem On the first run this creates the virtual environment in src\.venv and
rem installs the requirements into it. On later runs it does neither, unless the
rem requirements file has changed since the last install. Any other argument is
rem passed straight through to check.py, so
rem
rem   check --rounding trunc
rem   check --vectors 20
rem
rem reach the checker unchanged. The rounding modes are in export\check_config.py.
rem
rem check.py runs two checks over one Brevitas pass: the exported description
rem executed as integers, and ultra-96\src\preprocess.py against the quantizer
rem at the PS/PL boundary. It exits non-zero if either fails.
rem
rem The environment is src\.venv, shared with train.bat and export.bat rather
rem than a third copy of torch: check.py imports train\config.py and
rem train\qacnn.py to rebuild the module the checkpoint was saved from, and
rem needs torch itself to produce the Brevitas side of the comparison. The setup
rem below is byte-for-byte the one in export.bat, down to the stamp file, so
rem whichever of the three scripts runs first does the install and the others
rem find the work already done.
rem
rem The virtual environment is never "activated": we call its interpreter by
rem path instead, which has the same effect and cannot leak into the calling
rem shell.

setlocal EnableDelayedExpansion

for %%I in ("%~dp0..") do set "SRC_DIR=%%~fI"
set "EXPORT_DIR=%SRC_DIR%\export"
set "TRAIN_DIR=%SRC_DIR%\train"
set "VENV_DIR=%SRC_DIR%\.venv"
set "PYTHON=%VENV_DIR%\Scripts\python.exe"
set "STAMP=%VENV_DIR%\.requirements.sha256"

rem requirements-macos.txt exists only to downgrade torch for Intel Macs.
rem Windows takes the ordinary pins.
set "REQUIREMENTS=%TRAIN_DIR%\requirements.txt"

set "REINSTALL=0"
set "ARGS="

:parse_arguments
if "%~1"=="" goto arguments_parsed
if /i "%~1"=="--reinstall" (
    set "REINSTALL=1"
) else (
    set "ARGS=!ARGS! %1"
)
shift
goto parse_arguments
:arguments_parsed

if exist "%REQUIREMENTS%" goto requirements_found
echo ERROR: "%REQUIREMENTS%" does not exist.
exit /b 1
:requirements_found

if exist "%PYTHON%" goto virtual_environment_ready

rem The py launcher ships with the python.org installer and is the reliable way
rem to ask for a specific version. Bare "python" is the fallback for a machine
rem that has Python on PATH but no launcher.
echo Creating the virtual environment in "%VENV_DIR%"
set "LAUNCHER="

py -3.13 --version >nul 2>&1
if not errorlevel 1 set "LAUNCHER=py -3.13"
if defined LAUNCHER goto create_virtual_environment

py -3.12 --version >nul 2>&1
if not errorlevel 1 set "LAUNCHER=py -3.12"
if defined LAUNCHER goto create_virtual_environment

python --version >nul 2>&1
if not errorlevel 1 set "LAUNCHER=python"
if defined LAUNCHER goto create_virtual_environment

echo ERROR: no suitable Python was found.
echo        Install Python 3.13 or 3.12 from https://www.python.org/downloads/
echo        and tick "Add python.exe to PATH" during setup.
exit /b 1

:create_virtual_environment
echo   using %LAUNCHER%
%LAUNCHER% -m venv "%VENV_DIR%"
if errorlevel 1 exit /b 1
"%PYTHON%" -m pip install --upgrade pip --quiet

rem Nothing is installed in a virtual environment that was just created.
set "REINSTALL=1"

:virtual_environment_ready

rem Reinstall when the requirements file has changed, so that editing a pin
rem takes effect on the next run rather than silently doing nothing. certutil
rem prints a header line, then the hash, then a completion line, so the first
rem line after the header is the one we want.
set "CURRENT_HASH="
for /f "skip=1 delims=" %%H in ('certutil -hashfile "%REQUIREMENTS%" SHA256') do (
    if not defined CURRENT_HASH set "CURRENT_HASH=%%H"
)
set "CURRENT_HASH=%CURRENT_HASH: =%"

set "STORED_HASH="
if exist "%STAMP%" set /p STORED_HASH=<"%STAMP%"

if "%REINSTALL%"=="1" goto install_requirements
if not "%CURRENT_HASH%"=="%STORED_HASH%" goto install_requirements
goto run_check

:install_requirements
echo Installing requirements.txt
"%PYTHON%" -m pip install -r "%REQUIREMENTS%"
if errorlevel 1 exit /b 1
>"%STAMP%" echo %CURRENT_HASH%

:run_check
rem export_config.py resolves its paths from __file__, so this is not strictly
rem needed; it is here so that anything the run writes relative to the working
rem directory lands next to the code rather than wherever the script was called
rem from.
cd /d "%EXPORT_DIR%"

echo Running check.py
"%PYTHON%" check.py%ARGS%
exit /b %errorlevel%
