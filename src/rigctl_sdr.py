#!/usr/bin/python3
"""
RigctlSDR -- drives any rigctl-speaking SDR: SDR++, Gqrx, a rigctld.

Replaces SDRPlusPlusController. One class for every program, told which one
it is talking to by a Profile (sdr_profiles.py), and finding out at connect
what the version actually running can do -- see discover().

It POLLS, because rigctl cannot push: every POLL_MS it reads the frequency
and mode, and the signal strength where there is one, and reports what
changed through its callbacks. What it SETS it records at once, so the next
poll does not mistake its own change for one made in the SDR -- the
echo-suppression the SDR++ controller learned the hard way.

All conversation goes through RigctlClient, which keeps each command with its
own reply -- see rigctl_client.py for why that needs doing.
"""
import globalvars as gv
from rigctl_client import RigctlClient, ConnectionLost
from sdr_profiles import FREQUENCY, MODE, FILTER, SIGNAL, VOLUME, SQUELCH, MUTE

POLL_MS = 200


def _number(text):
    """A float from a server's reply, or None."""
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


class RigctlSDR:
    """One rigctl-speaking SDR."""

    def __init__(self, root, profile):
        self.root = root
        self.profile = profile
        self._client = RigctlClient()
        self._poll_id = None

        self.capabilities = frozenset()
        self.frequency = None
        self.mode = None
        self.filter_width = None
        self.signal = None           # dBFS, where the SDR reports it
        self.volume = None           # its own audio level, in its own units
        self.muted = None            # its own mute, where it has one
        self.squelch = None          # its squelch threshold, in its own units

        # Called with the new value when it changes in the SDR itself.
        self.on_frequency = None
        self.on_mode = None
        self.on_filter = None
        self.on_signal = None
        self.on_volume = None        # the level changed in the SDR itself
        self.on_mute = None          # its mute changed in the SDR itself
        self.on_squelch = None       # its squelch changed in the SDR itself
        self.on_disconnect = None

    @property
    def is_connected(self):
        return self._client.connected

    def default_filter_width(self, sdr_mode):
        """The configured default width for a mode: CW's, or SSB's for the rest."""
        try:
            if "CW" in str(sdr_mode).upper():
                return int(gv.config.get_sdr_cw_filter_default_hz())
            return int(gv.config.get_sdr_ssb_filter_default_hz())
        except Exception:
            return 500 if "CW" in str(sdr_mode).upper() else 2600

    # ------------------------------------------------------------------
    # Connecting, and finding out what it can do
    # ------------------------------------------------------------------
    def connect(self, host, port):
        """
        Connects, and finds out what this SDR can do.

        Returns False if it could not connect, or if what answered cannot
        report a frequency -- which is not a rigctl server this can use.
        """
        self.disconnect()
        if not self._client.connect(host, port):
            return False
        try:
            if not self.discover():
                self._client.close()
                return False
        except ConnectionLost:
            return False
        self._poll_id = self.root.after(POLL_MS, self._poll)
        return True

    def discover(self):
        """
        Finds out what this SDR can do. READS ONLY -- nothing here changes
        its setting, except where a value it just reported is sent straight
        back, which changes nothing.

        Returns False if it cannot even report a frequency.
        """
        client, known_missing = self._client, self.profile.known_missing
        # What the profile knows the program has, taken on trust.
        caps = set(self.profile.known_present)

        reply = client.query("f")
        if not (reply.ok and reply.values and _number(reply.values[0]) is not None):
            return False
        self.frequency = int(_number(reply.values[0]))
        caps.add(FREQUENCY)

        reply = client.query("m", lines=2)
        if reply.ok and reply.values:
            self.mode = reply.values[0].strip().upper()
            caps.add(MODE)
            width = _number(reply.values[1]) if len(reply.values) > 1 else None
            self.filter_width = int(width) if width else None
            # FILTER: send back the mode and width it just reported. Nothing
            # changes, and it shows whether a width is accepted -- which in
            # some SDR++ versions it is not, through a parsing bug. Only where
            # the profile does not already know, and only with a real width
            # to send back.
            if (self.filter_width and FILTER not in known_missing
                    and FILTER not in caps):
                if client.command(f"M {self.mode} {self.filter_width}").ok:
                    caps.add(FILTER)

        # What it can read and set, if it says -- Gqrx and rigctld do.
        readable = writable = None
        if self.profile.self_describing:
            reply = client.query("l ?")
            if reply.ok and reply.values:
                readable = set(reply.values[0].upper().split())
            reply = client.query("L ?")
            if reply.ok and reply.values:
                writable = set(reply.values[0].upper().split())

        for cap, level in ((SIGNAL, "STRENGTH"), (VOLUME, "AF"), (SQUELCH, "SQL")):
            if cap in known_missing:
                continue
            # Read it -- from the list if there is one, else by trying.
            current = None
            if readable is None or level in readable:
                reply = client.query(f"l {level}")
                current = _number(reply.values[0]) if reply.ok and reply.values else None
            if current is None:
                continue
            if cap == SIGNAL:
                caps.add(SIGNAL)
                self.signal = current
                continue
            # Set it -- from the list, else by sending back what it reported.
            if writable is not None:
                settable = level in writable
            else:
                settable = client.command(f"L {level} {current}").ok
            if settable:
                caps.add(cap)
                if cap == VOLUME:
                    self.volume = current
                elif cap == SQUELCH:
                    self.squelch = current

        if MUTE not in known_missing:
            reply = client.query("u MUTE")
            state = reply.values[0].strip() if reply.ok and reply.values else None
            if state in ("0", "1") and client.command(f"U MUTE {state}").ok:
                caps.add(MUTE)
                self.muted = state == "1"

        self.capabilities = frozenset(caps)
        return True

    def disconnect(self):
        if self._poll_id is not None:
            try:
                self.root.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        self._client.close()
        self.capabilities = frozenset()

    def start(self):
        """Starts the SDR's receiver, if the program has a way to."""
        return self._command(self.profile.start) if self.profile.start else True

    def stop(self):
        """Stops the SDR's receiver, if the program has a way to."""
        return self._command(self.profile.stop) if self.profile.stop else True

    # ------------------------------------------------------------------
    # Setting -- each records what it set, so the poll does not echo it
    # ------------------------------------------------------------------
    def set_frequency(self, hz):
        if self._command(f"F {int(hz)}"):
            self.frequency = int(hz)
            return True
        return False

    def set_mode(self, sdr_mode, width=0):
        """
        Sets the mode, with a filter width where the SDR accepts one.

        The mode and width are recorded only when the SDR says it took them.
        The controller this replaces recorded them before sending, so a
        refused mode was remembered as set and never tried again.
        """
        sdr_mode = str(sdr_mode).upper()
        width = int(width or self.filter_width or self.default_filter_width(sdr_mode))
        if FILTER in self.capabilities:
            ok = self._command(f"M {sdr_mode} {width}")
        else:
            # No width, where one is refused. Width 0 is rigctl's "leave it
            # as it is"; a server that refuses that too gets the mode alone.
            ok = self._command(f"M {sdr_mode} 0") or self._command(f"M {sdr_mode}")
        if ok:
            self.mode = sdr_mode
            if FILTER in self.capabilities:
                self.filter_width = width
            return True
        return False

    def set_filter_width(self, width):
        if FILTER not in self.capabilities or not self.mode:
            return False
        if self._command(f"M {self.mode} {int(width)}"):
            self.filter_width = int(width)
            return True
        return False

    def set_level(self, level, value):
        """
        Sets a level -- "AF", "SQL" -- the SDR says it can set. The audio
        level is recorded on success, so the poll does not report it back.
        """
        if self._command(f"L {level} {value}"):
            if level == "AF":
                self.volume = float(value)
            elif level == "SQL":
                self.squelch = float(value)
            return True
        return False

    def get_level(self, level):
        """Reads a level, or None."""
        try:
            reply = self._client.query(f"l {level}")
        except ConnectionLost:
            self._lost()
            return None
        return _number(reply.values[0]) if reply.ok and reply.values else None

    def set_mute(self, muted):
        if self._command(f"U MUTE {1 if muted else 0}"):
            self.muted = bool(muted)
            return True
        return False

    def _command(self, text):
        try:
            return self._client.command(text).ok
        except ConnectionLost:
            self._lost()
            return False

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------
    def _poll(self):
        """Reads what the SDR is doing, and reports what changed."""
        self._poll_id = None
        if not self.is_connected:
            return
        try:
            reply = self._client.query("f")
            hz = _number(reply.values[0]) if reply.ok and reply.values else None
            if hz is not None and int(hz) != self.frequency:
                self.frequency = int(hz)
                self._call(self.on_frequency, self.frequency)

            reply = self._client.query("m", lines=2)
            if reply.ok and reply.values:
                mode = reply.values[0].strip().upper()
                if mode != self.mode:
                    self.mode = mode
                    self._call(self.on_mode, mode)
                width = _number(reply.values[1]) if len(reply.values) > 1 else None
                if width and int(width) != self.filter_width:
                    self.filter_width = int(width)
                    self._call(self.on_filter, self.filter_width)

            # Its own audio level and mute, so the application's controls
            # follow a change made in the SDR -- as frequency and filter do.
            if VOLUME in self.capabilities:
                reply = self._client.query("l AF")
                level = _number(reply.values[0]) if reply.ok and reply.values else None
                if level is not None and level != self.volume:
                    self.volume = level
                    self._call(self.on_volume, level)
            if SQUELCH in self.capabilities:
                reply = self._client.query("l SQL")
                level = _number(reply.values[0]) if reply.ok and reply.values else None
                if level is not None and level != self.squelch:
                    self.squelch = level
                    self._call(self.on_squelch, level)
            if MUTE in self.capabilities:
                reply = self._client.query("u MUTE")
                state = reply.values[0].strip() if reply.ok and reply.values else None
                if state in ("0", "1") and (state == "1") != self.muted:
                    self.muted = state == "1"
                    self._call(self.on_mute, self.muted)

            if SIGNAL in self.capabilities:
                reply = self._client.query("l STRENGTH")
                level = _number(reply.values[0]) if reply.ok and reply.values else None
                if level is not None:
                    self.signal = level
                    self._call(self.on_signal, level)
        except ConnectionLost:
            self._lost()
            return
        self._poll_id = self.root.after(POLL_MS, self._poll)

    def _lost(self):
        self.disconnect()
        self._call(self.on_disconnect)

    @staticmethod
    def _call(callback, *args):
        if callable(callback):
            try:
                callback(*args)
            except Exception as err:
                print(f"[sdr] a callback failed: {err}")
