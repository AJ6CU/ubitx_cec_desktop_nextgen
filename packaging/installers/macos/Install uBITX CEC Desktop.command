#!/bin/zsh
# Installs uBITX CEC Desktop for this user, from the wheel next to this script.
#
# Double-click it. If macOS says it cannot be opened (it is not signed): open
# Terminal, type  zsh  and a space, drag this file into the window, press Return.
#
# Puts the program in ~/Library/Application Support/uBITX CEC Desktop (its own
# Python environment; nothing goes into Python itself) and the app
# "uBITX CEC Desktop" in your Applications folder (~/Applications). Run it
# again to upgrade or repair. Needs no administrator password.
setopt nullglob
APP="uBITX CEC Desktop"
HERE="${0:A:h}"
HOME_DIR="$HOME/Library/Application Support/$APP"
VENV="$HOME_DIR/venv"
BUNDLE="$HOME/Applications/$APP.app"

say()  { print; print -- "$*"; }
fail() { print; print -- "NOT INSTALLED: $*"; print; read -k1 "?Press a key to close."; exit 1; }

# -- the wheel --------------------------------------------------------------
wheels=("$HERE"/ubitx_cec_desktop-*.whl)
(( ${#wheels} == 1 )) || fail "expected one ubitx_cec_desktop-*.whl next to this script, found ${#wheels}."
WHEEL="${wheels[1]}"
say "Installing $APP from ${WHEEL:t}"

# -- a Python that can run it ----------------------------------------------
# 3.10 or newer with a working Tk. python.org's installer has Tk; Homebrew's
# Python needs "brew install python-tk@3.x" for it. Apple's own /usr/bin/python3
# (3.9) is too old. The newest that works is taken.
python_ok() { "$1" -c "import sys, tkinter, venv; tkinter.Tcl(); sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null }
PY=""
for v in 3.14 3.13 3.12 3.11 3.10; do
    for p in "/Library/Frameworks/Python.framework/Versions/$v/bin/python$v" \
             "/opt/homebrew/bin/python$v" "/usr/local/bin/python$v"; do
        if [[ -x "$p" ]] && python_ok "$p"; then PY="$p"; break 2; fi
    done
done
if [[ -z "$PY" ]] && p="$(command -v python3)" && python_ok "$p"; then PY="$p"; fi
if [[ -z "$PY" ]]; then
    say "No Python 3.10 or newer with Tk was found.
Install Python from python.org (the page opens now) -- its installer includes Tk --
then run this again. (With Homebrew instead: brew install python@3.13 python-tk@3.13)"
    open "https://www.python.org/downloads/macos/"
    fail "Python with Tk needed."
fi
say "Using $PY ($("$PY" -c 'import sys; print(sys.version.split()[0])'))"

# -- its own environment ---------------------------------------------------
# Remade if the Python it was made from has gone (Python upgraded or removed).
if [[ -x "$VENV/bin/python" ]] && ! "$VENV/bin/python" -c "import sys" 2>/dev/null; then
    rm -rf "$VENV"
fi
if [[ ! -x "$VENV/bin/python" ]]; then
    mkdir -p "$HOME_DIR"
    "$PY" -m venv "$VENV" || fail "could not create $VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip || say "(pip itself could not be upgraded; carrying on)"
say "Installing the program and what it needs from PyPI -- a minute or two the first time"
"$VENV/bin/python" -m pip install --quiet --upgrade "$WHEEL" || fail "pip could not install it (see the message above; is the internet reachable?)"
# The same version again (a rebuilt wheel) is not picked up by --upgrade.
"$VENV/bin/python" -m pip install --quiet --force-reinstall --no-deps "$WHEEL" || fail "pip could not reinstall the wheel"

# -- how to start it: a small app in ~/Applications -------------------------
# Made here, on this Mac, so macOS does not treat it as downloaded. It starts
# the program and writes its messages to ~/Library/Logs/uBITX CEC Desktop.log.
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
# The program's own icon, from the installed package.
PKG="$("$VENV/bin/python" -c 'import os, ubitx_cec_app; print(os.path.dirname(ubitx_cec_app.__file__))')"
cp "$PKG/icons/icon.icns" "$BUNDLE/Contents/Resources/AppIcon.icns" 2>/dev/null
cat > "$BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$APP</string>
  <key>CFBundleDisplayName</key><string>$APP</string>
  <key>CFBundleIdentifier</key><string>net.aj6cu.ubitx-cec-desktop</string>
  <key>CFBundleExecutable</key><string>start</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
cat > "$BUNDLE/Contents/MacOS/start" <<START
#!/bin/zsh
exec "$VENV/bin/python" -m ubitx_cec_app >> "\$HOME/Library/Logs/$APP.log" 2>&1
START
chmod +x "$BUNDLE/Contents/MacOS/start"
touch "$BUNDLE"     # so Finder shows the new icon rather than a cached one

say "DONE. $APP is installed.
  Start it from Applications (in your home folder), Launchpad or Spotlight.
  Program:  $HOME_DIR
  Messages: ~/Library/Logs/$APP.log
  Settings and logbook stay in ~/.ubitx_cec_desktop (kept by the uninstaller)."
print; read -k1 "?Press a key to close."
exit 0
