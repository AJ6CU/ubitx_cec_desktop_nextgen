#!/usr/bin/python3
"""
RestSDR -- drives SDRangel over its REST API.

The second SDR transport, beside RigctlSDR, and the same shape: SDR_Link
calls the same methods and reads the same attributes, so nothing above this
needs to know which one it has. See SDRANGEL_REST_NOTES.md for what was
established by hand against a running SDRangel, and why REST rather than
SDRangel's own rigctl server.

FREQUENCY, SIGNAL, VOLUME, MUTE, AND STARTING AND STOPPING THE DEVICE, FOR
NOW. Every method SDR_Link calls is here; what is not yet done -- mode and
filter, squelch -- answers "cannot", and the interface greys it out, as it
does for SDR++.

WHAT IT TALKS TO. SDRangel has device sets, each with any number of
channels. Discovery takes the FIRST RECEIVING device set that has a
channel, and the first receiving channel in it -- and says so. With none, it
refuses to connect and says what to add.

TUNING IS A PAIR. What is heard is the device's centre frequency plus the
channel's offset from it. A move that stays well inside the sampled band
changes the offset alone; one that would reach the edge retunes the centre
and resets the offset. See set_frequency.

IT POLLS, as RigctlSDR does, and for the same reason it records what it sets
at once: the next poll must not mistake its own change for one made in
SDRangel. SDRangel's REST adds a wrinkle rigctl did not have -- a change may
take effect after the PATCH has been answered, so a poll straight after can
still see the old value. See SETTLE_SECONDS.

BLOCKING, ON THE INTERFACE THREAD, like RigctlClient: every request has
REPLY_TIMEOUT, and a refused connection fails at once. The worst case is a
hung SDRangel, which is RigctlClient's worst case too.
"""
import json
import math
import time
import urllib.error
import urllib.request

import globalvars as gv
from sdr_programs import FREQUENCY, SIGNAL, VOLUME, MUTE, MODE, FILTER, AGC, NR, RF_GAIN

POLL_MS = 200

# How long one request may take. SDRangel on this computer answers in
# milliseconds; this is only long enough to be sure an answer is not coming,
# and it is the most one request can hold up the interface.
REPLY_TIMEOUT = 0.5

# How long after setting the frequency a poll that disagrees is ignored.
# SDRangel may apply a PATCH after answering it, so a poll straight after can
# still report the old centre or offset -- and would be passed to the rig as
# a click in SDRangel, pulling it back. Ignored, not lost: a real change made
# in SDRangel during this time is still reported, by the first poll after.
SETTLE_SECONDS = 0.6

# How far from the centre the channel may be moved before the centre is
# retuned instead: this share of the sampled band, each way. The last tenth
# of each side is kept clear, where the edge filtering is.
OFFSET_REACH_SHARE = 0.4

# Where a retuned signal lands: this share of the sampled band above the new
# centre. Not ON the centre, where an RTL dongle has its DC spike.
RETUNE_OFFSET_SHARE = 0.125

# A retuned centre is rounded down to this, and the channel offset takes the
# remainder. SDRangel's device dial shows the centre in kHz, so a centre of
# 11,000,115 reads "11000" and the 115 Hz looks lost; a centre on a whole kHz
# reads true, and centre plus offset still equals the rig exactly.
CENTRE_ROUNDING_HZ = 1000

# How long after connecting the RIG LEADS whatever SDRangel says. SDRangel
# answers over REST before it has finished applying its saved settings, and
# those can land on top of the frequency just sent -- observed: the rig on
# 21 MHz, SDRangel restoring its last 11 MHz, and the poll taking that for a
# click and pulling the rig there. A disagreement in this time is SDRangel
# settling, so the rig's frequency is sent again rather than SDRangel's
# reported. The same allowance as SDR_Link.CAPABILITY_RECHECK_MS, for the
# same reason: a program still starting answers badly about itself.
STARTUP_LEAD_SECONDS = 3.0

# The channel's volume and mute are read every this many polls -- once a
# second. They change only when someone turns SDRangel's own knob, and the
# settings block they live in is large; five times a second is the meter's
# rate, not theirs.
AUDIO_POLL_EVERY = 5

# SDRangel's `volume` is a LINEAR factor behind a logarithmic knob: 0.1 at
# its minimum, 1 by default, 10000 at its maximum. SDR_Link maps its slider
# linearly onto an SDR's range, so it is given dB instead -- as Gqrx gives
# it -- and the factor is converted at this edge only.
#
# 10 log10, not 20: SDRangel's knob reads -10 dB at 0.1 and +40 dB at 10000
# (seen on the knob; it shows -9 at the bottom, its own rounding of the
# float 0.100000001). The range is in the profile's volume_range, [-10, 40],
# so this application's figure is the one on SDRangel's knob.
# MODE AND FILTER ARE ONE THING IN SDRangel's SSB DEMODULATOR: its passband.
# Two fields, both in Hz from the tuned frequency, confirmed on the station:
#   rfBandwidth  "high cut" -- its SIGN is the sideband: +3000 USB, -3000 LSB
#   lowCutoff    "low cut"  -- the same sign as rfBandwidth; negative in LSB
# So LSB 300-2700 Hz is lowCutoff -300, rfBandwidth -2700. CW is the same
# demodulator with a narrow passband placed round the CW pitch. No channel is
# ever swapped: all four of the rig's modes live in this one demodulator.
#
# The span limits the passband. It is SPAN_BASE_HZ / 2**spanLog2 -- 6k at
# spanLog2 3, seen on the station -- and SDRangel's high-cut slider runs to
# the FULL span (it stops at 6k in a 6k span). Over REST, though, SDRangel
# takes a high cut past its span without complaint -- 10.1k was accepted in
# a 6k span, the slider simply pinned at its end -- and did not take a
# spanLog2 sent to widen it. So the span is the operator's, set in SDRangel,
# and the passband is kept inside it here: a wider request stops at the span.
SPAN_BASE_HZ = 48000

# THE DEMODULATOR'S DSP FUNCTIONS -- AGC and noise reduction -- each a switch
# and its adjustments, by the application's name for each: (field, lowest,
# highest) in the units SDRangel's dials show. Ranges read off the station.
#
#   AGC: the time constant is stored as a power of two -- agcTimeLog2 7 is
#   128 ms, the dial 16-2048 ms. Threshold in dB; the gate as the dial shows.
#   NR: the scheme picks which of avg, sigma and peaks applies -- 0 Average,
#   1 Avg Std Dev, 2 Peaks (all three confirmed on the station).
#   Alpha is SMOOTHING, stored as 1 - 10^(-n/10) for dial position n (0-40;
#   0 is none, stored 0): the 0.2056717... captured is exactly n = 1. See
#   _to_stored / _from_stored.
DSP_FUNCTIONS = {
    "agc": {
        "switch": "agc", "capability": AGC,
        "settings": {
            "time": ("agcTimeLog2", 4, 11),
            "threshold": ("agcPowerThreshold", -119, 0),
            "gate": ("agcThresholdGate", 0, 500),
        },
    },
    "nr": {
        "switch": "dnr", "capability": NR,
        "settings": {
            "scheme": ("dnrScheme", 0, 2),
            "avg": ("dnrAboveAvgFactor", 20, 99),
            "sigma": ("dnrSigmaFactor", 2, 16),
            "peaks": ("dnrNbPeaks", 1, 40),
            "alpha": ("dnrAlpha", 0, 40),       # FIX: from 0 -- no smoothing; the dial showed 0
        },
    },
}


# READ-ONLY adjustments: read and shown, never sent. dnrScheme is accepted
# over REST without error and NOT applied -- PATCHed to 2, it read back 0
# and SDRangel's own NR dialog stayed on Average (on the station). The
# scheme is chosen in that dialog, and followed here.
DSP_READ_ONLY = {("nr", "scheme")}


def _to_stored(function, name, value):
    """A dial value as SDRangel stores it."""
    if (function, name) == ("nr", "alpha"):
        return 1.0 - 10 ** (-float(value) / 10.0)
    return int(value)


def _from_stored(function, name, stored):
    """A stored value as the dial shows it, a whole number."""
    if (function, name) == ("nr", "alpha"):
        remainder = max(1.0 - float(stored), 1e-9)
        return int(round(-10.0 * math.log10(remainder)))
    return int(round(float(stored)))


# RF GAIN IS THE DEVICE'S, and each kind names and scales it its own way, so
# it is described per deviceHwType. A device not listed has no RF gain here:
# the control is greyed rather than guessed at.
#
# RTLSDR, confirmed on the station: rtlSdrSettings.gain in TENTHS of a dB
# (328 = 32.8 dB, 496 = 49.6 dB at the top), and rtlSdrSettings.agc, the
# dongle's own AGC -- while that is on the dongle sets its own gain and the
# field does nothing. The dongle takes gain in fixed steps; these are the
# R820T tuner's, the usual chip, and both values captured are among them.
RF_GAIN_DEVICES = {
    "RTLSDR": {
        "field": "gain", "per_db": 10, "auto": "agc",
        "steps": (0, 9, 14, 27, 37, 77, 87, 125, 144, 157, 166, 197, 207, 229,
                  254, 280, 297, 328, 338, 364, 372, 386, 402, 421, 434, 439,
                  445, 480, 496),
    },
}

# The CW pitch when the rig has not reported its tone. SDR_Link passes the
# rig's reported tone as cw_pitch before choosing a CW mode.
CW_PITCH_FALLBACK_HZ = 500

# SDRangel keeps the low cut on the high cut's side of zero and inside it,
# clamping one that is not. Both edges in one PATCH could arrive with the low
# cut checked against the OLD high cut -- -250 against +2700 when USB becomes
# CWL -- and be clamped, leaving only the high cut moved. So the high cut is
# sent first and the low cut after, and the next read checks that SDRangel
# kept both: a mismatch then is SDRangel's correction, not the operator's,
# and is sent again rather than reported to the rig. Tried this many times.
PASSBAND_RETRIES = 2

# SDRangel's low-cut and high-cut sliders move in 100 Hz steps, and what the
# slider can show is what it keeps: sent 250, it holds 200; sent -750, -700
# (seen on the station in CW). So the passband is put on that grid here, and
# asks only for what SDRangel can hold -- CW 500 Hz on a 500 Hz tone is
# 200-700, where SDRangel would have put it anyway.
PASSBAND_STEP_HZ = 100


def _volume_to_db(factor):
    return 10.0 * math.log10(max(float(factor), 1e-6))


def _db_to_volume(db):
    return 10.0 ** (float(db) / 10.0)


class ConnectionLost(Exception):
    """SDRangel refused the connection or closed it -- it has gone."""


class RestClient:
    """
    Requests to SDRangel's REST API.

    Two kinds of failure, kept apart as RigctlClient keeps them:

      * SDRangel ANSWERED, but not with what was asked -- a 4xx or 5xx, a
        reply that is not JSON, or no reply within the time. The request
        failed; the connection did not. Returns None or False.
      * Nothing is listening, or the connection broke. Raises ConnectionLost.
    """

    def __init__(self, reply_timeout=REPLY_TIMEOUT):
        self._base = None
        self.reply_timeout = reply_timeout
        # NO PROXY. urllib otherwise uses any proxy set in the environment,
        # and a request for 127.0.0.1 sent to a proxy fails in ways that
        # look nothing like "SDRangel is not running".
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @property
    def connected(self):
        return self._base is not None

    def open(self, host, port):
        """Whether SDRangel answers at this address."""
        self._base = f"http://{host}:{int(port)}/sdrangel"
        try:
            if isinstance(self.get(""), dict):
                return True
        except ConnectionLost:
            pass
        self.close()
        return False

    def close(self):
        self._base = None

    def get(self, path):
        """The JSON at a path, or None."""
        return self._send(urllib.request.Request(self._url(path), method="GET"))

    def patch(self, path, body):
        """A partial settings change. True if SDRangel accepted it."""
        request = urllib.request.Request(
            self._url(path), data=json.dumps(body).encode("utf-8"),
            method="PATCH", headers={"Content-Type": "application/json"})
        return self._send(request) is not None

    def post(self, path):
        """An action with no body -- starting a device. True if accepted."""
        request = urllib.request.Request(self._url(path), data=b"", method="POST")
        return self._send(request) is not None

    def delete(self, path):
        """The opposite action -- stopping a device. True if accepted."""
        request = urllib.request.Request(self._url(path), method="DELETE")
        return self._send(request) is not None

    def _url(self, path):
        if self._base is None:
            raise ConnectionLost("not connected")
        return self._base + path

    def _send(self, request):
        try:
            with self._opener.open(request, timeout=self.reply_timeout) as reply:
                text = reply.read()
        except urllib.error.HTTPError as err:
            # It answered, and refused. Said, because a refused PATCH is how
            # a wrong guess about SDRangel's JSON would show itself.
            print(f"[sdr] SDRangel refused {request.get_method()} "
                  f"{request.full_url}: {err.code} {err.reason}")
            return None
        except urllib.error.URLError as err:
            if isinstance(err.reason, TimeoutError):
                return None             # silence: this request failed
            self.close()
            raise ConnectionLost(str(err.reason))
        except TimeoutError:
            return None
        except OSError as err:
            self.close()
            raise ConnectionLost(str(err))
        if not text:
            return {}                   # accepted, with nothing to say
        try:
            return json.loads(text)
        except ValueError:
            return None


def _block_key(block, suffix):
    """
    The one key in a reply ending in `suffix` whose value is a block --
    "SSBDemodSettings", "rtlSdrSettings", "SSBDemodReport". Named after the
    hardware or channel type, so FOUND rather than looked up; anything but
    exactly one is refused.
    """
    if not isinstance(block, dict):
        return None
    keys = [key for key, value in block.items()
            if key.endswith(suffix) and isinstance(value, dict)]
    return keys[0] if len(keys) == 1 else None


def _settings_key(block):
    """
    The one key in a settings reply that holds the settings themselves.

    SDRangel names it after the hardware or channel type -- rtlSdrSettings,
    SSBDemodSettings -- so it is FOUND, not looked up in a table that would
    need an entry for every device. Anything but exactly one such key is
    refused: a guess here would PATCH the wrong block.
    """
    if not isinstance(block, dict):
        return None
    keys = [key for key, value in block.items()
            if key.endswith("Settings") and isinstance(value, dict)]
    return keys[0] if len(keys) == 1 else None


def _locate(listing):
    """
    Where the demodulator is, from the device-set list.

    Returns:
        (set index, channel index, channel type, centre Hz, offset Hz,
        band Hz) -- or None if there is no receiving device set with a
        receiving channel in it.

    THE BAND IS THE LIST'S "bandwidth" -- 64000 for an RTL dongle at
    1024000 samples a second decimated by 16, which is the sampled band a
    channel can be placed in. Checked against the device's own settings at
    discovery, where it has them to check against.
    """
    if not isinstance(listing, dict):
        return None
    for set_index, device_set in enumerate(listing.get("deviceSets") or ()):
        device = device_set.get("samplingDevice") or {}
        if device.get("direction", 0) != 0:
            continue                    # a transmitter
        for channel in device_set.get("channels") or ():
            if channel.get("direction", 0) != 0:
                continue
            try:
                return (set_index, int(channel["index"]), str(channel["id"]),
                        int(device["centerFrequency"]),
                        int(channel["deltaFrequency"]),
                        int(device["bandwidth"]))
            except (KeyError, TypeError, ValueError):
                return None
    return None


class RestSDR:
    """SDRangel, over its REST API."""

    def __init__(self, root, profile):
        self.root = root
        self.profile = profile
        self._client = RestClient()
        self._poll_id = None

        self.capabilities = frozenset()
        self.frequency = None
        self.mode = None
        self.filter_width = None
        self.signal = None
        self.volume = None
        self.muted = None
        # The demodulator's DSP functions -- see DSP_FUNCTIONS. On or off, and
        # their adjustments in dial units, by function; present only where
        # the demodulator has them. The AGC is the DEMODULATOR's
        # (SSBDemodSettings.agc) -- not the dongle's (rtlSdrSettings.agc),
        # which drives the RF gain and is left to the operator in SDRangel.
        self.dsp_on = {}
        self.dsp_settings = {}
        # The device's RF gain in dB, and whether its own AGC is setting it --
        # see RF_GAIN_DEVICES.
        self.rf_gain = None
        self.rf_gain_auto = None
        self._rf_spec = None
        self.squelch = None

        # Called with the new value when it changes in the SDR itself.
        self.on_frequency = None
        self.on_mode = None
        self.on_filter = None
        self.on_signal = None
        self.on_volume = None
        self.on_mute = None
        self.on_dsp = None              # called with the function's name: "agc", "nr"
        self.on_rf_gain = None          # no arguments: gain or its AGC changed
        self.on_squelch = None
        self.on_disconnect = None

        # WHERE THE DEMODULATOR IS, found by discovery. The paths below are
        # built from these.
        self._set_index = None
        self._channel_index = None
        self._channel_type = None       # "SSBDemod"
        self._channel_key = None        # "SSBDemodSettings"
        self._hw_type = None            # "RTLSDR"
        self._hw_key = None             # "rtlSdrSettings"
        self._device_direction = 0

        # The tuning pair as last read or set, and the band it lives in.
        self._centre = None
        self._offset = None
        self._band = None

        self._quiet_until = 0.0         # see SETTLE_SECONDS
        self._lead_until = 0.0          # see STARTUP_LEAD_SECONDS
        self._wanted = None             # the frequency last sent -- the rig's
        self._settling_said = False
        self._polls = 0                 # see AUDIO_POLL_EVERY
        self._missing_said = False      # the demodulator vanished; said once
        # WHY THE LAST connect() FAILED: "unreachable" (no answer) or
        # "nothing to tune" (it answered, but has no receiving device set with
        # a channel). SDR_Link reported both as "could not reach", which sent
        # the operator looking at the network when SDRangel was running.
        self.last_failure = None
        self._nothing_said = False      # "nothing to tune", said once

        # The passband as last read or written, as magnitudes -- see the
        # note above SPAN_BASE_HZ. The mode's sideband is kept apart, since
        # CW and SSB share one: the passband alone cannot say which it is.
        self._sideband = None           # "U" or "L"
        self._low = None                # low cut, Hz
        self._high = None               # high cut, Hz
        self._span_log2 = None
        self._ssb_low = 0               # the operator's SSB low cut, kept
        self.cw_pitch = None            # set by SDR_Link: the rig's CW tone
        self._passband_check = None     # (mode, width, tries) -- see PASSBAND_RETRIES

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
    # Connecting, and finding the demodulator
    # ------------------------------------------------------------------
    def connect(self, host, port):
        """
        Connects, and finds the demodulator to drive.

        Returns False if SDRangel does not answer, or has nothing this can
        tune -- no receiving device set with a channel in it.
        """
        self.disconnect()
        self.last_failure = "unreachable"
        if not self._client.open(host, port):
            return False
        # FIX: forgotten, so discovery reads it afresh -- see discover().
        self.frequency = None
        self._wanted = None
        try:
            if not self.discover():
                self.last_failure = "nothing to tune"
                self._client.close()
                return False
        except ConnectionLost:
            return False
        self.last_failure = None
        self._lead_until = time.monotonic() + STARTUP_LEAD_SECONDS
        self._settling_said = False
        self._poll_id = self.root.after(POLL_MS, self._poll)
        return True

    def discover(self):
        """
        Finds the demodulator and the device it listens through. READS ONLY.

        Nothing is kept unless everything is found: called again later --
        SDR_Link asks a few seconds after connecting -- a failure leaves
        what was found before in place.

        Returns False, saying why, if there is nothing to tune.
        """
        client = self._client
        located = _locate(client.get("/devicesets"))
        if located is None:
            # FIX: "yet" -- SDRangel answers before its saved device sets
            # are loaded, so this is usual while it starts, and the next
            # attempt normally finds them.
            if not self._nothing_said:
                self._nothing_said = True
                print("[sdr] SDRangel is answering, but has no receiving device "
                      "set with a channel in it yet -- still loading, or it "
                      "needs a demodulator (SSB). Waiting for one.")
            return False
        set_index, channel_index, channel_type, centre, offset, band = located

        device = client.get(f"/deviceset/{set_index}/device/settings")
        hw_key = _settings_key(device)
        if hw_key is None:
            print(f"[sdr] SDRangel's device settings for device set {set_index} "
                  f"are not in a shape this recognises")
            return False

        path = f"/deviceset/{set_index}/channel/{channel_index}/settings"
        channel = client.get(path)
        channel_key = _settings_key(channel)
        if channel_key is None:
            print(f"[sdr] SDRangel's settings for channel {channel_index} are not "
                  f"in a shape this recognises")
            return False

        # THE POLL READS THE OFFSET FROM THE DEVICE-SET LIST, one request for
        # both halves of the pair. That rests on the list's deltaFrequency
        # being the channel's inputFrequencyOffset -- observed equal at 0, not
        # yet seen to move together. Checked here, and refused if not: a
        # frequency built from the wrong number would send the rig somewhere
        # plausible and wrong.
        settings = channel[channel_key]
        if settings.get("inputFrequencyOffset") != offset:
            print(f"[sdr] SDRangel's channel offset reads {offset} Hz in the "
                  f"device-set list but {settings.get('inputFrequencyOffset')} Hz "
                  f"in its settings; not connecting until that is understood")
            return False

        # And the band against the device's own sample rate and decimation,
        # where it has them -- an RTL dongle does.
        hardware = device[hw_key]
        rate, decimation = hardware.get("devSampleRate"), hardware.get("log2Decim")
        if isinstance(rate, int) and isinstance(decimation, int):
            expected = rate // (2 ** decimation)
            if expected != band:
                print(f"[sdr] note: SDRangel reports a {band} Hz band, but "
                      f"{rate} / 2^{decimation} is {expected} Hz; using {band}")

        if (set_index, channel_index) != (self._set_index, self._channel_index):
            print(f"[sdr] driving SDRangel device set {set_index} "
                  f"({device.get('deviceHwType')}), channel {channel_index} "
                  f"({channel_type}); the sampled band is {band} Hz wide")

        self._set_index, self._channel_index = set_index, channel_index
        self._channel_type, self._channel_key = channel_type, channel_key
        self._hw_type, self._hw_key = device.get("deviceHwType"), hw_key
        self._device_direction = device.get("direction", 0)
        self._centre, self._offset, self._band = centre, offset, band
        # FIX: only when not known. Rediscovery -- SDR_Link asks again three
        # seconds after connecting -- used to adopt SDRangel's frequency
        # silently, so a disagreement at that moment was never seen by the
        # poll, and rig and SDRangel stayed apart.
        if self.frequency is None:
            self.frequency = centre + offset
        self._missing_said = False
        self._nothing_said = False

        caps = {FREQUENCY}
        # SIGNAL: the channel's report carries its power. Offered only if
        # this channel's report has a number there.
        level = self._read_report(set_index, channel_index)
        if level is not None:
            caps.add(SIGNAL)
            self.signal = level
        # VOLUME and MUTE: fields of the channel's own settings, already read
        # above. Offered where this channel type has them -- SSBDemod does.
        if isinstance(settings.get("volume"), (int, float)):
            caps.add(VOLUME)
            self.volume = round(_volume_to_db(settings["volume"]), 1)
        if settings.get("audioMute") in (0, 1, True, False):
            caps.add(MUTE)
            self.muted = bool(settings["audioMute"])
        # RF GAIN: the device's -- see RF_GAIN_DEVICES.
        spec = RF_GAIN_DEVICES.get(self._hw_type)
        if spec and isinstance(hardware.get(spec["field"]), (int, float)):
            caps.add(RF_GAIN)
            self._rf_spec = spec
            self._take_rf_gain(hardware)
        # AGC and NR: the demodulator's own switches -- see DSP_FUNCTIONS.
        for function, spec in DSP_FUNCTIONS.items():
            if settings.get(spec["switch"]) in (0, 1, True, False):
                caps.add(spec["capability"])
                self.dsp_on[function] = bool(settings[spec["switch"]])
                self.dsp_settings[function] = {}
                self._take_dsp_settings(function, settings)
        # MODE and FILTER: the passband -- see the note above SPAN_BASE_HZ.
        rf, lc, span = (settings.get("rfBandwidth"), settings.get("lowCutoff"),
                        settings.get("spanLog2"))
        if all(isinstance(v, (int, float)) for v in (rf, lc, span)):
            caps.update((MODE, FILTER))
            self._span_log2 = int(span)
            self._take_passband(rf, lc)
            if self._sideband and self.mode is None:
                self.mode = "LSB" if self._sideband == "L" else "USB"
            if self.mode in ("USB", "LSB"):
                self._ssb_low = self._low
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

    # ------------------------------------------------------------------
    # Starting and stopping the device
    #
    # SDR_Link decides WHEN, by the same rules as for every program: start()
    # on every connect, as Gqrx's receiver is started; stop() only from
    # close_program() and a switch of program -- never on a plain
    # disconnect, which leaves an operator's SDRangel running as it was.
    # ------------------------------------------------------------------
    def _run_path(self):
        return f"/deviceset/{self._set_index}/device/run"

    # How long after asking the device to start to look whether it did. The
    # POST is answered before the device is up -- its reply still says
    # "idle" -- so the state is read again rather than taken from the reply.
    START_CHECK_MS = 1000

    def device_state(self):
        """
        SDRangel's word for the device, or None.

        Seen so far: "idle" before it was ever started, "ready" after a stop
        (opened, not streaming), and "running". Only "running" means
        streaming; anything else is treated as not.
        """
        try:
            reply = self._client.get(self._run_path())
        except ConnectionLost:
            self._lost()
            return None
        return reply.get("state") if isinstance(reply, dict) else None

    def start(self):
        """
        Starts the device streaming, unless it already is.

        Asked first rather than started blind: a POST to a running device is
        at best a no-op, and whether SDRangel treats it as one is not
        something to find out on the operator's receiver.
        """
        if not self.is_connected or self._set_index is None:
            return False
        if self.device_state() == "running":
            return True
        try:
            ok = self._client.post(self._run_path())
        except ConnectionLost:
            self._lost()
            return False
        if not ok:
            print("[sdr] SDRangel's device did not start")
            return False
        print("[sdr] asked SDRangel's device to start")
        self.root.after(self.START_CHECK_MS, self._report_start)
        return True

    def _report_start(self):
        """Says whether the device came up -- the POST's own reply cannot."""
        if not self.is_connected:
            return
        state = self.device_state()
        if state == "running":
            print("[sdr] SDRangel's device is running")
        else:
            print(f"[sdr] SDRangel's device did not come up (state {state!r}) -- "
                  f"is another program holding the dongle?")

    def stop(self):
        """Stops the device streaming, if it is."""
        if not self.is_connected or self._set_index is None:
            return True
        if self.device_state() != "running":
            return True                 # "idle" and "ready" are both stopped
        try:
            ok = self._client.delete(self._run_path())
        except ConnectionLost:
            self._lost()
            return False
        print(f"[sdr] SDRangel's device {'stopped' if ok else 'did not stop'}")
        return ok

    # ------------------------------------------------------------------
    # Frequency
    # ------------------------------------------------------------------
    def set_frequency(self, hz):
        """
        Tunes SDRangel to a frequency -- by the channel offset where the
        signal stays well inside the sampled band, else by retuning the
        centre and resetting the offset.

        RECORDS WHAT SDRANGEL WAS LEFT AT, not what was asked for. If the
        centre moved and the offset then failed, SDRangel is somewhere new;
        recording the request instead would make the next poll report that
        somewhere as a click in SDRangel, and the rig would be pulled there.
        """
        if not self.is_connected or self._band is None:
            return False
        hz = int(hz)
        self._wanted = hz               # the rig's, for STARTUP_LEAD_SECONDS
        reach = int(self._band * OFFSET_REACH_SHARE)
        try:
            # FIX: a centre off a whole kHz -- left by an earlier session, or
            # set over the API -- is retuned once rather than kept, or its
            # odd Hz ride along in every offset and SDRangel's kHz dial
            # never reads true. See CENTRE_ROUNDING_HZ.
            if (abs(hz - self._centre) <= reach
                    and self._centre % CENTRE_ROUNDING_HZ == 0):
                if self._patch_offset(hz - self._centre):
                    self._offset = hz - self._centre
            else:
                centre = hz - int(self._band * RETUNE_OFFSET_SHARE)
                # FIX: down to a whole kHz -- see CENTRE_ROUNDING_HZ. Down,
                # so the offset only grows, by under a kHz, and stays well
                # inside OFFSET_REACH_SHARE.
                centre -= centre % CENTRE_ROUNDING_HZ
                if self._patch_centre(centre):
                    self._centre = centre
                    if self._patch_offset(hz - centre):
                        self._offset = hz - centre
        except ConnectionLost:
            self._lost()
            return False
        self.frequency = self._centre + self._offset
        self._quiet_until = time.monotonic() + SETTLE_SECONDS
        return self.frequency == hz

    def _patch_offset(self, offset):
        return self._patch_channel({"inputFrequencyOffset": int(offset)})

    def _patch_channel(self, fields):
        """A partial change to the channel's own settings."""
        return self._client.patch(
            f"/deviceset/{self._set_index}/channel/{self._channel_index}/settings",
            {"channelType": self._channel_type, "direction": 0,
             self._channel_key: fields})

    def _patch_device(self, fields):
        """A partial change to the device's own settings."""
        return self._client.patch(
            f"/deviceset/{self._set_index}/device/settings",
            {"deviceHwType": self._hw_type, "direction": self._device_direction,
             self._hw_key: fields})

    def _patch_centre(self, centre):
        return self._client.patch(
            f"/deviceset/{self._set_index}/device/settings",
            {"deviceHwType": self._hw_type, "direction": self._device_direction,
             self._hw_key: {"centerFrequency": int(centre)}})

    # ------------------------------------------------------------------
    # Not yet -- each answers "cannot", so the interface greys it out
    # ------------------------------------------------------------------
    def set_mode(self, sdr_mode, width=0):
        """
        Chooses the mode -- which here is where the passband sits.

        USB and CWU put it above the tuned frequency, LSB and CWL below. SSB
        keeps the operator's low cut and sets the high cut `width` above it;
        CW centres a passband `width` wide on the CW pitch.
        """
        if MODE not in self.capabilities:
            return False
        mode = str(sdr_mode).upper()
        if mode not in ("USB", "LSB", "CWU", "CWL"):
            return False
        width = int(width) if width else self.default_filter_width(mode)
        if not self._write_passband(mode, width):
            return False
        self.mode = mode
        return True

    def set_filter_width(self, width):
        """Narrows or widens the passband, in the current mode."""
        if FILTER not in self.capabilities or self.mode is None:
            return False
        return self._write_passband(self.mode, int(width))

    def _passband_for(self, mode, width):
        """(low, high) magnitudes, in Hz, for a mode and a width."""
        step = PASSBAND_STEP_HZ
        width = max(step, int(round(int(width) / step)) * step)
        if mode.startswith("CW"):
            pitch = int(self.cw_pitch or CW_PITCH_FALLBACK_HZ)
            low = max(0, int((pitch - width / 2) // step) * step)
        else:
            low = int(round(int(self._ssb_low or 0) / step)) * step
        high = low + width
        # Inside the span -- see the note above SPAN_BASE_HZ. On the grid, so
        # the edge is one SDRangel's slider can show.
        if self._span_log2 is not None:
            span = int(SPAN_BASE_HZ / 2 ** self._span_log2) // step * step
            if high > span:
                high = span
                low = min(low, high - step)
        return low, high

    def _write_passband(self, mode, width, tries=0):
        """
        PATCHes the passband, kept inside the span -- see SPAN_BASE_HZ.
        High cut first, low cut second: see PASSBAND_RETRIES.
        """
        low, high = self._passband_for(mode, width)
        sideband = "L" if mode in ("LSB", "CWL") else "U"
        sign = -1 if sideband == "L" else 1
        first = {"rfBandwidth": sign * high}
        try:
            ok = (self._patch_channel(first)
                  and self._patch_channel({"lowCutoff": sign * low}))
        except ConnectionLost:
            self._lost()
            return False
        self._passband_check = (mode, width, tries) if ok else None
        if ok:
            # Recorded as written, so the next read does not report it back.
            self._sideband, self._low, self._high = sideband, low, high
            self.filter_width = high - low
            if not mode.startswith("CW"):
                self._ssb_low = low
        return ok

    def _passband_check_failed(self, rf, lc):
        """
        After a write, whether SDRangel kept the passband sent. If not, it
        is SDRangel's correction, not the operator's: sent again, up to
        PASSBAND_RETRIES times, and never reported to the rig. Returns True
        while that is going on, so the caller reads nothing into it.
        """
        if self._passband_check is None:
            return False
        mode, width, tries = self._passband_check
        sign = -1 if self._sideband == "L" else 1
        wanted = (sign * self._high, sign * self._low)
        held = (int(rf), int(lc))
        if held == wanted:
            self._passband_check = None
            return False
        if tries < PASSBAND_RETRIES:
            print(f"[sdr] SDRangel holds high cut {held[0]}, low cut {held[1]} "
                  f"after being sent {wanted[0]}, {wanted[1]} for {mode}; "
                  f"sending it again")
            self._write_passband(mode, width, tries + 1)
            return True
        print(f"[sdr] SDRangel will not hold high cut {wanted[0]}, low cut "
              f"{wanted[1]} for {mode}; it keeps {held[0]}, {held[1]}")
        self._passband_check = None
        # Adopted as SDRangel's, silently: reporting it would move the rig
        # because of a correction the operator never made.
        self._take_passband(rf, lc)
        return True

    def _take_passband(self, rf, lc):
        """
        Records a passband read from SDRangel. Returns (sideband changed,
        width changed). A high cut of 0 is no passband at all -- the knob
        dragged through zero -- and is ignored rather than read as a mode.
        """
        if rf == 0:
            return False, False
        sideband = "L" if rf < 0 else "U"
        low, high = abs(int(lc)), abs(int(rf))
        sideband_changed = self._sideband is not None and sideband != self._sideband
        width_changed = (self._low, self._high) != (low, high)
        self._sideband, self._low, self._high = sideband, low, high
        self.filter_width = high - low
        return sideband_changed, width_changed

    def set_level(self, level, value):
        """
        Sets a level SDR_Link asks for by rigctl's name. Only "AF", the
        channel's volume, in dB -- see _volume_to_db. Recorded on success,
        so the next audio poll does not report it back.
        """
        if level != "AF" or VOLUME not in self.capabilities:
            return False
        db = float(value)
        try:
            ok = self._patch_channel({"volume": _db_to_volume(db)})
        except ConnectionLost:
            self._lost()
            return False
        if ok:
            self.volume = round(db, 1)
        return ok

    def get_level(self, level):
        """
        A level read fresh. Only "STRENGTH" so far -- the channel's power,
        in dB, as SDR_Link's auto-squelch asks for it.
        """
        if level != "STRENGTH" or SIGNAL not in self.capabilities:
            return None
        try:
            return self._read_report(self._set_index, self._channel_index)
        except ConnectionLost:
            self._lost()
            return None

    def rf_gain_range(self):
        """(lowest, highest) RF gain in dB, or None without one."""
        if not self._rf_spec:
            return None
        steps = self._rf_spec["steps"]
        return steps[0] / self._rf_spec["per_db"], steps[-1] / self._rf_spec["per_db"]

    def rf_gain_steps(self):
        """The device's gain steps, in dB, lowest first."""
        if not self._rf_spec:
            return []
        return [step / self._rf_spec["per_db"] for step in self._rf_spec["steps"]]

    def snap_rf_gain(self, db):
        """The device's nearest gain step to `db`, in dB."""
        if not self._rf_spec:
            return None
        per_db = self._rf_spec["per_db"]
        raw = min(self._rf_spec["steps"], key=lambda step: abs(step - float(db) * per_db))
        return raw / per_db

    def set_rf_gain(self, db):
        """Sets the device's RF gain, at its nearest step."""
        if RF_GAIN not in self.capabilities:
            return False
        db = self.snap_rf_gain(db)
        raw = int(round(db * self._rf_spec["per_db"]))
        try:
            ok = self._patch_device({self._rf_spec["field"]: raw})
        except ConnectionLost:
            self._lost()
            return False
        if ok:
            self.rf_gain = db
        return ok

    def _take_rf_gain(self, hardware):
        """Records the gain and its AGC from device settings; True if either changed."""
        spec = self._rf_spec
        gain = hardware.get(spec["field"])
        auto = hardware.get(spec["auto"]) if spec.get("auto") else None
        changed = False
        if isinstance(gain, (int, float)):
            db = gain / spec["per_db"]
            if db != self.rf_gain:
                self.rf_gain, changed = db, True
        if auto in (0, 1, True, False) and bool(auto) != self.rf_gain_auto:
            self.rf_gain_auto, changed = bool(auto), True
        return changed

    def _read_rf_gain(self):
        """Reads the device's gain, and reports one changed in SDRangel."""
        block = self._client.get(f"/deviceset/{self._set_index}/device/settings")
        if isinstance(block, dict) and isinstance(block.get(self._hw_key), dict):
            if self._take_rf_gain(block[self._hw_key]):
                self._call(self.on_rf_gain)

    def dsp_range(self, function, name):
        """(lowest, highest) of an adjustment, in dial units -- see DSP_FUNCTIONS."""
        _, low, high = DSP_FUNCTIONS[function]["settings"][name]
        return low, high

    def dsp_adjustable(self, function, name):
        """Whether an adjustment can be set from here -- see DSP_READ_ONLY."""
        return (function, name) not in DSP_READ_ONLY

    def set_dsp_setting(self, function, name, value):
        """Sets one adjustment, within its range, in dial units."""
        if name not in self.dsp_settings.get(function, {}):
            return False
        if not self.dsp_adjustable(function, name):
            return False
        field, low, high = DSP_FUNCTIONS[function]["settings"][name]
        value = int(round(max(low, min(high, float(value)))))
        try:
            ok = self._patch_channel({field: _to_stored(function, name, value)})
        except ConnectionLost:
            self._lost()
            return False
        if ok:
            self.dsp_settings[function][name] = value
        return ok

    def _take_dsp_settings(self, function, settings):
        """Records a function's adjustments from channel settings; True if any changed."""
        changed = False
        held = self.dsp_settings.setdefault(function, {})
        for name, (field, _, _) in DSP_FUNCTIONS[function]["settings"].items():
            stored = settings.get(field)
            if isinstance(stored, (int, float)):
                value = _from_stored(function, name, stored)
                if held.get(name) != value:
                    held[name] = value
                    changed = True
        return changed

    def set_dsp(self, function, on):
        """A DSP function -- "agc" or "nr" -- on or off."""
        spec = DSP_FUNCTIONS.get(function)
        if not spec or spec["capability"] not in self.capabilities:
            return False
        try:
            ok = self._patch_channel({spec["switch"]: 1 if on else 0})
        except ConnectionLost:
            self._lost()
            return False
        if ok:
            self.dsp_on[function] = bool(on)
        return ok

    def set_mute(self, muted):
        """The channel's own mute -- silences SDRangel and nothing else."""
        if MUTE not in self.capabilities:
            return False
        try:
            ok = self._patch_channel({"audioMute": 1 if muted else 0})
        except ConnectionLost:
            self._lost()
            return False
        if ok:
            self.muted = bool(muted)
        return ok

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------
    def _poll(self):
        """Reads where SDRangel is tuned, and reports a change made there."""
        self._poll_id = None
        if not self.is_connected:
            return
        try:
            self._read_frequency()
            if SIGNAL in self.capabilities:
                self._read_signal()
            self._polls += 1
            if (self._polls % AUDIO_POLL_EVERY == 0
                    and self.capabilities & {VOLUME, MUTE, MODE, FILTER, AGC, NR}):
                self._read_audio()
            if (self._polls % AUDIO_POLL_EVERY == 0
                    and RF_GAIN in self.capabilities):
                self._read_rf_gain()
        except ConnectionLost:
            self._lost()
            return
        self._poll_id = self.root.after(POLL_MS, self._poll)

    def _read_frequency(self):
        if time.monotonic() < self._quiet_until:
            return                      # our own change may not show yet
        located = _locate(self._client.get("/devicesets"))
        if located is None:
            if not self._missing_said:
                print("[sdr] SDRangel's demodulator has gone; waiting for one")
                self._missing_said = True
            return
        set_index, channel_index, _, centre, offset, band = located
        before = self.frequency
        if (set_index, channel_index) != (self._set_index, self._channel_index):
            # A different channel is now the first: find out about it before
            # reading it, so a PATCH never goes to a channel not looked at.
            if not self.discover():
                return
            centre, offset, band = self._centre, self._offset, self._band
        self._missing_said = False
        self._centre, self._offset, self._band = centre, offset, band
        hz = centre + offset

        # FIX: THE RIG LEADS WHILE SDRANGEL SETTLES -- see
        # STARTUP_LEAD_SECONDS. Nothing is reported; the rig's frequency is
        # sent again, and set_frequency records where that leaves SDRangel.
        if (hz != before and time.monotonic() < self._lead_until
                and self._wanted is not None):
            if hz != self._wanted:
                if not self._settling_said:
                    print(f"[sdr] SDRangel moved to {hz} while still starting; "
                          f"sending the rig's {self._wanted} again")
                    self._settling_said = True
                self.set_frequency(self._wanted)
            else:
                self.frequency = hz
            return

        # Against the frequency BEFORE any rediscovery: a different channel
        # is a different frequency the rig should follow.
        self.frequency = hz
        if hz != before:
            self._call(self.on_frequency, hz)

    # ------------------------------------------------------------------
    # Signal
    # ------------------------------------------------------------------
    def _read_report(self, set_index, channel_index):
        """
        The channel's power from its report, in dB, or None.

        GET .../channel/{n}/report answers {"SSBDemodReport":
        {"channelPowerDB": -150}, ...} -- the block named after the channel
        type, found the same way as a settings block.
        """
        report = self._client.get(
            f"/deviceset/{set_index}/channel/{channel_index}/report")
        key = _block_key(report, "Report")
        if key is None:
            return None
        value = report[key].get("channelPowerDB")
        return float(value) if isinstance(value, (int, float)) else None

    def _read_audio(self):
        """
        Reads the channel's volume, mute and passband, and reports a change
        made in SDRangel -- so the application's controls follow its knobs.

        Compared in dB to a tenth, the precision set_level records: SDRangel
        stores the factor as a float, and 0.1 comes back 0.100000001.
        """
        block = self._client.get(
            f"/deviceset/{self._set_index}/channel/{self._channel_index}/settings")
        key = _settings_key(block)
        if key is None:
            return
        settings = block[key]
        if VOLUME in self.capabilities and isinstance(settings.get("volume"), (int, float)):
            db = round(_volume_to_db(settings["volume"]), 1)
            if db != self.volume:
                self.volume = db
                self._call(self.on_volume, db)
        if MUTE in self.capabilities and settings.get("audioMute") in (0, 1, True, False):
            muted = bool(settings["audioMute"])
            if muted != self.muted:
                self.muted = muted
                self._call(self.on_mute, muted)
        for function, spec in DSP_FUNCTIONS.items():
            if (spec["capability"] in self.capabilities
                    and settings.get(spec["switch"]) in (0, 1, True, False)):
                on = bool(settings[spec["switch"]])
                adjusted = self._take_dsp_settings(function, settings)
                if on != self.dsp_on.get(function) or adjusted:
                    self.dsp_on[function] = on
                    self._call(self.on_dsp, function)
        # The passband, changed at SDRangel's own knobs: the high cut dragged
        # across zero is a change of sideband -- CWU to CWL if in CW, USB to
        # LSB otherwise -- and any other move is a new width.
        if MODE in self.capabilities:
            rf, lc = settings.get("rfBandwidth"), settings.get("lowCutoff")
            if isinstance(rf, (int, float)) and isinstance(lc, (int, float)):
                if isinstance(settings.get("spanLog2"), (int, float)):
                    self._span_log2 = int(settings["spanLog2"])
                if self._passband_check_failed(rf, lc):
                    return
                sideband_changed, width_changed = self._take_passband(rf, lc)
                if sideband_changed:
                    cw = bool(self.mode) and self.mode.startswith("CW")
                    lower = self._sideband == "L"
                    self.mode = ("CWL" if lower else "CWU") if cw else ("LSB" if lower else "USB")
                    self._call(self.on_mode, self.mode)
                if self.mode in ("USB", "LSB") and self._low is not None:
                    self._ssb_low = self._low
                if width_changed:
                    self._call(self.on_filter, self.filter_width)

    def _read_signal(self):
        """Reads the signal and reports it -- every poll, as RigctlSDR does."""
        level = self._read_report(self._set_index, self._channel_index)
        if level is not None:
            self.signal = level
            self._call(self.on_signal, level)

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
