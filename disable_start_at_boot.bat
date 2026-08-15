@echo off
REM Double-click to stop the profile switcher from starting at boot.
REM Pass -StopNow to also stop the instance that is running right now,
REM or -DryRun to see what would be removed without changing anything.
powershell -ExecutionPolicy Bypass -File "%~dp0disable_start_at_boot.ps1" %*
echo.
pause
