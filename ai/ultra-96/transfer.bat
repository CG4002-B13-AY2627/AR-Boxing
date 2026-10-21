@echo off
rem transfer.bat -- send one archived run's board artefacts to the Ultra96.
rem
rem   transfer                  prompt for the run name
rem   transfer --name mark-2    skip the prompt
rem   transfer --name pipeline/mark-2   when two kinds share a name
rem   transfer --name mark-2 --dry-run    list what would be sent
rem
rem pipeline.bat archives every run into out\pipeline\<name>\, and all.bat into
rem out\all\<name>\. Only the run's bitstream\
rem is of any use to the board, and this sends exactly that, into a bitstream/
rem subdirectory of the run on the board:
rem
rem   nn_w<N>_<B>.bit     the PL image
rem   nn_w<N>_<B>.hwh     the hardware handoff Overlay() reads for the register
rem                       map -- same basename as the .bit, side by side, which
rem                       is how PYNQ finds the second from the first
rem   norm_stats.json     per-channel standardisation the PS applies before
rem                       every inference; without it the board feeds the
rem                       accelerator raw IMU units it was never trained on
rem   description_w<N>.json  class order, window, channels, accumulator width:
rem                       the host's half of the interface contract
rem   golden_w<N>.npz     held-out windows and the logits the model produced for
rem                       them, for verify.py to replay against the accelerator.
rem                       Sent when the run has one -- unlike the four above it
rem                       is optional, because a run archived before golden.py
rem                       emitted it has none, and loading the build does not
rem                       need it
rem
rem Every file under ultra-96\scripts goes to the run root rather than into
rem src/, because those are what you run on the board and src/ is what they
rem run. So a run directory answers "how do I test this build?" by having
rem verify.sh sitting in it, next to the bitstream it tests.
rem
rem ROOT_FROM_SRC names the one exception in the other direction: a file kept
rem in ultra-96\src because that is where the host code is edited, but landing
rem at the run root because it is a starting point for a caller to copy rather
rem than part of the library a caller imports.
rem
rem Alongside them goes the PYNQ host code -- every file under ultra-96\src --
rem into a src/ subdirectory of the run. The code and the build it drives travel
rem together: a run directory holding a bitstream but not the host that loads it
rem is not something you can pick up and run.
rem
rem The run lands in its own directory on the board, named for the run, so two
rem runs never overwrite each other and the board can always say which build it
rem is holding.
rem
rem Connection details are variables, not literals -- override from the
rem environment when the lab reassigns a board:
rem
rem   set U96_HOST=... ^& set U96_JUMP=... ^& transfer --name mark-2
rem
rem Those names, and the board's password, can live in a .env beside this
rem script instead. See .env.example. The environment still wins over the file,
rem and a missing or wrong password only means ssh asks for it, exactly as it
rem did before the file existed.
rem
rem Uses Windows' own OpenSSH client (ssh.exe / scp.exe, in System32 since
rem Windows 10 1809). Nothing else is required.

setlocal EnableExtensions EnableDelayedExpansion

rem --- askpass mode -----------------------------------------------------------
rem
rem ssh re-invokes this script to ask for a password (see :with_password),
rem handing it the prompt it was about to print. There is no second script for
rem this: SSH_ASKPASS must name a program, and this is the program. The marker
rem separates the two roles -- a transfer never sets it, and ssh always does.
if "%U96_ASKPASS_MODE%"=="1" goto :askpass

set "HERE=%~dp0"
set "ROOT=%~dp0.."
for %%i in ("%ROOT%") do set "ROOT=%%~fi"
set "OUT_ROOT=%ROOT%\out"
set "SRC_DIR=%HERE%src"
set "SCRIPTS_DIR=%HERE%scripts"

rem Kept in src\, shipped to the run root. See the note above.
set "ROOT_FROM_SRC=template.py"

rem The one src\ file outside callers import by name -- Comms' server loads
rem the model through it. A run without it loads, verifies and benchmarks
rem fine, and then fails only when the server starts, so its absence stops the
rem transfer.
set "API_FROM_SRC=classifier.py"
if not defined U96_ENV set "U96_ENV=%HERE%.env"

rem --- .env -------------------------------------------------------------------

rem Read as KEY=VALUE lines, never executed. eol=# drops comments; a line with
rem no '=' is skipped by :env_set. Only four names are recognised, and anything
rem else is called out rather than silently ignored, because a misspelt key
rem looks exactly like a key that did not work.
if exist "%U96_ENV%" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%U96_ENV%") do (
        call :env_set "%%a" "%%b"
    )
)

if not defined U96_HOST set "U96_HOST=xilinx@makerslab-fpga-12.ddns.comp.nus.edu.sg"
if not defined U96_JUMP set "U96_JUMP=wayne@stujump.comp.nus.edu.sg"
if not defined U96_ROOT set "U96_ROOT=ai"

rem --- password handling ------------------------------------------------------

rem OpenSSH will take a password from a helper program instead of the console,
rem but only if told to: SSH_ASKPASS names the helper and SSH_ASKPASS_REQUIRE
rem forces its use even with a console attached.
set "AUTH=prompt"
if defined U96_HOST_PASSWORD set "AUTH=env"

rem SSH_ASKPASS_REQUIRE applies to every prompt, and we can only answer one of
rem the two. So the jump is made by its own ssh, as a ProxyCommand rather than
rem -o ProxyJump, with the helper stripped from its environment: that
rem connection asks for the NUS password on the console as it always has, and
rem only the board's prompt reaches the helper. Were the jump left under
rem -o ProxyJump, its prompt would go to the helper too, be refused, and take
rem the whole connection down with it.
rem
rem %%h and %%p are ssh's own placeholders for the host and port it wants
rem reached, and survive as %h and %p once this line is parsed. They must not
rem be expanded again after that, which is why :with_password builds the option
rem itself rather than taking it as an argument -- see the note there.
set "PROXY=cmd /c set SSH_ASKPASS=&& set SSH_ASKPASS_REQUIRE=&& set U96_ASKPASS_MODE=&& ssh -W %%h:%%p %U96_JUMP%"

set "NAME="
set "DRY_RUN=0"

rem --- arguments --------------------------------------------------------------

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--name"    goto arg_name
if /i "%~1"=="--dry-run" goto arg_dry
if /i "%~1"=="-h"        goto usage
if /i "%~1"=="--help"    goto usage
echo ERROR: unknown argument: %~1 1>&2
goto usage

:arg_name
set "NAME=%~2"
shift
shift
goto parse

:arg_dry
set "DRY_RUN=1"
shift
goto parse

:usage
echo Usage: transfer.bat [--name ^<run^>] [--dry-run]
echo.
echo   --name     the run under out\, as ^<name^> or ^<kind^>/^<name^>;
echo              prompted for if omitted
echo   --dry-run  list the files and the destination, transfer nothing
echo.
echo Override the connection with U96_HOST, U96_JUMP and U96_ROOT,
echo in the environment or in a .env beside this script ^(.env.example^).
exit /b 1

:parsed

rem --- which run --------------------------------------------------------------

if not exist "%OUT_ROOT%\" (
    echo ERROR: no out\ directory. Run src\pipeline.bat first. 1>&2
    exit /b 1
)

if not defined NAME (
    echo runs available in out\:
    call :list_runs
    echo.
    set /p "NAME=which run: "
)

if not defined NAME (
    echo ERROR: no run named. 1>&2
    exit /b 1
)

rem Runs sit one level below out\, under the script that wrote them: pipeline\,
rem all\ and sweep\. A run is therefore <kind>/<name>, and a bare <name> is
rem resolved by looking in every kind. The qualified form settles it when two
rem kinds hold the same name.
set "KIND="
for /f "tokens=1,* delims=/" %%a in ("!NAME!") do (
    if not "%%b"=="" (
        set "KIND=%%a"
        set "NAME=%%b"
    )
)

rem Both halves become path components here, and the name becomes one on the
rem board, so neither may contain anything that could leave its directory.
rem Anything outside this set is refused rather than sanitised. Tested through
rem delayed expansion so that a name holding ^& or ^| cannot reach the parser.
call :valid_part "!NAME!"
if errorlevel 1 exit /b 1
if defined KIND (
    call :valid_part "!KIND!"
    if errorlevel 1 exit /b 1
)

if not defined KIND (
    call :resolve_kind
    if errorlevel 1 exit /b 1
)

set "RUN=%OUT_ROOT%\!KIND!\!NAME!"
set "RUN_REL=out\!KIND!\!NAME!"

if not exist "!RUN!\" (
    echo ERROR: no such run: !RUN_REL! 1>&2
    echo. 1>&2
    echo runs that do exist: 1>&2
    call :list_runs 1>&2
    exit /b 1
)

set "BITSTREAM=!RUN!\bitstream"

if not exist "!BITSTREAM!\" (
    echo ERROR: !RUN_REL! has no bitstream\ directory. 1>&2
    echo        A run that failed before Vivado has none, and a sweep, which 1>&2
    echo        measures widths rather than producing one, never has one. 1>&2
    exit /b 1
)

rem --- find the files ---------------------------------------------------------

rem Globbed, not named: the width comes from the training sweep and the build
rem letter from the run, so neither is knowable here. Exactly one of each must
rem match -- two .bit files means the archive is not one coherent build.
call :one_of BIT  ".bit"              "*.bit"
if errorlevel 1 exit /b 1
call :one_of HWH  ".hwh"              "*.hwh"
if errorlevel 1 exit /b 1
call :one_of DESC "description json"  "description_w*.json"
if errorlevel 1 exit /b 1

rem Overlay('x.bit') looks for x.hwh beside it, so a mismatch here is a failure
rem that would otherwise appear on the board as a missing-metadata error.
for %%i in ("!BIT!") do set "BIT_STEM=%%~ni"
for %%i in ("!HWH!") do set "HWH_STEM=%%~ni"
if not "!BIT_STEM!"=="!HWH_STEM!" (
    echo ERROR: !BIT_STEM!.bit and !HWH_STEM!.hwh are different builds. 1>&2
    echo        PYNQ finds the .hwh by the .bit's name; they must match. 1>&2
    exit /b 1
)

set "NORM=!BITSTREAM!\norm_stats.json"

if not exist "!NORM!" (
    echo ERROR: !RUN_REL!\bitstream\norm_stats.json is absent. 1>&2
    echo        The PS cannot standardise input without it. 1>&2
    exit /b 1
)

rem Optional, where the four above are required: an older archive has no .npz,
rem and a power or pre-processing session on the board does not replay anything.
rem One run holds one width, so the last match is the only match.
set "GOLDEN="
for %%i in ("!BITSTREAM!\golden_w*.npz") do set "GOLDEN=%%~fi"

if not defined GOLDEN (
    echo note: !RUN_REL!\bitstream\ has no golden npz, so verify.py will have 1>&2
    echo       nothing to replay. The build itself is unaffected. 1>&2
)

rem --- host source ------------------------------------------------------------

if not exist "!SRC_DIR!\" (
    echo ERROR: ultra-96\src is absent. 1>&2
    echo        It holds the PYNQ host code the board runs. 1>&2
    exit /b 1
)

if not exist "!SRC_DIR!\!API_FROM_SRC!" (
    echo ERROR: ultra-96\src\!API_FROM_SRC! is absent. 1>&2
    echo        Comms imports the model through it; the server cannot start 1>&2
    echo        without it. 1>&2
    exit /b 1
)

rem Whatever is in there, not a named list: the host is still being written, and
rem a script naming its files would need editing every time one was added.
set "SRC_ITEMS="
set "SRC_COUNT=0"
set "ROOT_ITEMS="
rem Bytecode is written by whatever Python last imported these locally, and is
rem both useless on the board and possibly built by another version of Python.
rem It reappears every time the modules are imported here, so it is skipped
rem rather than deleted.
for /f "delims=" %%i in ('dir /b "!SRC_DIR!" 2^>nul') do (
    if /i not "%%i"=="__pycache__" if /i not "%%~xi"==".pyc" (
        if /i "%%i"=="!ROOT_FROM_SRC!" (
            set "ROOT_ITEMS=!ROOT_ITEMS! "!SRC_DIR!\%%i""
        ) else (
            set "SRC_ITEMS=!SRC_ITEMS! "!SRC_DIR!\%%i""
            set /a SRC_COUNT+=1
        )
    )
)

rem The runnable half, landing in the run root beside the build. Globbed for
rem the same reason src\ is. Optional rather than required: an older checkout
rem has no scripts\ and the build still loads without it.
set "SCRIPT_ITEMS="
set "SCRIPT_COUNT=0"
if exist "!SCRIPTS_DIR!\" (
    for /f "delims=" %%i in ('dir /b "!SCRIPTS_DIR!" 2^>nul') do (
        set "SCRIPT_ITEMS=!SCRIPT_ITEMS! "!SCRIPTS_DIR!\%%i""
        set /a SCRIPT_COUNT+=1
    )
)

if "!SCRIPT_COUNT!"=="0" (
    echo note: ultra-96\scripts is absent or empty, so the run will have no 1^>^&2
    echo       verify.sh. Run src/verify.py directly on the board instead. 1^>^&2
)

set "DEST=%U96_ROOT%/!NAME!"

echo.
echo run       !RUN_REL!
echo build     !BIT_STEM!
echo host      %U96_HOST%
echo jump      %U96_JUMP%
if "!AUTH!"=="env" (
    for %%i in ("%U96_ENV%") do echo auth      board password from %%~nxi; jump typed
) else (
    echo auth      both passwords typed
)
echo dest      ~/!DEST!
echo.
echo sending:
call :show "!BIT!" "bitstream/"
call :show "!HWH!" "bitstream/"
call :show "!NORM!" "bitstream/"
call :show "!DESC!" "bitstream/"
if defined GOLDEN call :show "!GOLDEN!" "bitstream/"

if not "!SCRIPT_COUNT!"=="0" (
    for /f "delims=" %%i in ('dir /b "!SCRIPTS_DIR!" 2^>nul') do (
        call :show "!SCRIPTS_DIR!\%%i"
    )
)

if exist "!SRC_DIR!\!ROOT_FROM_SRC!" call :show "!SRC_DIR!\!ROOT_FROM_SRC!"

if "!SRC_COUNT!"=="0" (
    echo         src/  empty, nothing to copy into it
) else (
    for /f "delims=" %%i in ('dir /b "!SRC_DIR!" 2^>nul') do (
        if /i not "%%i"=="__pycache__" if /i not "%%~xi"==".pyc" if /i not "%%i"=="!ROOT_FROM_SRC!" (
            if exist "!SRC_DIR!\%%i\" (
                echo         src/%%i  ^(directory^)
            ) else (
                call :show "!SRC_DIR!\%%i" "src/"
            )
        )
    )
)

if "%DRY_RUN%"=="1" (
    echo.
    echo --dry-run: nothing sent.
    exit /b 0
)

rem --- send -------------------------------------------------------------------

rem scp cannot create a missing remote directory and takes one target, so this is
rem one ssh and one copy -- a password prompt each, unless keys are set up.
echo.
echo creating ~/!DEST!

set "_PROG=ssh"
call :with_password %U96_HOST% "mkdir -p '!DEST!'"
if errorlevel 1 (
    echo ERROR: could not create ~/!DEST! on the board. 1>&2
    exit /b 1
)

set "STAGE=%TEMP%\u96_transfer_%RANDOM%%RANDOM%"
mkdir "!STAGE!\bitstream" "!STAGE!\src"
for %%f in ("!BIT!" "!HWH!" "!NORM!" "!DESC!") do copy /y "%%~f" "!STAGE!\bitstream\" >nul
if defined GOLDEN copy /y "!GOLDEN!" "!STAGE!\bitstream\" >nul
for /f "delims=" %%i in ('dir /b "!SRC_DIR!" 2^>nul') do (
    if /i not "%%i"=="__pycache__" if /i not "%%~xi"==".pyc" if /i not "%%i"=="!ROOT_FROM_SRC!" (
        if exist "!SRC_DIR!\%%i\" (
            xcopy /e /i /q /y "!SRC_DIR!\%%i" "!STAGE!\src\%%i" >nul
        ) else (
            copy /y "!SRC_DIR!\%%i" "!STAGE!\src\" >nul
        )
    )
)

echo copying

set "_PROG=scp"
call :with_password -r "!STAGE!\bitstream" "!STAGE!\src" !SCRIPT_ITEMS! !ROOT_ITEMS! "%U96_HOST%:!DEST!/"
set "_RC=!errorlevel!"
rmdir /s /q "!STAGE!"
if not "!_RC!"=="0" (
    echo ERROR: transfer failed. Nothing on the board should be trusted. 1>&2
    exit /b 1
)

echo.
echo Done. On the board:
if not "!SCRIPT_COUNT!"=="0" (
    rem bash rather than ./ because Windows has no executable bit to send, so
    rem the file arrives unexecutable however it was written here.
    echo     cd ~/!DEST! ^&^& bash verify.sh
) else (
    echo     cd ~/!DEST! ^&^& ls -l
)
exit /b 0

rem --- helpers ----------------------------------------------------------------

rem :askpass
rem Answers the board and nothing else: the jump host's prompt is not ours to
rem answer, a key passphrase is a different question, and a host-key
rem confirmation is not a password at all. Refusing is the safe answer -- ssh
rem then fails, and :with_password falls back to asking on the console.
:askpass
set "PROMPT=%*"
echo(%PROMPT%| findstr /I /C:"password" >nul || exit /b 1
if not defined U96_HOST exit /b 1
echo(%PROMPT%| findstr /C:"%U96_HOST%" >nul || exit /b 1
if not defined U96_HOST_PASSWORD exit /b 1
call echo(%%U96_HOST_PASSWORD%%
exit /b 0

rem :env_set ^<key^> ^<value^>
rem The environment wins over the file: an override set at the prompt must not
rem be undone by a file. A surrounding pair of quotes is stripped from the
rem value; nothing else about it is interpreted.
:env_set
set "_K=%~1"
set "_V=%~2"
for /f "tokens=* delims= " %%k in ("!_K!") do set "_K=%%k"
if not defined _K goto :eof
if "!_V:~0,1!"=="^"" if "!_V:~-1!"=="^"" set "_V=!_V:~1,-1!"
for %%k in (U96_HOST U96_JUMP U96_ROOT U96_HOST_PASSWORD) do (
    if /i "!_K!"=="%%k" (
        if not defined %%k set "%%k=!_V!"
        goto :eof
    )
)
for %%i in ("%U96_ENV%") do echo note: %%~nxi sets !_K!, which nothing reads. 1>&2
goto :eof

rem :with_password ^<arguments...^>
rem The program is _PROG and the connection option is added here, not passed
rem in: CALL runs a second round of %% expansion over its line, which eats the
rem %%h and %%p in PROXY -- ssh then sees "-W p" and refuses to connect. Built
rem here, the option is inserted by delayed expansion after that round, and the
rem placeholders reach ssh intact.
rem
rem Runs the command with the helper wired up, and runs it again the old way if
rem that did not work. The second attempt is what makes this safe to leave
rem switched on: every failure mode -- no .env, empty or stale password, an ssh
rem too old for SSH_ASKPASS_REQUIRE, a Windows ssh that will not run a .bat as
rem its helper -- lands on the console prompt this script would have shown
rem anyway. AUTH stays "prompt" afterwards, so the rest of the transfer does
rem not re-run the same doomed attempt. Both commands are safe to repeat: the
rem copy overwrites, the mkdir is -p.
:with_password
if "!AUTH!"=="env" (
    set "SSH_ASKPASS=%~f0"
    set "SSH_ASKPASS_REQUIRE=force"
    set "U96_ASKPASS_MODE=1"
    !_PROG! -o ProxyCommand="!PROXY!" %*
    set "_RC=!errorlevel!"
    set "SSH_ASKPASS="
    set "SSH_ASKPASS_REQUIRE="
    set "U96_ASKPASS_MODE="
    if "!_RC!"=="0" exit /b 0
    echo. 1>&2
    for %%i in ("%U96_ENV%") do echo note: the password in %%~nxi did not get through. 1>&2
    echo        Falling back to asking for it. 1>&2
    set "AUTH=prompt"
)
!_PROG! -o ProxyJump=%U96_JUMP% %*
exit /b !errorlevel!

rem :list_runs
rem Newest first: the run you just built is the one you want to send.
:list_runs
for /f "delims=" %%k in ('dir /b /ad /o-d "%OUT_ROOT%" 2^>nul') do (
    for /f "delims=" %%r in ('dir /b /ad /o-d "%OUT_ROOT%\%%k" 2^>nul') do echo     %%k/%%r
)
goto :eof

rem :valid_part ^<component^>
:valid_part
echo(%~1| findstr /R "^[-A-Za-z0-9._][-A-Za-z0-9._]*$" >nul
if errorlevel 1 (
    echo ERROR: use letters, digits, dot, dash and underscore only. 1>&2
    exit /b 1
)
if "%~1"=="."  (
    echo ERROR: "." is not a run name. 1>&2
    exit /b 1
)
if "%~1"==".." (
    echo ERROR: ".." is not a run name. 1>&2
    exit /b 1
)
exit /b 0

rem :resolve_kind
rem Which kind holds !NAME!. Exactly one must, or the caller is told to say.
:resolve_kind
set "_COUNT=0"
set "_MATCHES="
for /f "delims=" %%k in ('dir /b /ad "%OUT_ROOT%" 2^>nul') do (
    if exist "%OUT_ROOT%\%%k\!NAME!\" (
        set "KIND=%%k"
        set /a _COUNT+=1
        set "_MATCHES=!_MATCHES! %%k"
    )
)
if "!_COUNT!"=="0" (
    echo ERROR: no run named !NAME! under out\. 1>&2
    echo. 1>&2
    echo runs that do exist: 1>&2
    call :list_runs 1>&2
    exit /b 1
)
if not "!_COUNT!"=="1" (
    echo ERROR: !_COUNT! runs are named !NAME!:!_MATCHES!. 1>&2
    echo        Say which one, for instance --name ^<kind^>/!NAME!. 1>&2
    exit /b 1
)
exit /b 0

rem :one_of ^<variable^> ^<what^> ^<pattern^>
:one_of
set "%~1="
set "_COUNT=0"
for %%i in ("!BITSTREAM!\%~3") do (
    set "%~1=%%~fi"
    set /a _COUNT+=1
)
if "!_COUNT!"=="0" (
    echo ERROR: !RUN_REL!\bitstream\ holds no %~2. 1>&2
    echo        That run failed before Vivado wrote one. 1>&2
    exit /b 1
)
if not "!_COUNT!"=="1" (
    echo ERROR: !RUN_REL!\bitstream\ holds !_COUNT! %~2 files, expected one. 1>&2
    exit /b 1
)
exit /b 0

rem :show ^<file^> [prefix]
:show
for %%i in ("%~1") do set /a _KB=%%~zi/1024
if "!_KB!"=="0" (
    for %%i in ("%~1") do echo         %~2%~nx1  ^(%%~zi bytes^)
) else (
    echo         %~2%~nx1  ^(!_KB! KB^)
)
goto :eof
