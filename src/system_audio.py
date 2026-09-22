#!/usr/bin/python3
"""
The computer's output volume -- for an SDR that cannot set its own.

SDR++'s rigctl server has no audio level, so the only way to make it quieter
is to turn the whole computer down. That is done here, with a different
command on each platform. It moves EVERY application's volume, not just the
SDR's, and the interface says so.

An SDR that has its own level -- Gqrx's AF gain -- uses that instead; see
SDR_Link. This module is the fallback.

Moved out of the SDR++ controller, which it never belonged to: it has nothing
to do with rigctl, and would be needed whichever SDR lacked a level.

Each call runs an external program on the interface thread -- osascript on
macOS takes long enough that a dragged slider would stutter -- so callers
should only set the value a control settles on. SDR_Link debounces for that.
"""
import subprocess
import sys

# Windows has no cheap way to READ the mute state, and its only mute key
# TOGGLES. So whether this application muted it is remembered here, and the
# key is pressed only when that changes -- otherwise mute() twice unmuted.
_windows_muted = False


def _run(command):
    """Runs a command quietly. True if it ran without error."""
    try:
        subprocess.run(command, shell=True, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def get_volume():
    """The output volume, 0 to 100 -- or 50 where it cannot be read."""
    try:
        if sys.platform == "darwin":
            out = subprocess.check_output(
                "osascript -e 'output volume of (get volume settings)'",
                shell=True).decode("utf-8").strip()
            if out.isdigit():
                return int(out)
        elif sys.platform.startswith("linux"):
            out = subprocess.check_output("amixer sget Master", shell=True).decode("utf-8")
            if "[" in out:
                return int(out.split("[")[1].split("%]")[0])
    except Exception:
        pass
    # Windows cannot report it through anything this simple.
    return 50


def set_volume(percent):
    """Sets the output volume, 0 to 100. True if the command ran."""
    percent = max(0, min(100, int(percent)))
    if sys.platform == "darwin":
        return _run(f"osascript -e 'set volume output volume {percent}'")
    if sys.platform.startswith("linux"):
        return _run(f"amixer -q sset Master {percent}%")
    if sys.platform == "win32":
        # Approximate: fifty presses down to zero, then up in 2% steps. The
        # best available without a native audio library.
        return _run('powershell -Command "$wsh = New-Object -ComObject WScript.Shell; '
                    f'[void]$wsh.SendKeys([char]174)*50; '
                    f'[void]$wsh.SendKeys([char]175)*{percent // 2}"')
    return False


def mute():
    """Mutes the output."""
    global _windows_muted
    if sys.platform == "darwin":
        return _run("osascript -e 'set volume with output muted'")
    if sys.platform.startswith("linux"):
        return _run("amixer -q sset Master mute")
    if sys.platform == "win32":
        if _windows_muted:
            return True
        if _run('powershell -Command "$wsh = New-Object -ComObject WScript.Shell; '
                '$wsh.SendKeys([char]173)"'):
            _windows_muted = True
            return True
    return False


def unmute():
    """
    Unmutes the output, at whatever level it was before.

    DOES NOT SET A LEVEL. The version in the SDR++ controller ended by setting
    the volume to 50% -- its restore_volume default -- so every unmute moved
    the computer's volume to half, whatever the slider said. Each platform
    already brings the old level back on unmuting.
    """
    global _windows_muted
    if sys.platform == "darwin":
        return _run("osascript -e 'set volume without output muted'")
    if sys.platform.startswith("linux"):
        return _run("amixer -q sset Master unmute")
    if sys.platform == "win32":
        if not _windows_muted:
            return True
        if _run('powershell -Command "$wsh = New-Object -ComObject WScript.Shell; '
                '$wsh.SendKeys([char]173)"'):
            _windows_muted = False
            return True
    return False
