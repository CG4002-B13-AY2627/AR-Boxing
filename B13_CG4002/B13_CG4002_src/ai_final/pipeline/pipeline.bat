@echo off
rem pipeline.bat -- the whole AI lane end to end, archived as one named run.
rem
rem   src\pipeline                     prompt for a name, build, and HLS mode
rem   src\pipeline --name sweep-w6-B   skip the name prompt
rem   src\pipeline --build E           skip the build picker
rem   src\pipeline --from hls          resume: skip training, check and export
rem
rem clean.bat runs first, so every run starts from nothing. The reason is the
rem archive, not the build: a run that dies in HLS never overwrites bit\ or
rem reports\, so without this the run folder quietly collects the *previous*
rem build's bitstream and timing numbers and presents them as its own.
rem
rem The five stages are the five scripts in src\scripts\, in the only order that works:
rem
rem   1 train    train.bat    FP32 baseline, QAT width sweep, selects a width
rem   2 check    check.bat    check.py: the description, and preprocess.py, vs Brevitas
rem   3 export   export.bat   headers + golden vectors for the selected width
rem   4 hls      hls.bat      full flow or synthesis -^> packaged IP
rem   5 vivado   vivado.bat   block design -^> implementation -^> .bit / .hwh
rem
rem check runs before export on purpose: it re-extracts the description itself
rem and needs no headers, so putting it first means headers are never emitted
rem from arithmetic that does not reproduce Brevitas. That is also why it reads
rem norm_stats.json from train\checkpoints\ rather than from a run directory --
rem the archive does not exist yet when it runs.
rem
rem Everything worth keeping is copied into out\pipeline\<name>\ at the end -- on
rem failure too, so a broken run still leaves its logs and whatever it got to.
rem
rem cmd has no tee, so each stage writes its log and the tail is shown when the
rem stage ends. To watch a long stage live, open a second terminal and run
rem   Get-Content -Wait out\pipeline\<name>\logs\1-train.log
rem
rem make_dummy_data.py is deliberately NOT run. Regenerating the dataset would
rem reshuffle the participant split and make this run incomparable with the
rem last. Run it by hand when the class list or the channel list changes.

if /i "%~1"=="--help" goto usage
if /i "%~1"=="-h" goto usage
if defined NN_BUILD_GUARD goto guarded
call "%~dp0scripts\build_support.bat" guard "%~f0" %*
exit /b %errorlevel%
:guarded
setlocal EnableExtensions EnableDelayedExpansion

set "SRC=%~dp0"
if "%SRC:~-1%"=="\" set "SRC=%SRC:~0,-1%"
for %%I in ("%SRC%\..") do set "ROOT=%%~fI"
set "SCRIPTS=%SRC%\scripts"
set "OUT_KIND=pipeline"
set "OUT_ROOT=%ROOT%\out\%OUT_KIND%"

set "RULE=============================================================="

set "BUILD="
set "FROM=train"
set "NAME="
set "HLS_MODE="
set "STATUS=0"
set "MISSING=0"
set "STAGES_RUN="
set "FAILED_AT="
set "REACHED=0"
set "WIDTH="

rem --- arguments --------------------------------------------------------------

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--name"  goto arg_name
if /i "%~1"=="--build" goto arg_build
if /i "%~1"=="--from"  goto arg_from
if /i "%~1"=="--hls-mode" goto arg_hls_mode
if /i "%~1"=="-h"      goto usage
if /i "%~1"=="--help"  goto usage
echo ERROR: unknown argument: %~1 1>&2
goto usage

:arg_name
set "NAME=%~2"
shift
shift
goto parse

:arg_build
set "BUILD=%~2"
shift
shift
goto parse

:arg_from
set "FROM=%~2"
shift
shift
goto parse

:arg_hls_mode
set "HLS_MODE=%~2"
shift
shift
goto parse

:usage
echo Usage: pipeline.bat [--name ^<name^>] [--build ^<letter^>] [--from ^<stage^>] [--hls-mode ^<mode^>]
echo.
echo   --name    name of the run; prompted for if omitted
echo   --build   HLS/Vivado directive set; picked from a list if omitted
echo   --from    first stage to run: train, check, export, hls, vivado
echo   --hls-mode  full or synth-export; picked after export if omitted
echo.
echo The width is not an option: it is whatever the training sweep selected,
echo read from src\fpga\hls\selected_width.hpp after the export.
exit /b 1

:parsed

set "VALID="
if /i "%FROM%"=="train"  set "VALID=1"
if /i "%FROM%"=="check"  set "VALID=1"
if /i "%FROM%"=="export" set "VALID=1"
if /i "%FROM%"=="hls"    set "VALID=1"
if /i "%FROM%"=="vivado" set "VALID=1"
if not defined VALID (
    echo ERROR: --from must be train, check, export, hls or vivado. 1>&2
    exit /b 1
)

rem --- the run's name and its folder -------------------------------------------

if not defined NAME set /p "NAME=name of the run: "

if not defined NAME (
    echo ERROR: a run needs a name. 1>&2
    exit /b 1
)

rem The name becomes a path, so it may not contain anything that could leave
rem out\. Anything outside this set is refused rather than sanitised, because a
rem silently renamed run is worse than one that did not start. Tested through
rem delayed expansion so that a name holding & or | cannot reach the parser.
echo(!NAME!| findstr /R "^[-A-Za-z0-9._][-A-Za-z0-9._]*$" >nul
if errorlevel 1 (
    echo ERROR: use letters, digits, dot, dash and underscore only. 1>&2
    exit /b 1
)
if "!NAME!"=="."  (
    echo ERROR: "." is not a run name. 1>&2
    exit /b 1
)
if "!NAME!"==".." (
    echo ERROR: ".." is not a run name. 1>&2
    exit /b 1
)

set "RUN=%OUT_ROOT%\%NAME%"
set "RUN_REL=out\%OUT_KIND%\%NAME%"
set "LOGS=%RUN%\logs"
set "NN_VIVADO_LOG_DIR=%LOGS%\vivado"

if exist "%RUN%" (
    echo ERROR: %RUN% already exists. Pick another name, or remove it first. 1>&2
    exit /b 1
)

rem The build is asked for the same way the name is, and only when the command
rem line did not settle it. The list and the default come from build_config.py,
rem so this script spells no letter of its own. An empty answer takes the
rem default, and so does a closed stdin -- a scripted run must not stop on a
rem question. resolve-build is what rejects a letter that does not exist.
if not defined BUILD (
    echo.
    echo which build?
    call "%SCRIPTS%\build_support.bat" list-builds
    set /p "BUILD=build: "
)

rem Screened to letters before it reaches a command line, for the same reason
rem the name is screened before it becomes a path: an answer holding & or a
rem quote must not reach the parser.
if defined BUILD (
    echo(!BUILD!| findstr /R "^[A-Za-z][A-Za-z]*$" >nul
    if errorlevel 1 (
        echo ERROR: a build is a letter. 1>&2
        exit /b 1
    )
)

set "RESOLVED="
for /f "usebackq delims=" %%L in (`call "%SCRIPTS%\build_support.bat" resolve-build "!BUILD!"`) do set "RESOLVED=%%L"
if not defined RESOLVED exit /b 1
set "BUILD=!RESOLVED!"

mkdir "%RUN%\bitstream"      2>nul
mkdir "%RUN%\headers"        2>nul
mkdir "%RUN%\model"          2>nul
mkdir "%RUN%\reports\vivado" 2>nul
mkdir "%RUN%\reports\hls"    2>nul
mkdir "%LOGS%"               2>nul

for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ssZ')"') do set "STARTED_AT=%%i"

echo.
echo run       %NAME%
echo out       %RUN_REL%
echo build     %BUILD%
echo from      %FROM%
echo started   %STARTED_AT%

rem --- clean ----------------------------------------------------------------------

rem Only the groups at or after the resume point. --from hls must not delete the
rem headers and checkpoints stage 4 is about to consume; check writes nothing of
rem its own, so it cleans from export onward like export does.
set "CLEAN_STAGES="
if /i "%FROM%"=="train"  set "CLEAN_STAGES=train export hls vivado"
if /i "%FROM%"=="check"  set "CLEAN_STAGES=export hls vivado"
if /i "%FROM%"=="export" set "CLEAN_STAGES=export hls vivado"
if /i "%FROM%"=="hls"    set "CLEAN_STAGES=hls vivado"
if /i "%FROM%"=="vivado" set "CLEAN_STAGES=vivado"

echo.
echo %RULE%
echo   [0/5] clean
echo   log: logs\0-clean.log
echo %RULE%
echo.

call "%SCRIPTS%\clean.bat" %CLEAN_STAGES% > "%LOGS%\0-clean.log" 2>&1
set "CLEAN_RC=%errorlevel%"
type "%LOGS%\0-clean.log"

if not "%CLEAN_RC%"=="0" (
    echo.
    echo FAILED: the cleaner refused to run, so nothing was built. 1>&2
    echo Cleanup may be partial. Inspect %RUN_REL%\logs\0-clean.log. 1>&2
    exit /b 1
)

rem --- stages -------------------------------------------------------------------

call :stage 1 train  "%SCRIPTS%\train.bat"
if defined FAILED_AT goto collect

call :stage 2 check  "%SCRIPTS%\check.bat"
if defined FAILED_AT goto collect

call :stage 3 export "%SCRIPTS%\export.bat"
if defined FAILED_AT goto collect

call :read_width
if not defined WIDTH (
    echo ERROR: no width in src\fpga\hls\selected_width.hpp. 1>&2
    echo        Run the export before using --from hls. 1>&2
    set "FAILED_AT=width"
    set "STATUS=1"
    goto collect
)

echo.
echo width     %WIDTH% ^(from selected_width.hpp^)

if /i "%FROM%"=="vivado" if not defined HLS_MODE set "HLS_MODE=full"
call :choose_hls_mode
if errorlevel 1 (
    set "FAILED_AT=hls-mode"
    set "STATUS=1"
    goto collect
)

call :stage 4 hls    "%SCRIPTS%\hls.bat" %WIDTH% %BUILD% "" %HLS_MODE%
if defined FAILED_AT goto collect

rem Check the deliverable as well as the stage's exit code before Vivado.
if not exist "%SRC%\fpga\hls\hls_w%WIDTH%_%BUILD%\sol\impl\ip\component.xml" (
    echo.
    echo ERROR: HLS reported success but packaged no IP. 1>&2
    echo        Read the end of the hls log for the export_design failure. 1>&2
    set "FAILED_AT=hls"
    set "STATUS=1"
    goto collect
)

call :stage 5 vivado "%SCRIPTS%\vivado.bat" %WIDTH% %BUILD%
if defined FAILED_AT goto collect

rem --- collect --------------------------------------------------------------------

:collect

if not defined WIDTH call :read_width

echo.
echo %RULE%
echo   collecting into %RUN_REL%
echo %RULE%
echo.

if not defined WIDTH (
    echo     no width resolved, so nothing named for one could be collected
    set /a MISSING+=1
    goto collect_rest
)

set "STEM=nn_w%WIDTH%_%BUILD%"
set "HLS_PROJECT=%SRC%\fpga\hls\hls_w%WIDTH%_%BUILD%\sol"

rem Everything the Ultra96 needs and nothing it does not. The .bit and .hwh
rem must keep the same basename and sit side by side, which is how PYNQ's
rem Overlay() finds the second from the first.
call :take "%SRC%\fpga\vivado\bit\%STEM%.bit" "%RUN%\bitstream"
call :take "%SRC%\fpga\vivado\bit\%STEM%.hwh" "%RUN%\bitstream"
rem The PS applies this standardisation before every DMA. Without it the board
rem feeds the accelerator raw IMU units it was never trained on.
call :take "%SRC%\train\checkpoints\norm_stats.json" "%RUN%\bitstream"
rem Class order, window, channels and the accumulator width: the host's half of
rem the interface contract, in the one file that is machine readable.
call :take "%SRC%\export\build\description_w%WIDTH%.json" "%RUN%\bitstream"
rem The golden header is C initialisers, which the board cannot read. Same
rem vectors, same run, in the form verify.py loads.
call :take "%SRC%\fpga\hls\golden_w%WIDTH%.npz" "%RUN%\bitstream"

call :take "%SRC%\fpga\hls\params_w%WIDTH%.hpp"  "%RUN%\headers"
call :take "%SRC%\fpga\hls\weights_w%WIDTH%.hpp" "%RUN%\headers"
call :take "%SRC%\fpga\hls\golden_w%WIDTH%.h"    "%RUN%\headers"
call :take "%SRC%\fpga\hls\selected_width.hpp"   "%RUN%\headers"

call :take "%SRC%\train\qmodel\qacnn_w%WIDTH%.pt" "%RUN%\model"

rem Post-implementation, which is what section 5.6 quotes -- not the HLS
rem estimates, which are in the csynth report below for the comparison.
call :take "%SRC%\fpga\vivado\reports\%STEM%_timing.rpt"      "%RUN%\reports\vivado"
call :take "%SRC%\fpga\vivado\reports\%STEM%_utilization.rpt" "%RUN%\reports\vivado"
call :take "%SRC%\fpga\vivado\reports\%STEM%_power.rpt"       "%RUN%\reports\vivado"

call :take "%HLS_PROJECT%\syn\report\nn_infer_csynth.rpt" "%RUN%\reports\hls"
if /i "%HLS_MODE%"=="synth-export" (
    echo     -  HLS simulation reports skipped ^(synth-export mode^)
) else (
    call :take "%HLS_PROJECT%\sim\report\nn_infer_cosim.rpt"  "%RUN%\reports\hls"
    call :take "%HLS_PROJECT%\sim\report\verilog\lat.rpt"     "%RUN%\reports\hls"
    call :take "%HLS_PROJECT%\csim\report\nn_infer_csim.log"  "%RUN%\reports\hls"
)

:collect_rest
call :take "%SRC%\train\plots\training_loss.png" "%RUN%\reports"

rem One confusion matrix per trained model: the FP32 baseline and every width the
rem sweep tried. Globbed, because the widths belong to train\config.py. A run
rem that wrote none hands :take the pattern itself, which reports it absent.
for %%F in ("%SRC%\train\plots\confusion_*.png") do call :take "%%~F" "%RUN%\reports"
if not exist "%SRC%\train\plots\confusion_*.png" call :take "%SRC%\train\plots\confusion_*.png" "%RUN%\reports"

rem --- manifest ---------------------------------------------------------------------

for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ssZ')"') do set "FINISHED_AT=%%i"

set "GIT_REV=unknown"
for /f "delims=" %%i in ('git -C "%ROOT%" rev-parse --short HEAD 2^>nul') do set "GIT_REV=%%i"
set "GIT_DIRTY="
for /f "delims=" %%i in ('git -C "%ROOT%" status --porcelain 2^>nul') do set "GIT_DIRTY=1"
if defined GIT_DIRTY set "GIT_REV=%GIT_REV% (dirty)"

set "RESULT=OK"
if not "%MISSING%"=="0" set "RESULT=FAILED: missing or unarchived artefacts"
if defined FAILED_AT set "RESULT=FAILED at %FAILED_AT%"

set "STAGES_SHOWN=%STAGES_RUN%"
if not defined STAGES_SHOWN set "STAGES_SHOWN= none"
set "WIDTH_SHOWN=%WIDTH%"
if not defined WIDTH_SHOWN set "WIDTH_SHOWN=unresolved"

set "MANIFEST=%RUN%\manifest.txt"

> "%MANIFEST%" echo run          %NAME%
>>"%MANIFEST%" echo status       %RESULT%
>>"%MANIFEST%" echo started      %STARTED_AT%
>>"%MANIFEST%" echo finished     %FINISHED_AT%
>>"%MANIFEST%" echo host         %COMPUTERNAME%
>>"%MANIFEST%" echo git          %GIT_REV%
>>"%MANIFEST%" echo.
>>"%MANIFEST%" echo width        %WIDTH_SHOWN%
>>"%MANIFEST%" echo build        %BUILD%
>>"%MANIFEST%" echo from         %FROM%
if defined HLS_MODE (>>"%MANIFEST%" echo hls mode     %HLS_MODE%) else (>>"%MANIFEST%" echo hls mode     not selected)
>>"%MANIFEST%" echo stages run  %STAGES_SHOWN%
>>"%MANIFEST%" echo absent       %MISSING% artefact^(s^)
>>"%MANIFEST%" echo.
>>"%MANIFEST%" echo bitstream/   .bit + .hwh + norm_stats.json + description json + golden npz.
>>"%MANIFEST%" echo              Everything needed to run the model on the Ultra96.
>>"%MANIFEST%" echo headers/     the generated PL interface, exactly as this run built it.
>>"%MANIFEST%" echo model/       the quantized checkpoint everything else derives from.
>>"%MANIFEST%" echo reports/     vivado post-implementation and HLS estimates; simulation
>>"%MANIFEST%" echo              reports are included when HLS mode is full. The
>>"%MANIFEST%" echo              loss curve and a confusion matrix per trained model.
>>"%MANIFEST%" echo logs/        stdout of every stage. The accuracy numbers, the layer
>>"%MANIFEST%" echo              table and the accumulator peaks live only here.

echo.
type "%MANIFEST%"

if defined FAILED_AT (
    echo.
    echo Run FAILED at stage %FAILED_AT%. Partial results in %RUN_REL% 1>&2
    if "%STATUS%"=="0" set "STATUS=1"
    exit /b %STATUS%
)

if not "%MISSING%"=="0" (
    echo.
    echo Run finished, but %MISSING% expected artefact^(s^) were absent. 1>&2
    exit /b 1
)

echo.
echo Run complete. %RUN_REL%
exit /b 0

rem --- helpers ----------------------------------------------------------------------

rem :stage ^<step^> ^<label^> ^<script^> [arg1] [arg2] [arg3] [arg4]
rem Stages are named in order, so the first match switches execution on and
rem everything after it follows. --from is a resume, not a filter.
:stage
if not "%REACHED%"=="1" if /i "%~2"=="%FROM%" set "REACHED=1"
if not "%REACHED%"=="1" (
    echo.
    echo --- [%~1/5] %~2 skipped ^(--from %FROM%^)
    goto :eof
)

set "LOGFILE=%LOGS%\%~1-%~2.log"

echo.
echo %RULE%
echo   [%~1/5] %~2
echo   log: logs\%~1-%~2.log
echo   follow live: Get-Content -Wait "%LOGFILE%"
echo %RULE%
echo.

rem Capture the exit code immediately, without a pipeline or another cmd parse.
call "%~3" %4 %5 %6 %7 > "%LOGFILE%" 2>&1
set "RC=%errorlevel%"
>> "%LOGFILE%" echo STAGE_EXIT_CODE %RC%

if not "%RC%"=="0" (
    powershell -NoProfile -Command "Get-Content -LiteralPath '%LOGFILE%' -Tail 40"
    echo.
    echo FAILED at stage %~2. Full output in %RUN_REL%\logs\%~1-%~2.log 1>&2
    set "FAILED_AT=%~2"
    set "STATUS=%RC%"
    goto :eof
)

powershell -NoProfile -Command "Get-Content -LiteralPath '%LOGFILE%' -Tail 20"
set "STAGES_RUN=%STAGES_RUN% %~2"
goto :eof

:choose_hls_mode
if not defined HLS_MODE (
    echo.
    echo which HLS flow?
    echo   1  full: C simulation, synthesis, RTL co-simulation, IP export
    echo   2  synth-export: synthesis and IP export only
    set /p "HLS_MODE=HLS mode [1]: "
)
if not defined HLS_MODE set "HLS_MODE=full"
if /i "%HLS_MODE%"=="1" set "HLS_MODE=full"
if /i "%HLS_MODE%"=="2" set "HLS_MODE=synth-export"
if /i "%HLS_MODE%"=="full" goto hls_mode_selected
if /i "%HLS_MODE%"=="synth-export" goto hls_mode_selected
echo ERROR: HLS mode must be full or synth-export. 1>&2
exit /b 1
:hls_mode_selected
echo hls mode  %HLS_MODE%
exit /b 0

rem :read_width
rem The width is discovered, not chosen: emit.py writes it into
rem selected_width.hpp from the checkpoint filename and nn_width.tcl reads the
rem same file, so this agrees with the Tcl by construction rather than by luck.
:read_width
set "WIDTH="
for /f "tokens=3" %%i in ('findstr /C:"#define NN_WIDTH_SELECTED" "%SRC%\fpga\hls\selected_width.hpp" 2^>nul') do set "WIDTH=%%i"
goto :eof

rem :take ^<file^> ^<destination directory^>
:take
if exist "%~1" (
    copy /y "%~1" "%~2\" >nul
    if errorlevel 1 (
        echo     -  %~nx1 ^(copy failed^) 1>&2
        set /a MISSING+=1
    ) else (
        echo     +  %~nx1
    )
) else (
    echo     -  %~nx1 ^(absent^)
    set /a MISSING+=1
)
goto :eof
