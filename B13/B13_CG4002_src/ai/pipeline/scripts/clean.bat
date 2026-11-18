@echo off
rem Checked cleanup shared with clean.sh; never reports a failed deletion as success.
call "%~dp0build_support.bat" clean %*
exit /b %errorlevel%
