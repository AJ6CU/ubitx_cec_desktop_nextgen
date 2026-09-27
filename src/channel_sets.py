#!/usr/bin/python3
"""
ChannelSets -- the application's own sets of channels.

WHAT THEY ARE

Named lists of channels -- a frequency, a mode, a short label, a longer name
and a filter width. They are the operator's data, not the rig's: unlike the
rig's twenty EEPROM slots they can be any length, and a change is saved
straight away, since there is no EEPROM wearing out to protect.

THEIR OWN FILE, IN THE APPLICATION'S FOLDER

    ~/.ubitx_cec_desktop/channels.json

beside the settings file, settings.json -- see app_paths. Data rather
than settings, so it can be backed up, copied between machines or shared on
its own. JSON rather than INI, because the sets are nested lists, which INI
holds badly.

The top level is {"version": 1, "sets": {...}, "scan": {...}}: the scan
settings sit beside the sets, and a future change of layout can be recognised
by its version.

SCANNING IS BY SET. The previous application also kept a separate "scan set"
list in the settings file ("Scan Set Settings"), choosing channels to scan
apart from the sets themselves. That concept is gone: you scan the set on
show. Only the time spent on each channel remains a setting, and it lives
here, moved over once from "Scan On Station Time".

NOT IN THE SETTINGS FILE

They were, once, under "Scan Channels Registry Queue", and the scan's dwell
time under "Scan On Station Time". Both are gone from there. This class reads
and writes its own file and nothing else, so there is one copy of the sets
and no question of which is current.

WHY THE APPLICATION OWNS THEM

They used to belong to the SDR++ controller, which loaded its own copy at
startup and saved that copy back whenever it changed anything. With the
Channels tab reading the configuration too, that made two copies -- and the
controller's next save would have written its stale copy over any edit made
in the tab.

Nothing about a channel is specific to one SDR, and some SDRs cannot scan at
all. So the application keeps the sets, here and nowhere else, and the
application scans them: stepping through the channels and tuning the rig,
with whichever SDR is attached following the rig as it does for any other
change.

EVERY CHANGE IS SAVED

Each method that changes a set saves the lot. The sets are small and changes
are made by hand, a few a minute at most, so saving each one costs nothing and
means nothing is ever lost to a crash or a forgotten save.
"""

import json
import os
import time

from app_paths import config_path

# Seconds on each channel when nothing has been set yet.
DEFAULT_DWELL_SECONDS = 5

# Beside the settings file, in the application's folder -- see app_paths.
DEFAULT_PATH = config_path("channels.json")
FILE_VERSION = 1

# The label is short because the table shows it in a narrow column; the name
# is where the description goes. Not an EEPROM limit -- these are not stored
# on the rig -- so it is longer than the rig's five characters.
LABEL_MAX = 12


def _clean_text(value, limit=None):
    """Printable characters only, trimmed, and cut to a length if given."""
    text = "".join(ch for ch in str(value or "") if 32 <= ord(ch) < 127).strip()
    return text[:limit] if limit else text


def _clean_channel(raw):
    """
    One channel in the shape every caller can rely on.

    The configuration has been written by more than one version of the
    application, so every field is checked rather than trusted.
    """
    try:
        freq = int(raw.get("freq_hz", 0))
    except (TypeError, ValueError):
        freq = 0
    try:
        bandwidth = int(raw.get("bandwidth", 0))
    except (TypeError, ValueError):
        bandwidth = 0
    return {"freq_hz": freq,
            "mode": _clean_text(raw.get("mode", "")).upper(),
            "label": _clean_text(raw.get("label", ""), LABEL_MAX),
            "name": _clean_text(raw.get("name", "")),
            "bandwidth": bandwidth}


class ChannelSets:
    """The application's channel sets, loaded from and saved to the configuration."""

    def __init__(self, path=None):
        """
        Args:
            path: The channel file. Defaults to DEFAULT_PATH, in the user's
                home; given one, a test can use a scratch file.
        """
        self.path = path or DEFAULT_PATH
        self._sets = {}
        self._scan = {"dwell_seconds": DEFAULT_DWELL_SECONDS}
        self.load()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def load(self):
        """
        Reads the sets from the channel file, replacing what is held.

        No file yet: the sets are taken from the settings file, where they
        used to live, and written to a new channel file.

        A DAMAGED FILE IS KEPT, NEVER OVERWRITTEN. It is renamed aside with a
        timestamp, and this starts with no sets rather than saving over it --
        which would throw away whatever could still be rescued by hand.
        """
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                self._sets = self._from_registry(data.get("sets", {}))
                # A file from before scanning moved here has no "scan" part;
                # it keeps the value taken from the settings file.
                scan = data.get("scan")
                if isinstance(scan, dict):
                    self._scan["dwell_seconds"] = self._clean_dwell(
                        scan.get("dwell_seconds"), self._scan["dwell_seconds"])
                return
            except (OSError, ValueError, AttributeError) as err:
                kept = f"{self.path}.damaged-{time.strftime('%Y%m%d-%H%M%S')}"
                try:
                    os.replace(self.path, kept)
                    print(f"[channels] {self.path} could not be read ({err}); "
                          f"kept it as {kept} and took the sets from the settings file")
                except OSError:
                    print(f"[channels] {self.path} could not be read ({err}), "
                          f"nor moved aside; its sets are not loaded")
                self._sets = {}
                return

        # No file yet: no sets yet. One is made the first time the operator
        # makes one.
        self._sets = {}

    @staticmethod
    def _clean_dwell(value, fallback):
        """A dwell time in whole seconds, 1 to 120, or `fallback`."""
        try:
            return max(1, min(120, int(round(float(value)))))
        except (TypeError, ValueError):
            return fallback

    # ------------------------------------------------------------------
    # Scan settings
    # ------------------------------------------------------------------
    @property
    def dwell_seconds(self):
        """Seconds the scan spends on each channel."""
        return self._scan["dwell_seconds"]

    def set_dwell_seconds(self, seconds):
        """Sets the time on each channel, 1 to 120 seconds, and saves."""
        self._scan["dwell_seconds"] = self._clean_dwell(seconds, self._scan["dwell_seconds"])
        self.save()
        return self._scan["dwell_seconds"]

    @staticmethod
    def _from_registry(registry):
        """Sets in the stored form, cleaned into the form held here."""
        if not isinstance(registry, dict):
            return {}
        return {str(name): [_clean_channel(ch) for ch in (channels or [])
                            if isinstance(ch, dict)]
                for name, channels in registry.items()}

    def names(self):
        """The sets' names, in the order they are kept."""
        return list(self._sets)

    def channels(self, set_name):
        """A set's channels, as copies -- change them through this class."""
        return [dict(ch) for ch in self._sets.get(set_name, [])]

    # ------------------------------------------------------------------
    # Changing -- every change is saved
    # ------------------------------------------------------------------
    # THE SET IS `set_name`, NEVER `name`. A channel has a field called
    # "name", so update(name, index, name=...) passed `name` twice and Python
    # refused -- renaming a channel was impossible. Every method uses
    # set_name, so the two cannot be confused anywhere.
    def update(self, set_name, index, **fields):
        """
        Changes fields of one channel, and saves.

        Accepts freq_hz, mode, label, name and bandwidth; each is cleaned the
        same way a channel loaded from the configuration is.
        """
        channels = self._sets.get(set_name)
        if channels is None or not 0 <= index < len(channels):
            return
        merged = dict(channels[index])
        merged.update(fields)
        channels[index] = _clean_channel(merged)
        self.save()

    def add(self, set_name, channel, index=None):
        """Adds a channel -- at the end, or before `index` -- and saves."""
        channels = self._sets.setdefault(set_name, [])
        cleaned = _clean_channel(channel)
        if index is None or not 0 <= index <= len(channels):
            channels.append(cleaned)
        else:
            channels.insert(index, cleaned)
        self.save()

    def delete(self, set_name, index):
        """Removes one channel, by position, and saves."""
        channels = self._sets.get(set_name)
        if channels is not None and 0 <= index < len(channels):
            del channels[index]
            self.save()

    # ------------------------------------------------------------------
    # Whole sets -- every change is saved
    # ------------------------------------------------------------------
    def check_new_name(self, set_name, reserved=()):
        """
        Why a name cannot be used for a new or renamed set -- or None if it
        can.

        `reserved` holds names that are taken although no set has them: the
        rig's own set shares the set selector with the sets, so a set
        called the same would be indistinguishable from it.
        """
        name = _clean_text(set_name)
        if not name:
            return "a set needs a name"
        if name in self._sets or name in reserved:
            return f"there is already a set called '{name}'"
        return None

    def create_set(self, set_name, channels=()):
        """A new set -- empty, or holding copies of `channels` -- and saves."""
        name = _clean_text(set_name)
        self._sets[name] = [_clean_channel(ch) for ch in channels]
        self.save()
        return name

    def duplicate_set(self, set_name, new_name):
        """A copy of a set under a new name, and saves."""
        return self.create_set(new_name, self._sets.get(set_name, []))

    def rename_set(self, set_name, new_name):
        """
        Renames a set, keeping its place in the order, and saves.

        Rebuilt rather than popped and re-added, which would move the set to
        the end of the set selector's list.
        """
        new = _clean_text(new_name)
        self._sets = {(new if name == set_name else name): channels
                      for name, channels in self._sets.items()}
        self.save()
        return new

    def delete_set(self, set_name):
        """Removes a whole set, and saves."""
        if self._sets.pop(set_name, None) is not None:
            self.save()

    def save(self):
        """
        Writes every set to the channel file.

        WRITTEN WHOLE OR NOT AT ALL. The sets go to a temporary file beside
        the real one, which is then swapped into place in a single step --
        os.replace is atomic on the same disk -- so a crash or a full disk
        part-way through leaves the previous file intact, not a truncated
        one that would lose every set.
        """
        data = {"version": FILE_VERSION,
                "sets": {set_name: [dict(ch) for ch in channels]
                         for set_name, channels in self._sets.items()},
                "scan": dict(self._scan)}
        temporary = self.path + ".saving"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as err:
            print(f"[channels] could not save {self.path}: {err}")
