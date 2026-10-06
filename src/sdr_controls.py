#!/usr/bin/python3
"""
For any REST based SDR program, the controls are, read from a file -- sdr_controls.json.
This is ignored for SDR with serial connections that use the RIGCTL protocol.

WHY A FILE, as for sdr_programs.json: the knobs behind the Operate tab's
lamps -- which settings a demodulator has, their ranges, their labels, their
units -- are a description of somebody else's software, not logic. They go
stale when that software changes, and changing a range should not mean
editing Python. The window builds its pop-ups from whatever this says, and
knows no SDR's controls itself.

WHAT STAYS CODE: how a dial position becomes the number the SDR stores, where
that is more than a whole number -- WDSP's AGC slope stored in tenths, the SSB
demodulator's alpha as 1 - 10^(-n/10). Each is written once here and NAMED in
the file ("convert": "tenths"), so the file can use it without being a
programming language. The same for a value shown in a way of its own
("text": "power_of_two_ms").

MERGED over by the operator's own file, ~/.ubitx_cec_desktop/sdr_controls.json,
FUNCTION BY FUNCTION: an entry there for WDSPRx's "agc" replaces that one
function, and everything else still comes from the shipped file. A malformed
entry is refused by name, and the rest still loads.

The in-memory shape is the one rest_sdr has always used -- each setting with
callable `store`, `load` and `text`, a function's `knobs` a callable of the
settings held -- so the transport reads it as before.
"""
import json
import math
import os

from app_paths import config_path, shown
from sdr_programs import CAPABILITIES

SHIPPED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "sdr_controls.json")
USER_FILE = config_path("sdr_controls.json")

KINDS = ("range", "choice", "step")


def _int(value):
    return int(round(float(value)))


def _alpha_store(n):
    return 1.0 - 10 ** (-float(n) / 10.0)


def _alpha_load(stored):
    return _int(-10.0 * math.log10(max(1.0 - float(stored), 1e-9)))


# How a dial position (a whole number the operator reads) is stored, and read
# back: (store, load).
CONVERSIONS = {
    "int": (_int, _int),
    # Stored as a float -- WDSP's CW peak gain.
    "float": (float, _int),
    # Stored in tenths -- WDSP's AGC slope: dial 10 is 100.
    # A default between whole dial steps -- WDSP's slope, 3.5 -- is stored
    # exactly (35), though the knob can only show 4.
    "tenths": (lambda v: _int(float(v) * 10), lambda stored: _int(float(stored) / 10.0)),
    # The SSB demodulator's NR alpha, smoothing: 1 - 10^(-n/10) for dial n.
    "alpha_db": (_alpha_store, _alpha_load),
}

# A value shown in a way of its own.
TEXTS = {
    # The SSB demodulator's AGC time, stored as a power of two: 7 is 128 ms.
    "power_of_two_ms": lambda v: f"{2 ** int(v)} ms",
}


def _complain(where, what, why):
    print(f"[sdr] {where}: {what} {why} -- left out")


def _setting(entry, where, what):
    """One setting from the file, in the transport's shape -- or None."""
    if not isinstance(entry, dict):
        _complain(where, what, "is not a block")
        return None
    for key in ("field", "caption", "low", "high"):
        if key not in entry:
            _complain(where, what, f"has no {key}")
            return None
    kind = entry.get("kind", "range")
    if kind not in KINDS:
        _complain(where, what, f"has kind {kind!r}, not one of {', '.join(KINDS)}")
        return None
    convert = entry.get("convert", "int")
    if convert not in CONVERSIONS:
        _complain(where, what, f"has convert {convert!r}, not one of "
                               f"{', '.join(CONVERSIONS)}")
        return None
    text = entry.get("text")
    if text is not None and text not in TEXTS:
        _complain(where, what, f"has text {text!r}, not one of {', '.join(TEXTS)}")
        return None
    default = entry.get("default")
    if default is not None and not (isinstance(default, (int, float))
                                    and entry["low"] <= default <= entry["high"]):
        _complain(where, what, f"has default {default!r}, not a number from "
                               f"{entry['low']} to {entry['high']}")
        return None
    labels = tuple(entry["labels"]) if entry.get("labels") else None
    short = tuple(entry["short"]) if entry.get("short") else labels
    store, load = CONVERSIONS[convert]
    return {"field": entry["field"], "caption": entry["caption"],
            "low": entry["low"], "high": entry["high"], "kind": kind,
            "unit": entry.get("unit", ""), "labels": labels, "short": short,
            "store": store, "load": load,
            "read_only": bool(entry.get("read_only", False)),
            "default": default,
            "text": TEXTS[text] if text else None}


def _knobs(spec, settings, where, what):
    """
    A function's `knobs` entry as a callable of the settings held: plain names
    as they are, {"by": setting, "choose": [...]} the one the setting picks.
    """
    for item in spec:
        names = [item] if isinstance(item, str) else (
            list(item.get("choose", ())) + [item.get("by")]
            if isinstance(item, dict) else [None])
        if any(name not in settings for name in names):
            _complain(where, what, "has knobs naming a setting it does not have")
            return None

    def knobs(held):
        chosen = []
        for item in spec:
            if isinstance(item, str):
                chosen.append(item)
            else:
                options = item["choose"]
                index = held.get(item["by"], 0)
                chosen.append(options[index] if isinstance(index, int)
                              and 0 <= index < len(options) else options[0])
        return chosen
    return knobs


def _function(entry, where, what):
    """One function -- its switch, capability and settings -- or None."""
    if not isinstance(entry, dict) or not entry.get("switch"):
        _complain(where, what, "has no switch")
        return None
    if entry.get("capability") not in CAPABILITIES:
        _complain(where, what, f"has capability {entry.get('capability')!r}, "
                               f"which this does not know")
        return None
    settings = {}
    for name, setting in (entry.get("settings") or {}).items():
        made = _setting(setting, where, f"{what}.{name}")
        if made is None:
            return None
        settings[name] = made
    function = {"switch": entry["switch"], "capability": entry["capability"],
                "settings": settings}
    if entry.get("knobs") is not None:
        knobs = _knobs(entry["knobs"], settings, where, what)
        if knobs is None:
            return None
        function["knobs"] = knobs
    return function


def _rf_gain(entry, where, what):
    """A device's RF gain: its field, units per dB, AGC field and steps -- or None."""
    if (not isinstance(entry, dict) or not entry.get("field")
            or not entry.get("per_db") or not entry.get("steps")):
        _complain(where, what, "needs field, per_db and steps")
        return None
    return {"field": entry["field"], "per_db": entry["per_db"],
            "auto": entry.get("auto"), "steps": tuple(sorted(entry["steps"]))}


def _read(path, where):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as err:
        print(f"[sdr] {where} ({shown(path)}) could not be read: {err}")
        return {}
    return data if isinstance(data, dict) else {}


def load(program="sdrangel"):
    """
    One program's controls: (channels, devices). channels[type][function] as
    rest_sdr has always used it; devices[hwType] its RF gain. The shipped
    file, with the operator's own merged over it function by function.
    """
    channels, devices = {}, {}
    for path, where in ((SHIPPED_FILE, "the controls file"),
                        (USER_FILE, "your controls file")):
        block = _read(path, where).get(program) or {}
        for channel_type, functions in (block.get("channels") or {}).items():
            for name, entry in (functions or {}).items():
                made = _function(entry, where, f"{channel_type}.{name}")
                if made is not None:
                    channels.setdefault(channel_type, {})[name] = made
        for hw_type, entry in (block.get("devices") or {}).items():
            if isinstance(entry, dict) and "rf_gain" in entry:
                made = _rf_gain(entry["rf_gain"], where, f"{hw_type}.rf_gain")
                if made is not None:
                    devices[hw_type] = made
    return channels, devices
