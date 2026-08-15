<#
.SYNOPSIS
    Run the profile switcher automatically at login.

.DESCRIPTION
    Creates a shortcut in the current user's Startup folder that launches
    switcher.py with pythonw.exe (no console window). The Startup folder is used
    rather than Task Scheduler because it needs no administrator rights.

.PARAMETER PythonPath
    The interpreter to launch it with. Defaults to whatever `python` resolves to
    on PATH. install.ps1 passes the interpreter it just validated, which matters
    when Python was installed as part of that run and isn't on PATH yet.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File enable_start_at_boot.ps1
    powershell -ExecutionPolicy Bypass -File enable_start_at_boot.ps1 -Uninstall
#>

param(
    [switch]$Uninstall,
    [string]$PythonPath
)

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $here 'switcher.py'
$startup = [Environment]::GetFolderPath('Startup')
$linkPath = Join-Path $startup 'Attack Shark Profile Switcher.lnk'

if ($Uninstall) {
    if (Test-Path $linkPath) {
        Remove-Item $linkPath -Force
        Write-Output "Removed $linkPath"
    } else {
        Write-Output 'Not installed - nothing to remove.'
    }
    return
}

if (-not (Test-Path $script)) {
    throw "switcher.py not found next to this script ($script)"
}

$python = if ($PythonPath) { $PythonPath }
          else { (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $python -or -not (Test-Path $python)) {
    throw 'No Python found. Run install.bat first, or pass -PythonPath.'
}

# pythonw.exe runs without a console window; fall back to python.exe if absent.
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) {
    Write-Warning 'pythonw.exe not found; using python.exe (a console window will appear).'
    $pythonw = $python
}

$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($linkPath)
$link.TargetPath = $pythonw
$link.Arguments = '"{0}"' -f $script
$link.WorkingDirectory = $here
$link.WindowStyle = 7            # minimized
$link.Description = 'Switches the Attack Shark V8 mouse profile when a game runs'
$link.Save()

Write-Output "Installed: $linkPath"
Write-Output "  target : $pythonw"
Write-Output "  script : $script"
Write-Output ''
Write-Output 'It will start at your next login. To start it now:'
Write-Output ('  Start-Process "{0}" -ArgumentList "{1}"' -f $pythonw, $script)
