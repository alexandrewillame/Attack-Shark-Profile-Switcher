<#
.SYNOPSIS
    One-shot install on a fresh machine: Python, the required packages, and
    start-at-boot.

.DESCRIPTION
    Finds a suitable Python (3.9+, 64-bit), offers to install one via winget if
    there isn't one, installs the packages from requirements.txt, verifies
    everything imports and that the mouse is reachable, enables start at boot by
    handing off to enable_start_at_boot.ps1, adds a desktop shortcut and a Start
    Menu shortcut, then starts the app.

    Safe to re-run - it skips whatever is already in place.

.PARAMETER Yes
    Don't prompt before installing Python.

.PARAMETER SkipPython
    Never install Python; fail with instructions instead.

.PARAMETER WithCapture
    Also install frida, needed only to re-capture the mouse protocol.

.PARAMETER NoStartAtBoot
    Install the dependencies but don't enable start at boot.

.PARAMETER NoDesktopShortcut
    Don't add the "Attack Shark Profile Switcher" desktop shortcut.

.PARAMETER NoStartMenuShortcut
    Don't add the "Attack Shark Profile Switcher" Start Menu shortcut.

.PARAMETER NoRun
    Don't start the app after installing. By default it starts automatically -
    if a copy is already running, the single-instance lock makes this a no-op.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1
    powershell -ExecutionPolicy Bypass -File install.ps1 -Yes -WithCapture
    powershell -ExecutionPolicy Bypass -File install.ps1 -NoRun
#>

param(
    [switch]$Yes,
    [switch]$SkipPython,
    [switch]$WithCapture,
    [switch]$NoStartAtBoot,
    [switch]$NoDesktopShortcut,
    [switch]$NoStartMenuShortcut,
    [switch]$NoRun
)

$ErrorActionPreference = 'Stop'
$here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

$MinMajor, $MinMinor = 3, 9
$WingetPackage = 'Python.Python.3.12'

function Write-Step { param([string]$Text) Write-Output ''; Write-Output "== $Text" }
function Write-Ok   { param([string]$Text) Write-Output "   [ok]   $Text" }
function Write-Bad  { param([string]$Text) Write-Output "   [fail] $Text" }

function Update-SessionPath {
    <# winget updates the registry, not this already-running shell. #>
    $parts = @(
        [Environment]::GetEnvironmentVariable('Path', 'Machine'),
        [Environment]::GetEnvironmentVariable('Path', 'User')
    ) | Where-Object { $_ }
    $env:Path = $parts -join ';'
}

function Test-PythonCandidate {
    <# Returns @{Path;Version;Bits} for a usable interpreter, else $null. #>
    param([string]$Exe, [string[]]$PreArgs = @())
    try {
        $probe = "import sys,struct;print(str(sys.version_info[0])+'.'+str(sys.version_info[1])+'.'+str(sys.version_info[2])+'|'+str(struct.calcsize('P')*8)+'|'+sys.executable)"
        $out = & $Exe @PreArgs -c $probe 2>$null
        if (-not $out) { return $null }
        $parts = ($out | Select-Object -Last 1).Trim() -split '\|'
        if ($parts.Count -lt 3) { return $null }
        $version = [version]$parts[0]
        if ($version.Major -lt $MinMajor -or
            ($version.Major -eq $MinMajor -and $version.Minor -lt $MinMinor)) { return $null }
        if ([int]$parts[1] -ne 64) { return $null }
        return @{ Path = $parts[2]; Version = $parts[0]; Bits = $parts[1] }
    } catch {
        return $null
    }
}

function New-AppShortcut {
    <#
    Creates (or overwrites in place) a .lnk in $FolderPath that runs
    run_now.bat with assets/logo.ico as its icon. Shared by the desktop and Start Menu
    steps below, which differ only in destination folder.
    #>
    param([string]$FolderPath)
    $runNow = Join-Path $here 'run_now.bat'
    if (-not (Test-Path $runNow)) {
        throw "run_now.bat not found in $here"
    }
    $iconPath = Join-Path $here 'assets' 'logo.ico'
    $shortcutPath = Join-Path $FolderPath 'Attack Shark Profile Switcher.lnk'
    $wshShell = New-Object -ComObject WScript.Shell
    $shortcut = $wshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $runNow
    # Without this, the shortcut's "start in" is $FolderPath, and run_now.bat's
    # relative "switcher.py" argument would resolve there instead of $here.
    $shortcut.WorkingDirectory = $here
    $shortcut.Description = 'Start the Attack Shark V8 profile switcher'
    if (Test-Path $iconPath) {
        $shortcut.IconLocation = "$iconPath,0"
    } else {
        Write-Warning "assets/logo.ico not found in $here - using the default .bat icon"
    }
    $shortcut.Save()
    return $shortcutPath
}

function Find-Python {
    foreach ($candidate in @(
            @{ Exe = 'python'; Pre = @() },
            @{ Exe = 'py';     Pre = @('-3') })) {
        if (Get-Command $candidate.Exe -ErrorAction SilentlyContinue) {
            $found = Test-PythonCandidate -Exe $candidate.Exe -PreArgs $candidate.Pre
            if ($found) { return $found }
        }
    }
    # winget's per-user install may not be on PATH yet in this shell.
    $globs = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe"
    )
    foreach ($glob in $globs) {
        Get-ChildItem $glob -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | ForEach-Object {
                $found = Test-PythonCandidate -Exe $_.FullName
                if ($found) { return $found }
            }
    }
    return $null
}

Write-Output 'Attack Shark V8 profile switcher - install'
Write-Output '=========================================='

# --- 1. Python --------------------------------------------------------------

Write-Step "Python $MinMajor.$MinMinor+ (64-bit)"
$python = Find-Python

if (-not $python) {
    Write-Bad 'no suitable Python found'
    if ($SkipPython) {
        throw "Install Python $MinMajor.$MinMinor+ (64-bit) from https://python.org and re-run."
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is unavailable. Install Python $MinMajor.$MinMinor+ (64-bit) from https://python.org (tick 'Add python.exe to PATH' and 'tcl/tk and IDLE'), then re-run this script."
    }
    if (-not $Yes) {
        $reply = Read-Host "   Install $WingetPackage with winget now? [y/N]"
        if ($reply -notmatch '^(y|yes)$') {
            throw 'Cancelled. Install Python manually and re-run.'
        }
    }
    Write-Output "   installing $WingetPackage ..."
    winget install --id $WingetPackage -e --source winget `
        --accept-package-agreements --accept-source-agreements
    Update-SessionPath
    $python = Find-Python
    if (-not $python) {
        throw 'Python was installed but is not visible yet. Close this window, open a new one, and re-run this script.'
    }
}

$py = $python.Path
Write-Ok "$($python.Version) $($python.Bits)-bit  ->  $py"

# --- 2. tkinter -------------------------------------------------------------

Write-Step 'tkinter (needed for the popup)'
& $py -c 'import tkinter' 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Ok 'available'
} else {
    Write-Bad 'missing'
    throw "This Python has no tkinter. pip cannot install it - re-run the Python installer, choose Modify, and tick 'tcl/tk and IDLE'."
}

# --- 3. packages ------------------------------------------------------------

Write-Step 'Packages from requirements.txt'
$requirements = Join-Path $here 'requirements.txt'
if (-not (Test-Path $requirements)) { throw "requirements.txt not found in $here" }

& $py -m pip install --disable-pip-version-check -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'pip install failed - see the output above.' }
Write-Ok 'installed'

if ($WithCapture) {
    Write-Step 'frida (protocol capture tooling)'
    # frida 17+ imports typing.NotRequired, which needs Python 3.11+.
    $version = [version]$python.Version
    $spec = if ($version.Major -eq 3 -and $version.Minor -lt 11) { 'frida<17' } else { 'frida' }
    Write-Output "   installing $spec ..."
    & $py -m pip install --disable-pip-version-check $spec
    if ($LASTEXITCODE -ne 0) { Write-Bad 'frida install failed (optional - the switcher still works)' }
    else { Write-Ok $spec }
}

# --- 4. verify --------------------------------------------------------------

Write-Step 'Verifying imports'
& $py -c 'import psutil,pystray,PIL,tkinter,ctypes;print(1)' > $null 2>&1
if ($LASTEXITCODE -eq 0) { Write-Ok 'psutil, pystray, Pillow, tkinter' }
else { throw 'Imports failed after installing. See the pip output above.' }

Write-Step 'Looking for the mouse'
$listing = & $py (Join-Path $here 'sharkctl.py') list 2>&1
if ($LASTEXITCODE -eq 0 -and ($listing -match 'config channel')) {
    Write-Ok 'V8 found, config channel identified'
} elseif ($listing -match 'No VID_') {
    Write-Bad 'mouse not detected - plug in the 8K dongle (setup is otherwise complete)'
} else {
    Write-Bad 'could not identify the config channel; run "python sharkctl.py list" for detail'
}

# --- 5. start at boot -------------------------------------------------------

$bootEnabled = $false
if ($NoStartAtBoot) {
    Write-Step 'Start at boot'
    Write-Output '   skipped (-NoStartAtBoot)'
} else {
    Write-Step 'Start at boot'
    $enable = Join-Path $here 'enable_start_at_boot.ps1'
    if (-not (Test-Path $enable)) {
        Write-Bad "enable_start_at_boot.ps1 not found in $here"
    } else {
        try {
            # Pass the interpreter we just validated: after a winget install it
            # may not be on PATH, and the shortcut must not point at a stale one.
            & $enable -PythonPath $py |
                ForEach-Object { if ($_) { "   $_" } else { '' } }
            $bootEnabled = $true
        } catch {
            # A dependency install that otherwise succeeded shouldn't be
            # reported as a failure just because the shortcut couldn't be made.
            Write-Bad "could not enable start at boot: $_"
            Write-Output '   run enable_start_at_boot.bat by hand to retry'
        }
    }
}

# --- 6. desktop shortcut ------------------------------------------------------

$shortcutCreated = $false
if ($NoDesktopShortcut) {
    Write-Step 'Desktop shortcut'
    Write-Output '   skipped (-NoDesktopShortcut)'
} else {
    Write-Step 'Desktop shortcut'
    try {
        $path = New-AppShortcut -FolderPath ([Environment]::GetFolderPath('Desktop'))
        Write-Ok $path
        $shortcutCreated = $true
    } catch {
        Write-Bad "could not create the desktop shortcut: $_"
    }
}

# --- 7. start menu shortcut ---------------------------------------------------

$startMenuShortcutCreated = $false
if ($NoStartMenuShortcut) {
    Write-Step 'Start Menu shortcut'
    Write-Output '   skipped (-NoStartMenuShortcut)'
} else {
    Write-Step 'Start Menu shortcut'
    try {
        # Per-user Programs folder - no admin rights needed, same reasoning as
        # using the Startup folder instead of Task Scheduler for start-at-boot.
        $path = New-AppShortcut -FolderPath ([Environment]::GetFolderPath('Programs'))
        Write-Ok $path
        $startMenuShortcutCreated = $true
    } catch {
        Write-Bad "could not create the Start Menu shortcut: $_"
    }
}

# --- 8. run now --------------------------------------------------------------

$appStarted = $false
if ($NoRun) {
    Write-Step 'Run now'
    Write-Output '   skipped (-NoRun)'
} else {
    Write-Step 'Run now'
    $pythonw = Join-Path (Split-Path -Parent $py) 'pythonw.exe'
    if (-not (Test-Path $pythonw)) { $pythonw = $py }
    $switcherScript = Join-Path $here 'switcher.py'
    try {
        # If a copy is already running (e.g. re-running this installer), the
        # single-instance lock in switcher.py makes this new one exit quietly -
        # no need to check for that here.
        Start-Process -FilePath $pythonw -ArgumentList ('"{0}"' -f $switcherScript) `
            -WorkingDirectory $here
        Write-Ok 'started - look for the tray icon'
        $appStarted = $true
    } catch {
        Write-Bad "could not start it: $_"
        Write-Output '   run run_now.bat by hand to retry'
    }
}

# --- next steps -------------------------------------------------------------

Write-Output ''
Write-Output 'Install complete. Next:'
Write-Output ''
Write-Output '  1. In the ATTACK SHARK MOUSE HUB, set up Profile 1 (desktop) and'
Write-Output '     Profile 2 (gaming), then close the Hub.'
Write-Output '  2. Add your games - from the tray menu (Detect games / Edit games'
Write-Output '     list), or:'
Write-Output "       $py detect_games.py --write"
Write-Output '     then review config.json.'
Write-Output '  3. Check it works:'
Write-Output "       $py sharkctl.py 2     (then 1 to go back)"
Write-Output ''
if ($appStarted) {
    Write-Output '  It is running now - look for the tray icon.'
} else {
    Write-Output '  4. Start it now, without waiting for a login:'
    if ($shortcutCreated) {
        Write-Output '       double-click "Attack Shark Profile Switcher" on the desktop'
    } elseif ($startMenuShortcutCreated) {
        Write-Output '       find "Attack Shark Profile Switcher" in the Start Menu'
    } else {
        Write-Output '       run_now.bat'
    }
}
if ($bootEnabled) {
    Write-Output '  It will start automatically at every login.'
    Write-Output '  To turn that off later: disable_start_at_boot.bat'
} else {
    Write-Output '  To start it at login:  enable_start_at_boot.bat'
}
if ($shortcutCreated -and $startMenuShortcutCreated) {
    Write-Output '  A "Attack Shark Profile Switcher" shortcut is on the desktop and in the Start Menu.'
} elseif ($shortcutCreated) {
    Write-Output '  A "Attack Shark Profile Switcher" shortcut is on the desktop.'
} elseif ($startMenuShortcutCreated) {
    Write-Output '  A "Attack Shark Profile Switcher" shortcut is in the Start Menu.'
}
