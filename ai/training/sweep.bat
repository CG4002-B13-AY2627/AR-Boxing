@echo off
rem sweep.bat -- every fixed-point width in the training sweep, under one run name.
rem
rem   sweep                     prompt for a name, sweep every width
rem   sweep --name mark-7       skip the prompt
rem   sweep --build E           sweep the widths against a directive set
rem   sweep --from export       resume: reuse the trained checkpoints
rem
rem pipeline.bat builds the one width training selected. all.bat builds one
rem width against every directive set. This builds every width against one
rem directive set, into out\sweep\<name>\, and answers the question neither of
rem the others does: what a bit of precision actually costs in silicon, and
rem where the network finally breaks.
rem
rem No bitstream is archived and none is meant to be. A sweep is evidence for
rem section 5.6, not something to load: the width that ships comes from
rem pipeline.bat, which archives one. transfer.bat will say so if asked.
rem
rem Training already sweeps the widths and leaves one checkpoint per entry in
rem train\checkpoints\, so this adds only the hardware half -- check, export,
rem hls and vivado per width, driven through CHECKPOINT_OVERRIDE.
rem
rem The selected width is built first and without an override, because it is
rem the export that writes selected_width.hpp and params.hpp includes that file
rem unconditionally. An override export deliberately does not write it: a sweep
rem entry is not a change of selection.
rem
rem The work is in scripts\sweep.py, beside the stage wrappers it drives and
rem the build_config.py it takes its paths from. Five widths by four stages is
rem the same procedure on both platforms, and writing it twice in two shells is
rem how the two drift. This file is the entry point, and sits with pipeline.bat
rem and all.bat because that is where you look for something to run.

if /i "%~1"=="--help" goto run
if /i "%~1"=="-h" goto run
if defined NN_BUILD_GUARD goto run
call "%~dp0scripts\build_support.bat" guard "%~f0" %*
exit /b %errorlevel%

:run
setlocal EnableExtensions

set "SRC=%~dp0"
if "%SRC:~-1%"=="\" set "SRC=%SRC:~0,-1%"

rem scripts\sweep.py is standard library only, so any working interpreter will
rem do. src\.venv is preferred because a full run has certainly created it, and
rem because the stages it calls use it too. Each candidate is made to execute
rem something before it is accepted: the `python` Windows puts on PATH may be
rem an App Execution Alias that advertises the Store instead of running.
set "SWEEP_PYTHON="
if exist "%SRC%\.venv\Scripts\python.exe" set "SWEEP_PYTHON=%SRC%\.venv\Scripts\python.exe"
if defined SWEEP_PYTHON goto found
for %%P in (python py python3) do (
    %%P -c "import sys" >nul 2>&1
    if not errorlevel 1 if not defined SWEEP_PYTHON set "SWEEP_PYTHON=%%P"
)
if not defined SWEEP_PYTHON (
    echo ERROR: Python 3 is required to run the width sweep. 1>&2
    exit /b 1
)

:found
"%SWEEP_PYTHON%" "%SRC%\scripts\sweep.py" %*
exit /b %errorlevel%
