@echo off
rem Run the FPGA Vivado flow. Windows, with Vivado installed.
rem
rem   vivado                      implement width 6, build A
rem   vivado 5 C                  implement width 5, build C
rem   vivado 6 A bd               block design only, validated and saved
rem
rem Runs fpga\vivado\tcl\install_board.tcl, then fpga\vivado\tcl\block_design.tcl.
rem The first is idempotent: it installs the Avnet board part only when it is
rem missing, so a fresh machine works unattended and a configured one pays a
rem catalog query.
rem
rem Arguments are passed to block_design.tcl. With no arguments, its defaults
rem apply: width 6, build A, full flow through write_bitstream. bd as the
rem third argument stops after validate_bd_design.
rem
rem Each phase uses a fresh process and scratch directory. Logs and journals
rem go to NN_VIVADO_LOG_DIR, or fpga\vivado\logs for standalone runs.
rem
rem Set VIVADO to the full executable path to override tool discovery.

setlocal DisableDelayedExpansion

if /i "%~1"=="--help" goto help

set "SELF=%~f0"
set "SCRIPT_DIR=%~dp0"
for %%I in ("%~dp0..") do set "SRC_DIR=%%~fI"
set "VIVADO_DIR=%SRC_DIR%\fpga\vivado"
set "VIVADO_TOOL="

if defined VIVADO (
    set "VIVADO_TOOL=%VIVADO%"
    goto tool_found
)

rem This script is itself named vivado.bat and `where` searches the current
rem directory first, so skip a match that is this file: otherwise discovery
rem finds the wrapper and it calls itself.
for /f "delims=" %%H in ('where vivado 2^>nul') do (
    if not defined VIVADO_TOOL if /i not "%%~fH"=="%SELF%" set "VIVADO_TOOL=%%H"
)
if defined VIVADO_TOOL goto tool_found

if defined XILINX_VIVADO if exist "%XILINX_VIVADO%\bin\vivado.bat" (
    set "VIVADO_TOOL=%XILINX_VIVADO%\bin\vivado.bat"
    goto tool_found
)

rem Also find the project's Vivado version when launched outside its shell.
if exist "C:\Xilinx\Vivado\2022.1\bin\vivado.bat" (
    set "VIVADO_TOOL=C:\Xilinx\Vivado\2022.1\bin\vivado.bat"
    goto tool_found
)

echo ERROR: Vivado was not found. >&2
echo        Run from its command prompt or set VIVADO to its full executable path. >&2
exit /b 1

:tool_found
if /i "%VIVADO_TOOL%"=="%SELF%" (
    echo ERROR: tool discovery resolved to this script, not Vivado. >&2
    echo        Set VIVADO to the full Vivado executable path. >&2
    exit /b 1
)
if not exist "%VIVADO_TOOL%" (
    echo ERROR: Vivado executable "%VIVADO_TOOL%" does not exist. >&2
    exit /b 1
)
if not exist "%VIVADO_DIR%\tcl\install_board.tcl" (
    echo ERROR: "%VIVADO_DIR%\tcl\install_board.tcl" does not exist. >&2
    exit /b 1
)
if not exist "%VIVADO_DIR%\tcl\block_design.tcl" (
    echo ERROR: "%VIVADO_DIR%\tcl\block_design.tcl" does not exist. >&2
    exit /b 1
)

call "%SCRIPT_DIR%build_support.bat" vivado --tool "%VIVADO_TOOL%" %*
exit /b %errorlevel%

:help
echo Usage: vivado.bat [width [build [bd]]]
echo Defaults: width 6, build A, full flow through write_bitstream.
echo   bd   stop after validate_bd_design
echo Set VIVADO to the full Vivado executable path if needed.
exit /b 0
