# Installs uBITX CEC Desktop for this user, from the wheel next to this script.
# Started by "Install uBITX CEC Desktop.bat" -- double-click that, not this.
#
# Puts the program in %LOCALAPPDATA%\uBITX CEC Desktop (its own Python
# environment; nothing goes into Python itself) and a shortcut in the Start
# menu and on the Desktop. Run it again to upgrade or repair. Needs no
# administrator rights. %LOCALAPPDATA% rather than Documents: Documents is often
# synced by OneDrive, which copes badly with thousands of small program files.

# "Continue", and every step's exit code checked by hand: in Windows PowerShell
# 5.1, "Stop" turns any line a program writes to stderr (a pip notice, a Python
# that is not the one) into an error that ends the script.
$ErrorActionPreference = "Continue"
$App   = "uBITX CEC Desktop"
$Here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Home_ = Join-Path $env:LOCALAPPDATA $App
$Venv  = Join-Path $Home_ "venv"

function Say($text)  { Write-Host ""; Write-Host $text }
function Fail($text) { Write-Host ""; Write-Host "NOT INSTALLED: $text" -ForegroundColor Red; exit 1 }

# -- the wheel --------------------------------------------------------------
$wheels = @(Get-ChildItem -Path $Here -Filter "ubitx_cec_desktop-*.whl")
if ($wheels.Count -ne 1) { Fail "expected one ubitx_cec_desktop-*.whl next to this script, found $($wheels.Count)." }
$Wheel = $wheels[0].FullName
Say "Installing $App from $($wheels[0].Name)"

# -- a Python that can run it ----------------------------------------------
# 3.10 or newer with Tk. The python.org installer includes Tk. The "python"
# that only opens the Microsoft Store (WindowsApps) is skipped; "py" is the
# python.org launcher and finds every version installed.
$check = "import sys, tkinter, venv; tkinter.Tcl(); sys.exit(0 if sys.version_info >= (3, 10) else 1)"
$candidates = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in "3.14", "3.13", "3.12", "3.11", "3.10", "3") { $candidates += ,@("py", "-$v") }
}
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python -and $python.Source -notmatch "WindowsApps") { $candidates += ,@($python.Source) }

$Py = $null
foreach ($c in $candidates) {
    $exe = $c[0]; $pre = @($c | Select-Object -Skip 1)
    try {
        & $exe @pre -c $check 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $Py = (& $exe @pre -c "import sys; print(sys.executable)").Trim()
            break
        }
    } catch { }
}
if (-not $Py) {
    Say "No Python 3.10 or newer with Tk was found."
    Say "Install Python from python.org (the page opens now). In its installer, tick
'Add python.exe to PATH', keep 'tcl/tk and IDLE' ticked, then run this installer again."
    Start-Process "https://www.python.org/downloads/windows/"
    exit 1
}
$ver = (& $Py -c "import sys; print(sys.version.split()[0])").Trim()
Say "Using $Py ($ver)"

# -- its own environment ---------------------------------------------------
$VPy  = Join-Path $Venv "Scripts\python.exe"
$VPyw = Join-Path $Venv "Scripts\pythonw.exe"
# Remade if the Python it was made from has gone (Python was uninstalled or upgraded).
if (Test-Path $VPy) {
    & $VPy -c "import sys" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { Remove-Item -Recurse -Force $Venv }
}
if (-not (Test-Path $VPy)) {
    New-Item -ItemType Directory -Force -Path $Home_ | Out-Null
    & $Py -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail "could not create $Venv" }
}
& $VPy -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { Say "(pip itself could not be upgraded; carrying on)" }
Say "Installing the program and what it needs from PyPI -- a minute or two the first time"
& $VPy -m pip install --quiet --upgrade $Wheel
if ($LASTEXITCODE -ne 0) { Fail "pip could not install it (see the message above; is the internet reachable?)" }
# The same version again (a rebuilt wheel) is not picked up by --upgrade.
& $VPy -m pip install --quiet --force-reinstall --no-deps $Wheel
if ($LASTEXITCODE -ne 0) { Fail "pip could not reinstall the wheel" }

# -- how to start it ---------------------------------------------------------
# pythonw: no black console window behind the app. For a window that shows
# the app's messages (when something goes wrong), "Start with messages.bat"
# in the program folder.
$shell = New-Object -ComObject WScript.Shell
$places = @(
    (Join-Path ([Environment]::GetFolderPath("Programs")) "$App.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "$App.lnk")
)
foreach ($lnk in $places) {
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $VPyw
    $s.Arguments = "-m ubitx_cec_app"
    $s.WorkingDirectory = $env:USERPROFILE
    $s.Description = "Control a uBITX (KD8CEC firmware) alongside an SDR"
    $s.Save()
}
$msgs = Join-Path $Home_ "Start with messages.bat"
Set-Content -Path $msgs -Encoding ASCII -Value @"
@echo off
rem Starts uBITX CEC Desktop with its messages shown here -- for when something goes wrong.
"$VPy" -m ubitx_cec_app
pause
"@

Say "DONE. $App is installed.
  Start it from the Start menu or the Desktop shortcut.
  Program:  $Home_
  Settings and logbook stay in $env:USERPROFILE\.ubitx_cec_desktop (kept by the uninstaller).
  The radio's COM port: Device Manager > Ports (COM & LPT), then the app's Setup page."
exit 0
