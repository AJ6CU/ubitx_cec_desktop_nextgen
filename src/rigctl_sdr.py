#!/usr/bin/python3
"""
RigctlSDR -- drives any rigctl-speaking SDR: SDR++, Gqrx, a rigctld.

Replaces SDRPlusPlusController. One class for every program, told which one
it is talking to by a Profile (sdr_programs.py), and finding out at connect
what the version actually running can do -- see discover().

It POLLS, because rigctl cannot push: every POLL_MS it reads the frequency
and mode, and the signal strength where there is one, and reports what
changed through its callbacks. What it SETS it records at once, so the next
poll does not mistake its own change for one made in the SDR -- the
echo-suppression the SDR++ controller learned the hard way. And, for a
program that applies a change a moment AFTER accepting it (SDRoxide), the
old value read back meanwhile is not taken as the operator turning the SDR
-- see _stale and Profile.settle_seconds.

All conversation goes through RigctlClient, which keeps each command with its
own reply -- see rigctl_client.py for why that needs doing.
"""
import os
import time

import globalvars as gv
from rigctl_client import RigctlClient, ConnectionLost
from sdr_programs import (FREQUENCY, MODE, FILTER, SIGNAL, VOLUME, SQUELCH, MUTE,
                          NB, NR, NOTCH)

POLL_MS = 200

# UBITX_SDR_TRACE=1 in the environment: every command sent, and every change
# the poll reports as made in the SDR, printed -- for finding who moved what.
TRACE = os.environ.get("UBITX_SDR_TRACE") == "1"

# The listening aids rigctl can switch: the window's name for each, its
# capability, and Hamlib's function name for `u` / `U`. On or off only --
# rigctl has no way to reach their adjustments, so their pop-ups hold just
# the switch. Found at connect by reading each and sending the state back
# (SDRoxide answers all three; SDR++ none).
SWITCHES = (("nb", NB, "NB"), ("nr", NR, "NR"), ("notch", NOTCH, "ANF"))


def _mode_and_width(reply):
    """
    The mode and filter width from an "m" reply -- WHICHEVER SHAPE IT COMES IN.

    Gqrx and rigctld answer on two lines:

        USB
        2400

    SDRangel answers on one:

        USB 3000

    Read as two lines, SDRangel's becomes a mode called "USB 3000" and no
    width at all -- so the mode never matches anything and the filter is
    never known. The protocol does not say which shape to expect, so both
    are accepted.

    Returns:
        (mode, width) -- either may be None.
    """
    if not reply or not reply.ok or not reply.values:
        return None, None
    values = list(reply.values)
    if len(values) == 1 and " " in values[0].strip():
        values = values[0].split()
    mode = values[0].strip().upper() if values else None
    width = _number(values[1]) if len(values) > 1 else None
    return mode, (int(width) if width else None)


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
        self.dsp_on = {}             # {"nb": True, ...} -- the switches it has

        # Called with the new value when it changes in the SDR itself.
        self.on_frequency = None
        self.on_mode = None
        self.on_filter = None
        self.on_signal = None
        self.on_volume = None        # the level changed in the SDR itself
        self.on_mute = None          # its mute changed in the SDR itself
        self.on_squelch = None       # its squelch changed in the SDR itself
        self.on_disconnect = None
        self.on_dsp = None           # a switch changed in the SDR itself

        # What was just set, while the SDR may still report the old value:
        # {"frequency": (value, until)} -- see Profile.settle_seconds.
        self._settling = {}
        # A mode hop under way -- (mode, width, until) -- see _send_mode.
        self._hop = None

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

        mode, width = _mode_and_width(client.query("m", lines=2))
        if mode:
            self.mode = mode
            caps.add(MODE)
            self.filter_width = width
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

        # The listening aids' switches -- each read, and its state sent back.
        self.dsp_on = {}
        for function, cap, name in SWITCHES:
            if cap in known_missing:
                continue
            reply = client.query(f"u {name}")
            state = reply.values[0].strip() if reply.ok and reply.values else None
            if state in ("0", "1") and client.command(f"U {name} {state}").ok:
                caps.add(cap)
                self.dsp_on[function] = state == "1"

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
        self.dsp_on = {}
        self._hop = None

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
            self._set("frequency", self.frequency)
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
            ok = self._send_mode(sdr_mode, width)
        else:
            # No width, where one is refused. Width 0 is rigctl's "leave it
            # as it is"; a server that refuses that too gets the mode alone.
            ok = self._command(f"M {sdr_mode} 0") or self._command(f"M {sdr_mode}")
        if ok:
            self.mode = sdr_mode
            self._set("mode", sdr_mode)
            self._notch_off_in_cw(sdr_mode)
            if FILTER in self.capabilities:
                self.filter_width = width
                self._set("width", width)
            return True
        return False

    def set_filter_width(self, width):
        if FILTER not in self.capabilities or not self.mode:
            return False
        if self._send_mode(self.mode, int(width)):
            self.filter_width = int(width)
            self._set("width", self.filter_width)
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
                self._set("volume", self.volume)
            elif level == "SQL":
                self.squelch = float(value)
                self._set("squelch", self.squelch)
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
            self._set("mute", self.muted)
            return True
        return False

    # ------------------------------------------------------------------
    # The listening aids -- switches only
    # ------------------------------------------------------------------
    def set_dsp(self, function, on):
        """Switches NB, NR or the notch on or off -- where the SDR has it."""
        for name_here, cap, name in SWITCHES:
            if name_here == function and cap in self.capabilities:
                if self._command(f"U {name} {1 if on else 0}"):
                    self.dsp_on[function] = bool(on)
                    self._set(function, bool(on))
                    return True
        return False

    def dsp_knob_names(self, function):
        """None: rigctl reaches a function's switch, not its adjustments."""
        return []

    def _send_mode(self, sdr_mode, width):
        """
        `M <mode> <width>` -- through another mode first where the program
        takes a width only WITH a change of mode.

        FIX (SDRoxide, 2026-09-28): its rigctl server treats an `M` naming
        the mode it already REPORTS as a success that changes nothing --
        deliberately, so WSJT-X re-sending the mode it read does not restart
        a decoder (crates/sdroxide-rigctld/src/proto.rs, set_mode) -- and the
        width goes with it. It takes any width, presets or not, with a change
        of mode. So a new width in the same mode goes by way of another mode.

        TWO STEPS, NOT TWO COMMANDS AT ONCE: the other mode now; the mode
        wanted only once it REPORTS the other one (see _poll). Sent together,
        the second arrived before SDRoxide's state had moved -- still naming
        the mode it reported -- and was dropped as a no-op, leaving it in
        the other mode: the CWL that sometimes ended in LSB. Remove with
        "width_needs_mode_change" once SDRoxide takes a width in the same
        mode.
        """
        if (self.profile.width_needs_mode_change and sdr_mode == self.mode
                and width != self.filter_width):
            hop = self._hop_mode(sdr_mode)
            if hop and self._hop is None:
                if not self._command(f"M {hop} {width}"):
                    return False
                # Until it is back in this mode WITH this width, every mode
                # and width it reports is the hop, or from before it.
                #
                # FIX: and so is every SWITCH it reports. SDRoxide keeps NB,
                # NR, notch and more PER MODE, so the hop loads the other
                # mode's -- the notch lamp flickered, and came back on or off
                # as SDRoxide saved it on the way through. The switches as
                # they were are kept, and sent back once the hop is over.
                self._hop = {"mode": sdr_mode, "width": width, "via": hop,
                             "back": False, "switches": dict(self.dsp_on),
                             "until": time.monotonic() + self._hop_window(),
                             "retries": self.HOP_RETRIES}
                return True
            if hop and self._hop is not None:
                # A hop already under way: it goes back to this width instead.
                self._hop["mode"], self._hop["width"] = sdr_mode, width
                return True
        # A real change of mode ends any hop under way -- its way back would
        # undo this.
        self._hop = None
        return self._command(f"M {sdr_mode} {width}")

    def _follow_hop(self, mode, width):
        """
        One poll's worth of a hop: (mode, width, still hopping). While it is
        under way the mode and width read are the hop's -- None, so nothing
        is reported, and nothing reaches the rig.
        """
        hop, now = self._hop, time.monotonic()
        if not hop["back"]:
            # Out: once it reports the other mode -- or has had its time --
            # the mode wanted, with the width. From the other mode that is a
            # change of mode, so the width goes with it.
            if mode == hop["via"] or now > hop["until"]:
                self._command(f"M {hop['mode']} {hop['width']}")
                hop["back"], hop["until"] = True, now + self._hop_window()
            return None, None, True
        if mode == hop["mode"] and width == hop["width"]:
            done = True
        elif now > hop["until"] and hop["retries"] > 0:
            # Not back in time: the mode wanted again, rather than what is
            # read being believed -- believing it sent the other mode to the
            # rig.
            print(f"[sdr] {self.profile.name} not back from a filter change "
                  f"(reads {mode} {width}) -- sending {hop['mode']} {hop['width']} again")
            self._command(f"M {hop['mode']} {hop['width']}")
            hop["until"], hop["retries"] = now + self._hop_window(), hop["retries"] - 1
            return None, None, True
        elif now > hop["until"]:
            print(f"[sdr] {self.profile.name} did not come back from a filter change "
                  f"-- it reads {mode} {width}")
            done = True
        else:
            return None, None, True
        self._hop = None
        # Back: the switches as they were before the hop -- SDRoxide keeps
        # them per mode, so the hop loaded the other mode's.
        for function, on in hop["switches"].items():
            self.set_dsp(function, on)
        return mode, width, False

    # How many times a hop that has not come back is sent its mode again
    # before what the SDR reports is believed.
    HOP_RETRIES = 2

    def _hop_window(self):
        return max(self.profile.settle_seconds, 1.0)

    def _hop_mode(self, sdr_mode):
        """Another of the program's modes, of the same kind where there is one -- USB for LSB."""
        modes = [m for m in dict.fromkeys(self.profile.to_sdr.values()) if m != sdr_mode]
        is_cw = sdr_mode.startswith("CW")
        same_kind = [m for m in modes if m.startswith("CW") == is_cw]
        return (same_kind or modes or [None])[0]

    def _notch_off_in_cw(self, sdr_mode):
        """
        FIX: the notch goes off on entering CW, as SDRangel's does -- it
        would take out the one steady tone there is. The window then keeps
        it off (SDR_Link.OFF_IN_CW).
        """
        if str(sdr_mode).upper().startswith("CW") and self.dsp_on.get("notch"):
            if self.set_dsp("notch", False):
                self._call(self.on_dsp, "notch", quiet=True)

    def _set(self, name, value):
        """Records a value just set, for the settle window -- where there is one."""
        if self.profile.settle_seconds > 0:
            self._settling[name] = (value, time.monotonic() + self.profile.settle_seconds)

    def _stale(self, name, read):
        """
        True if a read-back is the SDR's OLD value, still reported after a
        change it accepted -- within the settle window, and not yet what was
        set. Once it reads what was set, or the window ends, it is believed.
        """
        pending = self._settling.get(name)
        if pending is None:
            return False
        value, until = pending
        if read == value or time.monotonic() > until:
            del self._settling[name]
            return False
        return True

    def _command(self, text):
        try:
            ok = self._client.command(text).ok
            if TRACE:
                print(f"[sdr] -> {text}  {'ok' if ok else 'REFUSED'}")
            return ok
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
            if (hz is not None and int(hz) != self.frequency
                    and not self._stale("frequency", int(hz))):
                self.frequency = int(hz)
                self._call(self.on_frequency, self.frequency)

            mode, width = _mode_and_width(self._client.query("m", lines=2))
            hopping = self._hop is not None
            if hopping:
                mode, width, hopping = self._follow_hop(mode, width)
            if mode and mode != self.mode and not self._stale("mode", mode):
                self.mode = mode
                self._call(self.on_mode, mode)
                self._notch_off_in_cw(mode)
            if (width and width != self.filter_width
                    and not self._stale("width", width)):
                self.filter_width = width
                self._call(self.on_filter, self.filter_width)

            # Its own audio level and mute, so the application's controls
            # follow a change made in the SDR -- as frequency and filter do.
            if VOLUME in self.capabilities and not hopping:
                reply = self._client.query("l AF")
                level = _number(reply.values[0]) if reply.ok and reply.values else None
                if (level is not None and level != self.volume
                        and not self._stale("volume", level)):
                    self.volume = level
                    self._call(self.on_volume, level)
            if SQUELCH in self.capabilities:
                reply = self._client.query("l SQL")
                level = _number(reply.values[0]) if reply.ok and reply.values else None
                if (level is not None and level != self.squelch
                        and not self._stale("squelch", level)):
                    self.squelch = level
                    self._call(self.on_squelch, level)
            if MUTE in self.capabilities and not hopping:
                reply = self._client.query("u MUTE")
                state = reply.values[0].strip() if reply.ok and reply.values else None
                if (state in ("0", "1") and (state == "1") != self.muted
                        and not self._stale("mute", state == "1")):
                    self.muted = state == "1"
                    self._call(self.on_mute, self.muted)

            # The listening aids' switches, so the lamps follow a change
            # made in the SDR itself -- not during a hop, when they are the
            # other mode's.
            for function, cap, name in SWITCHES:
                if cap not in self.capabilities or hopping:
                    continue
                reply = self._client.query(f"u {name}")
                state = reply.values[0].strip() if reply.ok and reply.values else None
                if state not in ("0", "1"):
                    continue
                on = state == "1"
                if on != self.dsp_on.get(function) and not self._stale(function, on):
                    self.dsp_on[function] = on
                    self._call(self.on_dsp, function)

            if SIGNAL in self.capabilities:
                reply = self._client.query("l STRENGTH")
                level = _number(reply.values[0]) if reply.ok and reply.values else None
                if level is not None:
                    self.signal = level
                    self._call(self.on_signal, level, quiet=True)
        except ConnectionLost:
            self._lost()
            return
        self._poll_id = self.root.after(POLL_MS, self._poll)

    def _lost(self):
        self.disconnect()
        self._call(self.on_disconnect)

    @staticmethod
    def _call(callback, *args, quiet=False):
        if TRACE and args and not quiet:
            print(f"[sdr] <- changed in the SDR: {args[0]!r}")
        if callable(callback):
            try:
                callback(*args)
            except Exception as err:
                print(f"[sdr] a callback failed: {err}")
