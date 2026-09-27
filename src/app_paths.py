#!/usr/bin/python3
"""
Where this application keeps its files on the operator's computer.

ONE FOLDER: ~/.ubitx_cec_desktop/, the same on every platform (the
operator's choice, 2026-09-27). The settings, the channel sets, the window's
size and place, the pinned pop-ups, and the operator's own additions to the
SDR programs and controls files all live in it, so the station can be backed
up, copied to another machine or cleared out by taking one folder. Every
module asks here for its file by name -- see config_path -- so the next thing
that needs a file does not invent a rule of its own.

Files shipped WITH the application -- sdr_programs.json, sdr_controls.json,
the theme -- are not here: they sit beside the code, and the operator's own
files in this folder are merged over them.
"""
import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".ubitx_cec_desktop")

_made = False


def config_path(name):
    """
    The full path of one of the application's own files, in CONFIG_DIR --
    the folder made the first time this is asked.
    """
    global _made
    if not _made:
        _made = True
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
        except OSError as err:
            print(f"[app] could not make {shown(CONFIG_DIR)}: {err}")
    return os.path.join(CONFIG_DIR, name)


def shown(path):
    """A path as the operator would write it: ~ for the home folder."""
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path
