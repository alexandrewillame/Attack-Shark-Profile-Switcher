<#
.SYNOPSIS
    Stop the profile switcher from starting at boot.

.DESCRIPTION
    Removes every autostart entry that points at this tool. Checks the places a
    startup entry can hide, not just the one the installer uses:

      - the per-user and All Users Startup folders
      - the Run / RunOnce registry keys (HKCU and HKLM, including WOW6432Node)
      - Scheduled Tasks

    Entries are matched strictly on "switcher.py" or this tool's own directory.
    That precision matters: the Attack Shark Hub registers its own autostart
    entry, and a looser match on "shark" would disable the vendor software too.

    This removes only the autostart entries. The tool's files, your config.json
    and your mouse profiles are all left alone.

.PARAMETER StopNow
    Also stop the instance that is currently running and put the mouse back on
    its default profile.

.PARAMETER DryRun
    Report what would be removed without changing anything.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File disable_start_at_boot.ps1
    powershell -ExecutionPolicy Bypass -File disable_start_at_boot.ps1 -StopNow
    powershell -ExecutionPolicy Bypass -File disable_start_at_boot.ps1 -DryRun
#>

param(
    [switch]$StopNow,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$script = Join-Path $here 'switcher.py'
$removed = 0
$found = 0

function Test-IsOurs {
    <# Strict match: only entries naming switcher.py or this tool's folder. #>
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $false }
    return ($Text -like '*switcher.py*') -or ($Text -like "*$here*")
}

function Write-Action {
    param([string]$What, [string]$Detail)
    $script:found++
    if ($DryRun) {
        Write-Output "  [would remove] $What"
    } else {
        Write-Output "  [removed]      $What"
        $script:removed++
    }
    if ($Detail) { Write-Output "                 $Detail" }
}

if ($DryRun) { Write-Output 'DRY RUN - nothing will be changed.'; Write-Output '' }

# --- 1. Startup folder shortcuts -------------------------------------------

Write-Output 'Startup folders:'
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @([Environment]::GetFolderPath('Startup'),
                      [Environment]::GetFolderPath('CommonStartup'))) {
    if (-not (Test-Path $folder)) { continue }
    Get-ChildItem -LiteralPath $folder -Filter *.lnk -ErrorAction SilentlyContinue |
        ForEach-Object {
            $lnk = $_
            try { $sc = $shell.CreateShortcut($lnk.FullName) } catch { return }
            $blob = "$($sc.TargetPath) $($sc.Arguments) $($sc.WorkingDirectory)"
            if (-not (Test-IsOurs $blob)) { return }

            Write-Action $lnk.FullName $sc.Arguments
            if (-not $DryRun) {
                try {
                    Remove-Item -LiteralPath $lnk.FullName -Force
                } catch {
                    $script:removed--
                    Write-Warning "Could not remove $($lnk.FullName): $_"
                    if ($lnk.FullName -like "*$([Environment]::GetFolderPath('CommonStartup'))*") {
                        Write-Warning 'This is an All Users entry - re-run as Administrator.'
                    }
                }
            }
        }
}

# --- 2. Run / RunOnce registry keys ----------------------------------------

Write-Output 'Registry Run keys:'
$runKeys = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'
)
foreach ($key in $runKeys) {
    if (-not (Test-Path $key)) { continue }
    $props = Get-ItemProperty -Path $key
    $props.PSObject.Properties |
        Where-Object { $_.Name -notlike 'PS*' } |
        ForEach-Object {
            if (-not (Test-IsOurs ([string]$_.Value))) { return }
            Write-Action "$key :: $($_.Name)" ([string]$_.Value)
            if (-not $DryRun) {
                try {
                    Remove-ItemProperty -Path $key -Name $_.Name -Force
                } catch {
                    $script:removed--
                    Write-Warning "Could not remove $key :: $($_.Name): $_"
                    if ($key -like 'HKLM:*') {
                        Write-Warning 'HKLM needs Administrator - re-run elevated.'
                    }
                }
            }
        }
}

# --- 3. Scheduled tasks -----------------------------------------------------

Write-Output 'Scheduled tasks:'
try {
    Get-ScheduledTask -ErrorAction Stop | ForEach-Object {
        $task = $_
        $blob = ($task.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join ' '
        if (-not (Test-IsOurs $blob)) { return }
        Write-Action "$($task.TaskPath)$($task.TaskName)" $blob
        if (-not $DryRun) {
            try {
                Unregister-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -Confirm:$false
            } catch {
                $script:removed--
                Write-Warning "Could not remove task $($task.TaskName): $_"
            }
        }
    }
} catch {
    Write-Output '  (could not query Scheduled Tasks - skipped)'
}

# --- summary ----------------------------------------------------------------

Write-Output ''
if ($found -eq 0) {
    Write-Output 'No autostart entries found - it was not set to start at boot.'
} elseif ($DryRun) {
    Write-Output "$found autostart entr$(if ($found -eq 1) {'y'} else {'ies'}) would be removed."
} else {
    Write-Output "Removed $removed of $found autostart entr$(if ($found -eq 1) {'y'} else {'ies'})."
    Write-Output 'It will no longer start at login.'
}

# --- optionally stop the running instance -----------------------------------

$running = @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
             Where-Object { Test-IsOurs $_.CommandLine })

if ($running.Count -eq 0) {
    Write-Output 'It is not running right now.'
    return
}

if (-not $StopNow) {
    Write-Output ''
    Write-Output "It is still running ($($running.Count) process). It will keep running"
    Write-Output 'until you quit it from the tray icon, or re-run this with -StopNow.'
    return
}

if ($DryRun) {
    Write-Output "[would stop] $($running.Count) running process"
    return
}

# Put the mouse back before killing the process: a terminated process never runs
# its own revert-on-exit, which would otherwise strand a game profile.
try {
    $cfgPath = Join-Path $here 'config.json'
    $default = 1
    if (Test-Path $cfgPath) {
        $default = (Get-Content $cfgPath -Raw | ConvertFrom-Json).default_profile
    }
    & python (Join-Path $here 'sharkctl.py') $default
} catch {
    Write-Warning "Could not restore the default profile: $_"
}

foreach ($proc in $running) {
    try {
        Stop-Process -Id $proc.ProcessId -Force
        Write-Output "Stopped process $($proc.ProcessId)."
    } catch {
        Write-Warning "Could not stop process $($proc.ProcessId): $_"
    }
}
