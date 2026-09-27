#!/usr/bin/python3
"""
What this application knows about each SDR program, read from a file.

WHY A FILE. None of this is logic: a program's port, where it is installed,
what it calls its modes, what it cannot do. It is a description of somebody
else's software, it goes stale when that software changes, and adding a
program should not mean editing Python. So it lives in sdr_programs.json,
beside this module, and an operator's own entries live in

    ~/.ubitx_cec_desktop/sdr_programs.json

MERGED ENTRY BY ENTRY, not file over file. The theme file works the other way
-- the first one found wins completely -- and Theming.md explains what that
costs: a copy made last year hides every block added since. Here, a user
entry overrides or adds to the shipped ones, and programs added later still
arrive.

ONE ENTRY PER WAY OF DRIVING A PROGRAM. A program with two interfaces gets
two entries, same install paths, different protocols. (SDRangel had two, REST
and rigctl; the rigctl one was removed -- see RETIRED below.) `protocol`
NAMES the transport that drives it -- it does not describe it. How a protocol works is code, because SDRangel's
REST is not a variation on rigctl: it addresses device sets and channels by
index, needs a discovery step to find the right demodulator, and can push
changes rather than be polled. A file that tried to express that would be a
programming language with no debugger.

A MALFORMED ENTRY IS REFUSED, LOUDLY, AND BY NAME -- the same argument the
theme file makes for raising on a missing key. The rest of the file still
loads: one bad entry of somebody's own should not take the working programs
with it.
"""
import json
import os
import sys

from app_paths import config_path

# What an SDR can be asked to do. The interface greys out what is missing.
FREQUENCY = "frequency"
MODE = "mode"
FILTER = "filter"        # a filter width alongside the mode
SIGNAL = "signal"        # signal strength, for the S-meter and the scanner
VOLUME = "volume"        # its own audio level
SQUELCH = "squelch"
MUTE = "mute"

AGC = "agc"              # the demodulator's AGC, on or off -- a receiver's AGC switch
NR = "nr"                # the demodulator's noise reduction, on or off
NOTCH = "notch"          # an automatic notch (SDRangel WDSP's ANF), on or off
NB = "nb"                # a noise blanker, on or off
CW_PEAK = "cw_peak"      # a CW peaking filter, on or off
# A squelch with a SWITCH of its own and a threshold in percent (SDRangel's
# WDSP receiver) -- not SQUELCH, which is a threshold in the SDR's own units
# with fully open as its "off" (Gqrx).
SQUELCH_SWITCH = "squelch_switch"
RF_GAIN = "rf_gain"      # the SDR hardware's front-end gain, in dB
# The width of the band the SDR samples -- what its spectrum and waterfall
# show. SDRangel: the device's decimation.
BANDWIDTH = "bandwidth"
# A CW decoder whose text reaches the application -- SDRangel's Morse
# Decoder feature, over UDP.
DECODER = "decoder"
CAPABILITIES = {FREQUENCY, MODE, FILTER, SIGNAL, VOLUME, SQUELCH, MUTE, AGC, NR,
                NOTCH, NB, CW_PEAK, SQUELCH_SWITCH, RF_GAIN, BANDWIDTH, DECODER}

# A "CW" from an SDR with no sideband of its own: the application has to
# choose one -- see SDR_Link._from_sdr_mode. Written "cw" in the file.
CW_EITHER = object()
AMBIGUOUS = {"cw": CW_EITHER}

RIG_MODES = ("LSB", "USB", "CWL", "CWU")

SHIPPED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "sdr_programs.json")
# The operator's own, in the application's folder -- see app_paths.
USER_FILE = config_path("sdr_programs.json")


class Profile:
    """What is known about one way of driving one SDR program."""

    def __init__(self, key, entry):
        self.key = key
        self.name = entry.get("name", key)
        self.protocol = entry.get("protocol", "rigctl")
        self.default_port = int(entry.get("port", 0))

        # rig mode -> the program's name for it, and back again. Modes left
        # out of the reverse map -- AM, FM -- are ones the rig cannot use and
        # are not passed on.
        self.to_sdr = dict(entry.get("modes", {}))
        self.from_sdr = {}
        for rig_mode, sdr_mode in self.to_sdr.items():
            self.from_sdr.setdefault(sdr_mode, rig_mode)
        for sdr_mode, meaning in entry.get("ambiguous_modes", {}).items():
            self.from_sdr[sdr_mode] = AMBIGUOUS.get(str(meaning).lower(), CW_EITHER)

        self.start = entry.get("start")
        self.stop = entry.get("stop")
        self.self_describing = bool(entry.get("self_describing", False))
        self.known_missing = frozenset(entry.get("known_missing", ()))
        self.known_present = frozenset(entry.get("known_present", ()))

        self.volume_range = tuple(entry["volume_range"]) if entry.get("volume_range") else None
        self.squelch_range = tuple(entry["squelch_range"]) if entry.get("squelch_range") else None
        self.squelch_unit = entry.get("squelch_unit", "")

        # For starting it -- see sdr_launcher.py.
        self.process_names = tuple(entry.get("process_names", ()))
        # What the operating system calls the application, for asking it to
        # quit politely -- see sdr_launcher.stop().
        self.app_name = entry.get("app_name", "")
        # macOS: start it as an APPLICATION ("open -a Gqrx") rather than by
        # running its binary. A binary started directly is not a registered
        # application, so "tell application ... to quit" has nothing to talk
        # to -- the polite quit fails silently and the kill that follows
        # leaves Gqrx's settings half-written.
        self.launch_as_application = bool(entry.get("launch_as_application", False))
        # Never SIGTERM or kill this one. Gqrx corrupts its configuration
        # when it does not shut down its own way -- losing which SDR device
        # was in use. Better to leave a window open than to damage it.
        self.never_force_quit = bool(entry.get("never_force_quit", False))
        self.paths = {system: tuple(paths)
                      for system, paths in entry.get("paths", {}).items()}
        self.arguments = {system: tuple(args)
                          for system, args in entry.get("arguments", {}).items()}
        # rigctld has to be told which radio and where, so it cannot be
        # started from a guess: the operator gives the whole command line.
        self.needs_command_line = bool(entry.get("needs_command_line", False))

    def launch_paths(self, system=None):
        """Where this program might be on a platform, in the order to try."""
        return self.paths.get(system or _system(), ())

    def launch_arguments(self, system=None):
        return self.arguments.get(system or _system(), ())


def _system():
    if sys.platform.startswith("win"):
        return "win32"
    return "darwin" if sys.platform == "darwin" else "linux"


def _complain(where, key, problem):
    print(f"[sdr] {where}: the '{key}' entry {problem}; ignoring it")


def _check(key, entry, where):
    """
    Whether an entry can be used, saying by name what is wrong with it.

    Refused rather than patched: a program described half-correctly connects
    and then behaves oddly, which is harder to work out than one that never
    appears.
    """
    if not isinstance(entry, dict):
        _complain(where, key, "is not a block of settings")
        return False
    if not entry.get("protocol"):
        _complain(where, key, "does not say which protocol drives it")
        return False
    modes = entry.get("modes")
    if not isinstance(modes, dict) or not modes:
        _complain(where, key, "has no mode names")
        return False
    missing = [m for m in RIG_MODES if m not in modes]
    if missing:
        _complain(where, key, f"has no name for {', '.join(missing)}")
        return False
    for field in ("known_missing", "known_present"):
        unknown = set(entry.get(field, ())) - CAPABILITIES
        if unknown:
            _complain(where, key, f"lists {field} this does not know: "
                                  f"{', '.join(sorted(unknown))}")
            return False
    if not entry.get("port"):
        _complain(where, key, "does not say which port it listens on")
        return False
    return True


def _read(path, where):
    """One file's entries, or nothing if it cannot be read."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as err:
        print(f"[sdr] {where} ({path}) could not be read: {err}")
        return {}
    if not isinstance(data, dict):
        print(f"[sdr] {where} ({path}) is not a block of programs")
        return {}
    return {key: entry for key, entry in data.items()
            if not key.startswith("_") and _check(key, entry, where)}


def load():
    """
    Every program this can drive: the shipped ones, with the operator's own
    merged over them entry by entry.
    """
    entries = _read(SHIPPED_FILE, "the programs file")
    entries.update(_read(USER_FILE, "your programs file"))
    return {key: Profile(key, entry) for key, entry in entries.items()}


PROFILES = load()

# "No SDR at all" is a profile too, so every caller has a name to show and a
# set of capabilities to read -- both empty -- rather than special cases for
# an SDR that is not there.
NONE = Profile("none", {"name": "no SDR", "protocol": "none", "port": 1,
                        "modes": {m: m for m in RIG_MODES},
                        "known_missing": sorted(CAPABILITIES)})
PROFILES["none"] = NONE


# Entries that no longer exist, and what a setting naming one now means.
# Without this a saved "sdrangel-rigctl" would fall through to SDR++ below --
# the wrong program, silently.
RETIRED = {"sdrangel-rigctl": "sdrangel"}


def profile_for(setting):
    """
    The profile the "SDR Software" setting names.

    An unknown name gives SDR++ where there is one, since that is what this
    has always driven -- but "none", which the operator chooses to say there
    is no SDR, gives NONE rather than falling back to one.
    """
    key = str(setting or "").strip().lower()
    if key in ("", "none"):
        return NONE
    if key in RETIRED and key not in PROFILES:   # FIX: retired entry -- see RETIRED
        print(f"[sdr] '{key}' is no longer offered; using '{RETIRED[key]}'")
        key = RETIRED[key]
    return PROFILES.get(key) or PROFILES.get("sdr++") or NONE


def choices():
    """
    (key, name) for every program, for the Setup page -- "None" first, then
    the rest by name.
    """
    rest = sorted(((key, profile.name) for key, profile in PROFILES.items()
                   if key != "none"), key=lambda pair: pair[1].lower())
    return [("none", "None")] + rest
