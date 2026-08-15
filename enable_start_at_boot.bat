@echo off
REM Double-click to make the profile switcher start at every login.
REM install.bat already does this, so you only need it to re-enable after
REM disable_start_at_boot.bat, which is the thorough way to turn it back off.
powershell -ExecutionPolicy Bypass -File "%~dp0enable_start_at_boot.ps1" %*
echo.
pause
