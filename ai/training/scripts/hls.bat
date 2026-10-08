@echo off
rem Run the FPGA HLS flow. Windows, with Vitis HLS installed.
rem
rem   hls                         full build, selected width, build A
rem   hls 5 C                     full build, width 5, build C
rem   hls 6 A 2                   full build with two RTL test vectors
rem   hls 6 A 2 cosim-only        reuse existing synthesized RTL
rem   hls 6 A "" synth-export      synthesize and package IP without simulations
rem
rem Arguments are passed to fpga\hls\tcl\run_hls.tcl. With no arguments, its
rem defaults apply. A full build runs C simulation, synthesis, RTL
rem co-simulation, and IP export. cosim-only requires an existing synthesis.
rem Set VITIS_HLS to the full executable path to override tool discovery.

setlocal DisableDelayedExpansion

if /i "%~1"=="--help" goto help
if defined NN_BUILD_GUARD goto guarded
call "%~dp0build_support.bat" guard "%~f0" %*
exit /b %errorlevel%
:guarded
call "%~dp0build_support.bat" preflight
if errorlevel 1 exit /b 1

for %%I in ("%~dp0..") do set "SRC_DIR=%%~fI"
set "HLS_DIR=%SRC_DIR%\fpga\hls"
set "HLS_TOOL="

if defined VITIS_HLS (
    set "HLS_TOOL=%VITIS_HLS%"
    goto tool_found
)

for /f "delims=" %%H in ('where vitis_hls 2^>nul') do if not defined HLS_TOOL set "HLS_TOOL=%%H"
if defined HLS_TOOL goto tool_found

if defined XILINX_HLS if exist "%XILINX_HLS%\bin\vitis_hls.bat" (
    set "HLS_TOOL=%XILINX_HLS%\bin\vitis_hls.bat"
    goto tool_found
)

rem Also find the project's Vitis version when launched outside its shell.
if exist "C:\Xilinx\Vitis_HLS\2022.1\bin\vitis_hls.bat" (
    set "HLS_TOOL=C:\Xilinx\Vitis_HLS\2022.1\bin\vitis_hls.bat"
    goto tool_found
)

echo ERROR: Vitis HLS was not found. >&2
echo        Run from its command prompt or set VITIS_HLS to its full executable path. >&2
exit /b 1

:tool_found
if not exist "%HLS_TOOL%" (
    echo ERROR: Vitis HLS executable "%HLS_TOOL%" does not exist. >&2
    exit /b 1
)
if not exist "%HLS_DIR%\tcl\run_hls.tcl" (
    echo ERROR: "%HLS_DIR%\tcl\run_hls.tcl" does not exist. >&2
    exit /b 1
)

rem The Tcl script resolves sources and generated projects from this directory.
pushd "%HLS_DIR%" || exit /b 1
rem Xilinx's Windows launcher returns tee's status, which can be zero after
rem a Tcl failure. Require this invocation to reach the Tcl success marker.
:status_path
set "NN_HLS_STATUS_FILE=%TEMP%\cg4002-hls-%RANDOM%-%RANDOM%.status"
if exist "%NN_HLS_STATUS_FILE%" goto status_path
> "%NN_HLS_STATUS_FILE%" echo 1
if errorlevel 1 (
    popd
    exit /b 1
)
echo Running tcl\run_hls.tcl
if "%~1"=="" (
    call "%HLS_TOOL%" -f tcl\run_hls.tcl
) else (
    call "%HLS_TOOL%" -f tcl\run_hls.tcl -tclargs %*
)
set "HLS_EXIT_CODE=%errorlevel%"
findstr /x /c:"0" "%NN_HLS_STATUS_FILE%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: HLS did not complete the requested flow. >&2
    if "%HLS_EXIT_CODE%"=="0" set "HLS_EXIT_CODE=1"
)
del /q "%NN_HLS_STATUS_FILE%" >nul 2>&1
popd
exit /b %HLS_EXIT_CODE%

:help
echo Usage: hls.bat [width [build [cosim_count [full^|synth-export^|cosim-only^|cosim-export]]]]
echo Defaults: selected width, build A, testbench default vector count, full flow.
echo Example: hls.bat 6 A 2 cosim-only
echo Set VITIS_HLS to the full Vitis HLS executable path if needed.
exit /b 0
