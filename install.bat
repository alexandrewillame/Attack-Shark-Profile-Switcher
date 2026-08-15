@echo off
REM Double-click to install everything this tool needs, enable start at boot,
REM and start it running now.
REM Pass -WithCapture to also install the protocol-capture tooling,
REM -Yes to skip the confirmation before installing Python,
REM -NoStartAtBoot to skip enabling start at boot,
REM or -NoRun to skip starting it now.
powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
