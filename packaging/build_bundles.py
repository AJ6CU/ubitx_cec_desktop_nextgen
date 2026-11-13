#!/usr/bin/env python3
"""
Makes the three download bundles from the wheel build_wheel.py made:

    python3 packaging/build_bundles.py

    dist/uBITX-CEC-Desktop-<version>-Windows.zip
    dist/uBITX-CEC-Desktop-<version>-macOS.zip
    dist/uBITX-CEC-Desktop-<version>-Linux.tar.gz

Each holds one folder: the wheel, that platform's installer and uninstaller
(from packaging/installers/), and a READ ME. The installers find the wheel by
its name pattern, so no version is written into them -- a new release is
build_wheel.py, then this.

Run build_wheel.py first; this stops if dist/ has no wheel for the version in
globalvars.APPVERSION.
"""
import io
import os
import re
import sys
import tarfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")
INSTALLERS = os.path.join(HERE, "installers")

README = {
    "Windows": """\
uBITX CEC Desktop {version} for Windows
=======================================

1. Install Python from https://www.python.org/downloads/windows/ if you do not
   have it (3.10 or newer). In its installer tick "Add python.exe to PATH".
2. Unzip this folder anywhere (it is not needed after installing).
3. Double-click "Install uBITX CEC Desktop.bat".
   If Windows warns about a file from the internet, choose "Run" (or "More
   info" then "Run anyway").
4. Start the program from the Start menu or the Desktop shortcut.

To upgrade: run the installer from a newer version's folder.
To remove: "Uninstall uBITX CEC Desktop.bat". Your settings and logbook in
%USERPROFILE%\\.ubitx_cec_desktop are kept.
If the program does not start: "Start with messages.bat" in
%LOCALAPPDATA%\\uBITX CEC Desktop shows what went wrong.
""",
    "macOS": """\
uBITX CEC Desktop {version} for macOS
=====================================

1. Install Python from https://www.python.org/downloads/macos/ if you do not
   have it (3.10 or newer; python.org's installer includes Tk).
2. Double-click "Install uBITX CEC Desktop.command".
   These scripts are not signed, so macOS may refuse to open them. Then open
   Terminal, type  zsh  and a space, drag the .command file into the Terminal
   window, and press Return.
3. Start the program from Applications (in your home folder), Launchpad or
   Spotlight: "uBITX CEC Desktop".

To upgrade: run the installer from a newer version's folder.
To remove: "Uninstall uBITX CEC Desktop.command". Your settings and logbook
in ~/.ubitx_cec_desktop are kept.
The program's messages: ~/Library/Logs/uBITX CEC Desktop.log
""",
    "Linux": """\
uBITX CEC Desktop {version} for Linux (and Raspberry Pi OS)
===========================================================

1. Unpack this folder:   tar xzf uBITX-CEC-Desktop-{version}-Linux.tar.gz
2. Run the installer:    bash uBITX-CEC-Desktop-{version}/install.sh
   It checks for Python's Tk and venv packages and the 'dialout' group for
   the radio's serial port, and offers to add what is missing (with sudo).
3. Start the program from the application menu (Internet / Ham Radio), or
   type:  ubitx-cec-desktop

To upgrade: run install.sh from a newer version's folder.
To remove: bash uninstall.sh. Your settings and logbook in ~/.ubitx_cec_desktop
are kept.
""",
}

FILES = {
    "Windows": ["Install uBITX CEC Desktop.bat", "install.ps1",
                "Uninstall uBITX CEC Desktop.bat", "uninstall.ps1"],
    "macOS": ["Install uBITX CEC Desktop.command",
              "Uninstall uBITX CEC Desktop.command"],
    "Linux": ["install.sh", "uninstall.sh"],
}
SOURCE = {"Windows": "windows", "macOS": "macos", "Linux": "linux"}


def version():
    with open(os.path.join(ROOT, "src", "globalvars.py")) as f:
        m = re.search(r'^APPVERSION\s*=\s*["\']([^"\']+)', f.read(), re.M)
    if not m:
        sys.exit("no APPVERSION in src/globalvars.py")
    return m.group(1)


def entries(platform, ver, wheel):
    """(name in the archive, bytes, executable) for one platform's folder."""
    top = f"uBITX-CEC-Desktop-{ver}"
    out = [(f"{top}/{os.path.basename(wheel)}", open(wheel, "rb").read(), False)]
    for name in FILES[platform]:
        with open(os.path.join(INSTALLERS, SOURCE[platform], name), "rb") as f:
            data = f.read()
        if platform == "Windows" and name.endswith(".bat"):
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        out.append((f"{top}/{name}", data, name.endswith((".sh", ".command"))))
    text = README[platform].format(version=ver)
    if platform == "Windows":
        text = text.replace("\n", "\r\n")
    out.append((f"{top}/READ ME.txt", text.encode(), False))
    return out


def write_zip(path, items):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data, exe in items:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3                      # unix, so the mode is used
            info.external_attr = (0o100755 if exe else 0o100644) << 16
            z.writestr(info, data)


def write_tgz(path, items):
    with tarfile.open(path, "w:gz") as t:
        for name, data, exe in items:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if exe else 0o644
            info.mtime = 0
            t.addfile(info, io.BytesIO(data))


def main():
    ver = version()
    wheel = os.path.join(DIST, f"ubitx_cec_desktop-{ver}-py3-none-any.whl")
    if not os.path.exists(wheel):
        sys.exit(f"no {os.path.relpath(wheel, ROOT)} -- run packaging/build_wheel.py first")
    for platform in ("Windows", "macOS", "Linux"):
        items = entries(platform, ver, wheel)
        if platform == "Linux":
            out = os.path.join(DIST, f"uBITX-CEC-Desktop-{ver}-Linux.tar.gz")
            write_tgz(out, items)
        else:
            out = os.path.join(DIST, f"uBITX-CEC-Desktop-{ver}-{platform}.zip")
            write_zip(out, items)
        print(f"  {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
