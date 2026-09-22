#!/usr/bin/python3
"""
ChannelSets -- the application's own banks of channels.

WHAT THEY ARE

Named lists of channels -- a frequency, a mode, a short label, a longer name
and a filter width. They are the operator's data, not the rig's: unlike the
rig's twenty EEPROM slots they can be any length, and a change is saved
straight away, since there is no EEPROM wearing out to protect.

THEIR OWN FILE, IN THE USER'S HOME

    ~/.ubitx_cec_desktop_channels.json

beside the settings file, ~/.ubitx_cec_desktop.ini, and found by the same
rule, so it lands in the same place on macOS, Linux and Windows. Data rather
than settings, so it can be backed up, copied between machines or shared on
its own. JSON rather than INI, because the sets are nested lists, which INI
holds badly.

The top level is {"version": 1, "sets": {...}}, so scan settings can sit
beside the sets later without a second file, and a future change of layout
can be recognised by its version.

MOVING OVER

The sets used to live in the settings file, under "Scan Channels Registry
Queue". The first time this runs with no channel file of its own, it takes
them from there and writes the new file; after that the file is the only copy
this application uses. The entry in the settings file is left where it is, so
the previous version of the application, which still reads it, goes on
working -- the two copies drift apart from then on, which is the price of not
breaking it.

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

# Beside the settings file, by the same rule -- see configuration.py.
DEFAULT_PATH = os.path.expanduser(os.path.join("~", ".ubitx_cec_desktop_channels.json"))
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

    def __init__(self, config, path=None):
        """
        Args:
            config: The ConfigurationManager -- gv.config. Used only to move
                the sets over, the first time, from where they used to live.
            path: The channel file. Defaults to DEFAULT_PATH, in the user's
                home; given one, a test can use a scratch file.
        """
        self._config = config
        self.path = path or DEFAULT_PATH
        self._sets = {}
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
        timestamp, and the sets are taken from the settings file instead.
        Saving over it would throw away whatever could still be rescued from
        it by hand.
        """
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                self._sets = self._from_registry(data.get("sets", {}))
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

        # Moving over from the settings file.
        registry = self._config.get_scan_channels_registry() or {}
        self._sets = self._from_registry(registry)
        self.save()

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
                         for set_name, channels in self._sets.items()}}
        temporary = self.path + ".saving"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as err:
            print(f"[channels] could not save {self.path}: {err}")
