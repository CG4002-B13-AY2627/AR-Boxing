@echo off
rem all.bat -- every HLS directive set, A through D, under one run name.
rem
rem   src\all                     prompt for a name, build A B C D
rem   src\all --name mark-5       skip the prompt
rem   src\all --from hls          resume: skip training, check and export
rem
rem pipeline.bat builds one directive set. This builds all four and compares
rem them, which is a different job with a different shape, so it is a different
rem script: pipeline.bat is the one in daily use and the one that feeds the
rem board, and it is left exactly as it is.
rem
rem Why all four. run_hls.tcl's builds A-D differ in directives only, never in
rem source, so any difference between them was caused by a pragma and nothing
rem else. That is what makes the comparison worth making -- and the comparison
rem is what answers "describe and outline the optimizations implemented" in
rem demo heading 6, and what section 5.6 selects a build with. Four separate
rem runs would scatter the numbers across four directories to be compared by
rem hand.
rem
rem   A   no directives -- the baseline the other three are an optimisation of
rem   B   pipeline the two convolution time-loops
rem   C   B + unroll the input-channel loops
rem   D   C + cyclic array partition on a1/p1
rem
rem Resource/timing failures are comparison results. Attempt every variant,
rem retain their reports, then return nonzero if any build or summary failed.
rem
rem The layout differs from pipeline.bat's, because four builds cannot share
rem one reports\ directory and out\all\<run>\bitstream\ may hold exactly one .bit
rem (transfer.bat aborts on two):
rem
rem   out\all\<name>\
rem     manifest.txt          the run, plus a per-build result block
rem     summary\summary.md    the comparison table -- the point of the exercise
rem     bitstream\            the deploy build's .bit/.hwh + the 3 shared files
rem     headers\  model\      shared: one export feeds all four builds
rem     reports\              training_loss.png, confusion_*.png
rem     logs\                 0-clean 1-train 2-check 3-export, and the summary
rem     builds\<X>\           status.txt, logs\, reports\hls\, reports\vivado\
rem
rem So transfer.bat needs no changes: bitstream\ looks exactly as it does after
rem a pipeline.bat run. Builds B-D's bitstreams are deliberately not archived --
rem out\ is git-tracked with no LFS, and every number the report quotes comes
rem from the reports, not from an overlay nobody will load. They survive in
rem src\fpga\vivado\bit\ until the next clean.
rem
rem Cosim is 65 %% of the HLS stage and its cost tracks simulated cycles, so
rem only the build that goes to the board pays for it in full; the rest run
rem QUICK_COSIM vectors. The achieved II -- the number this comparison is
rem actually about -- comes from csynth, not from cosim. What the short run
rem gives up is verification depth, which is why the summary carries a
rem vector-count row.
rem
rem cmd has no tee, so each stage writes its log and the tail is shown when the
rem stage ends. To watch a long stage live, open a second terminal and run
rem   Get-Content -Wait out\all\<name>\builds\A\logs\4-hls.log

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
set "OUT_KIND=all"
set "OUT_ROOT=%ROOT%\out\%OUT_KIND%"

set "RULE=============================================================="

rem Canonical order, always. Not an option: the whole point of this script is
rem that it runs all four, and a fixed order keeps two runs' logs diffable.
set "BUILDS=A B C D"

rem Vectors the non-deploy builds co-simulate. Enough to prove the RTL runs and
rem to measure its real latency; not enough to call it verified.
set "QUICK_COSIM=5"

set "FROM=train"
set "NAME="
set "STATUS=0"
set "MISSING=0"
set "BUILD_MISSING=0"
set "FAILED_BUILDS=0"
set "SUSPECT_BUILDS=0"
set "STAGES_RUN="
set "FAILED_AT="
set "WIDTH="
set "DEPLOY="
set "STEP=0"
set "LAST_RC=0"
set "SUMMARY_OK=0"

rem --- arguments --------------------------------------------------------------

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--name" goto arg_name
if /i "%~1"=="--from" goto arg_from
if /i "%~1"=="-h"     goto usage
if /i "%~1"=="--help" goto usage
echo ERROR: unknown argument: %~1 1>&2
goto usage

:arg_name
set "NAME=%~2"
shift
shift
goto parse

:arg_from
set "FROM=%~2"
shift
shift
goto parse

:usage
echo Usage: all.bat [--name ^<name^>] [--from ^<stage^>]
echo.
echo   --name    name of the run; prompted for if omitted
echo   --from    first stage to run: train, check, export, hls, vivado
echo.
echo Builds A, B, C and D, in that order, always. Use pipeline.bat to build
echo one. The width is not an option either: it is whatever the training
echo sweep selected, read from src\fpga\hls\selected_width.hpp.
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
rem delayed expansion so that a name holding ^& or ^| cannot reach the parser.
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

if exist "%RUN%" (
    echo ERROR: %RUN% already exists. Pick another name, or remove it first. 1>&2
    exit /b 1
)

mkdir "%RUN%\bitstream" 2>nul
mkdir "%RUN%\headers"   2>nul
mkdir "%RUN%\model"     2>nul
mkdir "%RUN%\reports"   2>nul
mkdir "%RUN%\summary"   2>nul
mkdir "%LOGS%"          2>nul

rem Every build's log directory exists before the first build runs. A redirect
rem into a directory that is not there fails the redirect, and then %errorlevel%
rem is the redirect's rather than the stage's -- a failure reported as success.
set "NBUILDS=0"
for %%B in (%BUILDS%) do (
    mkdir "%RUN%\builds\%%B\logs"            2>nul
    mkdir "%RUN%\builds\%%B\reports\hls"     2>nul
    mkdir "%RUN%\builds\%%B\reports\vivado"  2>nul
    set /a NBUILDS+=1
)

rem The first build in the list is the one that gets a full co-simulation, and
rem the one deploy falls to first. Known before anything runs, so the decision
rem never depends on a result.
for /f "tokens=1" %%B in ("%BUILDS%") do set "FULL_COSIM_BUILD=%%B"

rem train, check, export + hls and vivado per build + the summary.
set /a "TOTAL=3 + 2 * NBUILDS + 1"

call :now
set "STARTED_AT=%NOW%"
call :epoch
set "STARTED_EPOCH=%EPOCH%"

call :rank "%FROM%"
set "FROM_RANK=%RANK%"

echo.
echo run       %NAME%
echo out       %RUN_REL%
echo builds    %BUILDS%
echo cosim     full on %FULL_COSIM_BUILD%, %QUICK_COSIM% vectors on the rest
echo from      %FROM%
echo started   %STARTED_AT%

rem --- clean ----------------------------------------------------------------------

rem Once, before every build. clean.bat's globs are build-blind -- hls_w*_* and
rem vivado_w*_* -- so one clean covers all four, and the four builds that follow
rem write disjoint names and cannot tread on each other.
rem
rem Only the groups at or after the resume point. --from hls must not delete the
rem headers and checkpoints the HLS stage is about to consume; check writes
rem nothing of its own, so it cleans from export onward like export does.
set "CLEAN_STAGES="
if /i "%FROM%"=="train"  set "CLEAN_STAGES=train export hls vivado"
if /i "%FROM%"=="check"  set "CLEAN_STAGES=export hls vivado"
if /i "%FROM%"=="export" set "CLEAN_STAGES=export hls vivado"
if /i "%FROM%"=="hls"    set "CLEAN_STAGES=hls vivado"
if /i "%FROM%"=="vivado" set "CLEAN_STAGES=vivado"

echo.
echo %RULE%
echo   [0/%TOTAL%] clean
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

rem --- shared stages --------------------------------------------------------------

call :stage train  "%LOGS%" "1-train.log"  "" "%SCRIPTS%\train.bat"
if not "%LAST_RC%"=="0" if not "%LAST_RC%"=="skipped" (
    set "FAILED_AT=train"
    set "STATUS=%LAST_RC%"
    goto collect
)

call :stage check  "%LOGS%" "2-check.log"  "" "%SCRIPTS%\check.bat"
if not "%LAST_RC%"=="0" if not "%LAST_RC%"=="skipped" (
    set "FAILED_AT=check"
    set "STATUS=%LAST_RC%"
    goto collect
)

call :stage export "%LOGS%" "3-export.log" "" "%SCRIPTS%\export.bat"
if not "%LAST_RC%"=="0" if not "%LAST_RC%"=="skipped" (
    set "FAILED_AT=export"
    set "STATUS=%LAST_RC%"
    goto collect
)

call :read_width
if not defined WIDTH (
    echo. 1>&2
    echo ERROR: no width in src\fpga\hls\selected_width.hpp. 1>&2
    echo        Run the export before using --from hls. 1>&2
    set "FAILED_AT=width"
    set "STATUS=1"
    goto collect
)

echo.
echo width     %WIDTH% ^(from selected_width.hpp^)

for %%B in (%BUILDS%) do call :run_build %%B

rem --- collect the shared half ----------------------------------------------------

:collect

if not defined WIDTH call :read_width

echo.
echo %RULE%
echo   collecting into %RUN_REL%
echo %RULE%

if not defined WIDTH (
    echo.
    echo     no width resolved, so nothing named for one could be collected
    set /a MISSING+=1
    goto collect_rest
)

echo.
echo   shared

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

:collect_rest
call :take "%SRC%\train\plots\training_loss.png" "%RUN%\reports"

rem One confusion matrix per trained model: the FP32 baseline and every width the
rem sweep tried. Globbed, because the widths belong to train\config.py. A run
rem that wrote none hands :take the pattern itself, which reports it absent.
for %%F in ("%SRC%\train\plots\confusion_*.png") do call :take "%%~F" "%RUN%\reports"
if not exist "%SRC%\train\plots\confusion_*.png" call :take "%SRC%\train\plots\confusion_*.png" "%RUN%\reports"

set /a "SHARED_MISSING=MISSING - BUILD_MISSING"

rem --- manifest ---------------------------------------------------------------------

rem Written before the summary rather than after it, because summarize.py
rem quotes the manifest's own header line back into the table. That puts the
rem render one second outside the elapsed time below, which is noise next to
rem four builds.

call :now
set "FINISHED_AT=%NOW%"
call :epoch
set /a "RUN_SECONDS=EPOCH - STARTED_EPOCH"
call :duration %RUN_SECONDS%
set "ELAPSED=%DURATION%"

set "GIT_REV=unknown"
for /f "delims=" %%i in ('git -C "%ROOT%" rev-parse --short HEAD 2^>nul') do set "GIT_REV=%%i"
set "GIT_DIRTY="
for /f "delims=" %%i in ('git -C "%ROOT%" status --porcelain 2^>nul') do set "GIT_DIRTY=1"
if defined GIT_DIRTY set "GIT_REV=%GIT_REV% (dirty)"

set "RESULT=OK"
if not "%FAILED_BUILDS%"=="0" set "RESULT=PARTIAL, %FAILED_BUILDS% of %NBUILDS% build(s) failed"
if not "%SUSPECT_BUILDS%"=="0" set "RESULT=FAILED: missing or unarchived build artefacts"
if not "%SHARED_MISSING%"=="0" set "RESULT=FAILED: missing or unarchived shared artefacts"
if defined FAILED_AT set "RESULT=FAILED at %FAILED_AT%"

set "STAGES_SHOWN=%STAGES_RUN%"
if not defined STAGES_SHOWN set "STAGES_SHOWN= none"
set "WIDTH_SHOWN=%WIDTH%"
if not defined WIDTH_SHOWN set "WIDTH_SHOWN=unresolved"
set "DEPLOY_SHOWN=%DEPLOY%"
if not defined DEPLOY_SHOWN set "DEPLOY_SHOWN=none"

set "MANIFEST=%RUN%\manifest.txt"

> "%MANIFEST%" echo run          %NAME%
>>"%MANIFEST%" echo status       %RESULT%
>>"%MANIFEST%" echo started      %STARTED_AT%
>>"%MANIFEST%" echo finished     %FINISHED_AT%
>>"%MANIFEST%" echo elapsed      %ELAPSED%
>>"%MANIFEST%" echo host         %COMPUTERNAME%
>>"%MANIFEST%" echo git          %GIT_REV%
>>"%MANIFEST%" echo.
>>"%MANIFEST%" echo width        %WIDTH_SHOWN%
>>"%MANIFEST%" echo builds       %BUILDS%
>>"%MANIFEST%" echo deploy       %DEPLOY_SHOWN%
>>"%MANIFEST%" echo from         %FROM%
>>"%MANIFEST%" echo stages run  %STAGES_SHOWN%
>>"%MANIFEST%" echo absent       %SHARED_MISSING% shared artefact^(s^)
>>"%MANIFEST%" echo.

if defined DEPLOY if not "%DEPLOY%"=="%FULL_COSIM_BUILD%" call :manifest_cosim_warning

>>"%MANIFEST%" echo per build
for %%B in (%BUILDS%) do call :manifest_build %%B
>>"%MANIFEST%" echo.
>>"%MANIFEST%" echo summary/     the A-D comparison table. Start here.
>>"%MANIFEST%" echo builds/^<X^>/  one directory per build: status.txt, logs, HLS and
>>"%MANIFEST%" echo              Vivado reports. A failed build has fewer of them, and
>>"%MANIFEST%" echo              that absence is its result.
if defined DEPLOY (
    >>"%MANIFEST%" echo bitstream/   build %DEPLOY%'s .bit + .hwh, plus norm_stats.json, the
) else (
    >>"%MANIFEST%" echo bitstream/   no build produced a bitstream, so norm_stats.json, the
)
>>"%MANIFEST%" echo              description json and the golden npz -- everything needed
>>"%MANIFEST%" echo              to run the model on the Ultra96, and nothing from the
>>"%MANIFEST%" echo              other builds: transfer.bat expects exactly one .bit.
>>"%MANIFEST%" echo headers/     the generated PL interface. Shared: one export fed all
>>"%MANIFEST%" echo              %NBUILDS% builds, which is what makes them comparable.
>>"%MANIFEST%" echo model/       the quantized checkpoint everything else derives from.
>>"%MANIFEST%" echo reports/     the training loss curve and a confusion matrix per
>>"%MANIFEST%" echo              trained model.
>>"%MANIFEST%" echo logs/        stdout of the shared stages. The accuracy numbers, the
>>"%MANIFEST%" echo              layer table and the accumulator peaks live only here.
>>"%MANIFEST%" echo              Each build's own stdout is under builds/^<X^>/logs/.

rem --- summary ----------------------------------------------------------------------

rem The summary is by definition the last stage, whatever happened before it.
set "STEP=%TOTAL%"
set "SUMMARY_LOG=%LOGS%\%STEP%-summary.log"

echo.
echo %RULE%
echo   [%STEP%/%TOTAL%] summary
echo   log: logs\%STEP%-summary.log
echo %RULE%
echo.

call :find_python
if defined PYTHON (
    "%PYTHON%" "%SRC%\fpga\summarize.py" "%RUN%" > "%SUMMARY_LOG%" 2>&1
    set "SUMMARY_RC=!errorlevel!"
    type "%SUMMARY_LOG%"
) else (
    > "%SUMMARY_LOG%" echo ERROR: no working Python found.
    type "%SUMMARY_LOG%"
    set "SUMMARY_RC=127"
)

if "%SUMMARY_RC%"=="0" (
    set "SUMMARY_OK=1"
) else (
    echo. 1>&2
    echo The comparison table was NOT written. Everything it reads is 1>&2
    echo already archived, so render it whenever Python is available: 1>&2
    echo     python src\fpga\summarize.py %RUN_REL% 1>&2
)

echo.
type "%MANIFEST%"

rem --- what the exit code means -----------------------------------------------------

rem Continue after variant failures, but never report a partial run as success.

if defined FAILED_AT (
    echo.
    echo Run FAILED at %FAILED_AT%. Partial results in %RUN_REL% 1>&2
    if "%STATUS%"=="0" set "STATUS=1"
    if "%STATUS%"=="skipped" set "STATUS=1"
    exit /b !STATUS!
)

if not "%SHARED_MISSING%"=="0" (
    echo.
    echo Run finished, but %SHARED_MISSING% shared artefact^(s^) were absent. 1>&2
    exit /b 1
)

if not "%SUSPECT_BUILDS%"=="0" (
    echo.
    echo Run finished, but %SUSPECT_BUILDS% build^(s^) reported success and are 1>&2
    echo still missing artefacts. Read their status.txt. 1>&2
    exit /b 1
)

echo.
if not "%SUMMARY_OK%"=="1" exit /b 1
if not "%FAILED_BUILDS%"=="0" exit /b 1
if "%SUMMARY_OK%"=="1" (
    echo Run complete. %RUN_REL% -- read summary\summary.md
) else (
    echo Run complete. %RUN_REL% -- the comparison table is still to render.
)
exit /b 0

rem --- helpers ----------------------------------------------------------------------

rem :stage ^<label^> ^<log dir^> ^<log name^> ^<tag^> ^<script^> [arg1] [arg2] [arg3]
rem
rem Sets LAST_RC to the exit code, or to "skipped". It never decides what that
rem means: a shared stage failing ends the run, a build's stage failing is a
rem result the next build follows.
rem
rem The script is %~5 and its arguments start at %6. Counting from the wrong
rem place here runs the log directory as if it were the script.
:stage
set /a STEP+=1

set "SHOWN=%~1"
if not "%~4"=="" set "SHOWN=%~1 %~4"

rem --from is a resume, not a filter: everything from that stage onward runs.
rem Expressed as a rank and tested freshly on every call, never as a latch the
rem first match switches on -- with four builds a latch set by build A's hls
rem stays set, and B, C and D then run an hls that --from vivado asked to skip.
call :rank "%~1"
if !RANK! LSS %FROM_RANK% (
    echo.
    echo --- [!STEP!/%TOTAL%] !SHOWN! skipped ^(--from %FROM%^)
    set "LAST_RC=skipped"
    goto :eof
)

set "LOGFILE=%~2\%~3"

echo.
echo %RULE%
echo   [!STEP!/%TOTAL%] !SHOWN!
echo   log: !LOGFILE:%RUN%\=!
echo   follow live: Get-Content -Wait "!LOGFILE!"
echo %RULE%
echo.

rem Capture the exit code immediately, without a pipeline or another cmd parse.
call "%~5" %6 %7 %8 > "%LOGFILE%" 2>&1
set "RC=%errorlevel%"
>> "%LOGFILE%" echo STAGE_EXIT_CODE %RC%
set "LAST_RC=%RC%"

if not "%RC%"=="0" (
    powershell -NoProfile -Command "Get-Content -LiteralPath '%LOGFILE%' -Tail 40"
    echo.
    echo !SHOWN! exited %RC%. Full output in "%LOGFILE%" 1>&2
    goto :eof
)

powershell -NoProfile -Command "Get-Content -LiteralPath '%LOGFILE%' -Tail 20"
set "STAGES_RUN=%STAGES_RUN% !SHOWN!"
goto :eof

rem :run_build ^<letter^>
rem Always returns success. A build's failure is this run's data, not its end.
:run_build
set "B=%~1"
set "BDIR=%RUN%\builds\%B%"
set "NN_VIVADO_LOG_DIR=%BDIR%\logs\vivado"

call :now
set "B_STARTED=%NOW%"
call :epoch
set "B_EPOCH=%EPOCH%"
set "B_MISSING_BEFORE=%MISSING%"

set "COSIM_N=%QUICK_COSIM%"
set "COSIM_DEPTH=quick"
set "COSIM_SHOWN=%QUICK_COSIM%"
if /i "%B%"=="%FULL_COSIM_BUILD%" set "COSIM_N="
if /i "%B%"=="%FULL_COSIM_BUILD%" set "COSIM_DEPTH=full"
if /i "%B%"=="%FULL_COSIM_BUILD%" call :full_cosim_vectors

set "RESULT=OK"
set "VIVADO_RC=skipped"

rem COSIM_N is unquoted and may be empty, in which case it disappears rather
rem than arriving as an empty argument: run_hls.tcl then uses the header's own
rem GOLDEN_COSIM_N, which is what "full" means.
call :stage hls "%BDIR%\logs" "4-hls.log" "%B%" "%SCRIPTS%\hls.bat" %WIDTH% %B% %COSIM_N%
set "HLS_RC=%LAST_RC%"

if /i "%HLS_RC%"=="skipped" set "COSIM_DEPTH=skipped"
if /i "%HLS_RC%"=="skipped" set "COSIM_SHOWN=-"

if not "%HLS_RC%"=="0" if not "%HLS_RC%"=="skipped" goto build_hls_failed

rem Require the packaged deliverable in addition to HLS's completion marker.
if not exist "%SRC%\fpga\hls\hls_w%WIDTH%_%B%\sol\impl\ip\component.xml" goto build_no_ip

call :stage vivado "%BDIR%\logs" "5-vivado.log" "%B%" "%SCRIPTS%\vivado.bat" %WIDTH% %B%
set "VIVADO_RC=%LAST_RC%"
if not "%VIVADO_RC%"=="0" if not "%VIVADO_RC%"=="skipped" set "RESULT=FAILED at vivado"
goto build_collect

:build_hls_failed
set "RESULT=FAILED at hls"
call :skip_vivado "%B%" "its HLS stage failed"
goto build_collect

:build_no_ip
echo. 1>&2
if /i "%HLS_RC%"=="skipped" (
    echo ERROR: build %B% has no packaged IP and --from skipped its HLS. 1>&2
    echo        Only a build already synthesised can be resumed at vivado. 1>&2
    set "RESULT=no packaged IP to resume from"
) else (
    echo ERROR: build %B% reported HLS success but packaged no IP. 1>&2
    echo        Read the end of its hls log: cosim or export_design failed. 1>&2
    set "RESULT=FAILED at hls, no packaged IP"
)
call :skip_vivado "%B%" "there is no IP to implement"
goto build_collect

:build_collect
call :collect_build "%B%"
call :claim_deploy "%B%"

set /a "B_ABSENT=MISSING - B_MISSING_BEFORE"
set /a "BUILD_MISSING=BUILD_MISSING + B_ABSENT"

rem A failed build's absent artefacts are expected, so they are not counted
rem against the run. A build that reported success and is still missing
rem something is the case worth a non-zero exit.
if "!RESULT!"=="OK" (
    if not "!B_ABSENT!"=="0" (
        set /a SUSPECT_BUILDS+=1
        set "RESULT=FAILED: missing or unarchived artefacts"
    )
) else (
    set /a FAILED_BUILDS+=1
)

call :now
set "B_FINISHED=%NOW%"
call :epoch
set /a "B_SECONDS=EPOCH - B_EPOCH"
call :duration !B_SECONDS!

set "DEPLOYED=no"
if /i "%DEPLOY%"=="%B%" set "DEPLOYED=yes"

set "B_STATUS=%BDIR%\status.txt"

> "%B_STATUS%" echo build          %B%
>>"%B_STATUS%" echo result         !RESULT!
>>"%B_STATUS%" echo hls_exit       %HLS_RC%
>>"%B_STATUS%" echo vivado_exit    !VIVADO_RC!
>>"%B_STATUS%" echo cosim_vectors  !COSIM_SHOWN!
>>"%B_STATUS%" echo cosim_depth    !COSIM_DEPTH!
>>"%B_STATUS%" echo started        %B_STARTED%
>>"%B_STATUS%" echo finished       %B_FINISHED%
>>"%B_STATUS%" echo elapsed        !DURATION!
>>"%B_STATUS%" echo absent         !B_ABSENT!
>>"%B_STATUS%" echo deploy         !DEPLOYED!

goto :eof

rem :skip_vivado ^<letter^> ^<reason^>
rem The step counter has to advance even when a stage does not run, or the
rem banners stop agreeing with TOTAL halfway through the first failed build.
:skip_vivado
set /a STEP+=1
echo.
echo --- [!STEP!/%TOTAL%] vivado %~1 not run: %~2
goto :eof

rem :collect_build ^<letter^>
rem Runs whatever the build's outcome, because a timing-failed build still
rem wrote its Vivado reports and that negative slack is evidence 5.6 wants.
rem Only a build that failed *placement* wrote none, and that absence is its
rem own result.
:collect_build
set "CB=%~1"
set "CB_DIR=%RUN%\builds\%CB%"
set "CB_STEM=nn_w%WIDTH%_%CB%"
set "CB_PROJECT=%SRC%\fpga\hls\hls_w%WIDTH%_%CB%\sol"

echo.
echo   build %CB%

rem Post-implementation, which is what section 5.6 quotes -- not the HLS
rem estimates.
call :take "%SRC%\fpga\vivado\reports\%CB_STEM%_timing.rpt"      "%CB_DIR%\reports\vivado"
call :take "%SRC%\fpga\vivado\reports\%CB_STEM%_utilization.rpt" "%CB_DIR%\reports\vivado"
call :take "%SRC%\fpga\vivado\reports\%CB_STEM%_power.rpt"       "%CB_DIR%\reports\vivado"

rem sol_data.json first: it is the one structured file holding every module,
rem and nn_infer_csynth.rpt is top-function only. The moment a build pipelines
rem a loop, that loop moves into a submodule report -- so the achieved II, the
rem entire point of this run, leaves the top-level file.
call :take "%CB_PROJECT%\sol_data.json" "%CB_DIR%\reports\hls"
rem What Vitis actually applied to this solution, rather than what the Tcl
rem reads today. It survives even a build that never reached synthesis.
call :take "%CB_PROJECT%\sol.directive" "%CB_DIR%\reports\hls"

call :take "%CB_PROJECT%\syn\report\csynth.rpt"          "%CB_DIR%\reports\hls"
call :take "%CB_PROJECT%\syn\report\nn_infer_csynth.rpt" "%CB_DIR%\reports\hls"
call :take "%CB_PROJECT%\syn\report\nn_infer_csynth.xml" "%CB_DIR%\reports\hls"
call :take_glob "%CB_PROJECT%\syn\report" "nn_infer_Pipeline_*_csynth.xml" "%CB_DIR%\reports\hls"

call :take "%CB_PROJECT%\sim\report\nn_infer_cosim.rpt" "%CB_DIR%\reports\hls"
call :take "%CB_PROJECT%\sim\report\verilog\lat.rpt"    "%CB_DIR%\reports\hls"
call :take "%CB_PROJECT%\csim\report\nn_infer_csim.log" "%CB_DIR%\reports\hls"
goto :eof

rem :claim_deploy ^<letter^>
rem The one build whose overlay is archived: the first in canonical order that
rem produced both files PYNQ needs. Normally A; B, C or D only if the ones
rem before it failed, in which case it was short-cosimmed and the manifest says
rem so.
:claim_deploy
if defined DEPLOY goto :eof
if not "!RESULT!"=="OK" goto :eof
if not "%MISSING%"=="%B_MISSING_BEFORE%" goto :eof
set "CD_STEM=nn_w%WIDTH%_%~1"
if not exist "%SRC%\fpga\vivado\bit\%CD_STEM%.bit" goto :eof
if not exist "%SRC%\fpga\vivado\bit\%CD_STEM%.hwh" goto :eof
set "DEPLOY=%~1"
rem The .bit and .hwh must keep the same basename and sit side by side, which
rem is how PYNQ's Overlay^(^) finds the second from the first.
call :take "%SRC%\fpga\vivado\bit\%CD_STEM%.bit" "%RUN%\bitstream"
call :take "%SRC%\fpga\vivado\bit\%CD_STEM%.hwh" "%RUN%\bitstream"
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

rem :take_glob ^<directory^> ^<pattern^> ^<destination directory^>
rem Zero matches is not a failure here: which submodule reports exist depends
rem on which loops the build pipelined, and that is one of the things being
rem measured.
:take_glob
set "GLOB_FOUND=0"
if exist "%~1\" (
    for /f "delims=" %%F in ('dir /b /a-d "%~1\%~2" 2^>nul') do (
        copy /y "%~1\%%F" "%~3\" >nul
        if errorlevel 1 set /a MISSING+=1
        set /a GLOB_FOUND+=1
    )
)
echo     +  !GLOB_FOUND! file^(s^) matching %~2
goto :eof

rem :read_width
rem The width is discovered, not chosen: emit.py writes it into
rem selected_width.hpp from the checkpoint filename and nn_width.tcl reads the
rem same file, so this agrees with the Tcl by construction rather than by luck.
:read_width
set "WIDTH="
for /f "tokens=3" %%i in ('findstr /C:"#define NN_WIDTH_SELECTED" "%SRC%\fpga\hls\selected_width.hpp" 2^>nul') do set "WIDTH=%%i"
goto :eof

rem :full_cosim_vectors
rem What a full co-simulation actually is, read off the generated header rather
rem than restated here -- golden.py owns the number and may change it.
:full_cosim_vectors
set "COSIM_SHOWN=all"
for /f "tokens=3" %%i in ('findstr /C:"#define GOLDEN_COSIM_N" "%SRC%\fpga\hls\golden_w%WIDTH%.h" 2^>nul') do set "COSIM_SHOWN=%%i"
goto :eof

rem :rank ^<stage^> -^> RANK
:rank
set "RANK=99"
if /i "%~1"=="train"  set "RANK=1"
if /i "%~1"=="check"  set "RANK=2"
if /i "%~1"=="export" set "RANK=3"
if /i "%~1"=="hls"    set "RANK=4"
if /i "%~1"=="vivado" set "RANK=5"
goto :eof

rem :duration ^<seconds^> -^> DURATION
:duration
set /a "D_T=%~1"
set /a "D_H=D_T / 3600"
set /a "D_R=D_T - D_H * 3600"
set /a "D_M=D_R / 60"
set /a "D_S=D_R - D_M * 60"
if %D_H% LSS 10 set "D_H=0%D_H%"
if %D_M% LSS 10 set "D_M=0%D_M%"
if %D_S% LSS 10 set "D_S=0%D_S%"
set "DURATION=%D_H%h %D_M%m %D_S%s"
goto :eof

rem :now -^> NOW, :epoch -^> EPOCH
rem Both are UTC. The epoch subtracts a local midnight, so it is not a true
rem Unix time -- but only differences are ever taken from it, and the offset
rem cancels in every one of them.
:now
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ssZ')"') do set "NOW=%%i"
goto :eof

:epoch
for /f "delims=" %%i in ('powershell -NoProfile -Command "[int]((Get-Date).ToUniversalTime() - (Get-Date '1970-01-01')).TotalSeconds"') do set "EPOCH=%%i"
goto :eof

rem :find_python -^> PYTHON
rem summarize.py is stdlib only, so it runs from whatever interpreter is at
rem hand; src\.venv is preferred only because it is certainly there after a
rem full run.
:find_python
set "PYTHON="
call :try_python "%SRC%\.venv\Scripts\python.exe"
if defined PYTHON goto :eof
call :try_python "python"
if defined PYTHON goto :eof
call :try_python "python3"
if defined PYTHON goto :eof
call :try_python "py"
goto :eof

rem :try_python ^<candidate^>
rem The candidate is made to execute something before it is accepted. Windows
rem ships a python.exe on PATH that is not an interpreter at all but an App
rem Execution Alias, and it answers `where` cheerfully before printing a
rem Microsoft Store advertisement instead of running the script.
:try_python
"%~1" -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYTHON=%~1"
goto :eof

rem :manifest_build ^<letter^>
:manifest_build
set "MB_RESULT=not run"
set "MB_ELAPSED=-"
for /f "tokens=1,*" %%k in ('findstr /B /C:"result " "%RUN%\builds\%~1\status.txt" 2^>nul') do set "MB_RESULT=%%l"
for /f "tokens=1,*" %%k in ('findstr /B /C:"elapsed " "%RUN%\builds\%~1\status.txt" 2^>nul') do set "MB_ELAPSED=%%l"
>>"%MANIFEST%" echo   %~1: !MB_RESULT! [!MB_ELAPSED!]
goto :eof

rem :manifest_cosim_warning
:manifest_cosim_warning
>>"%MANIFEST%" echo WARNING      bitstream/ holds build %DEPLOY%, which was
>>"%MANIFEST%" echo              co-simulated on %QUICK_COSIM% vectors only, because
>>"%MANIFEST%" echo              %FULL_COSIM_BUILD% produced no bitstream. Re-run it at
>>"%MANIFEST%" echo              full cosim before it goes near the board:
>>"%MANIFEST%" echo                src\pipeline.bat --name ^<name^> --build %DEPLOY% --from hls
>>"%MANIFEST%" echo.
goto :eof
