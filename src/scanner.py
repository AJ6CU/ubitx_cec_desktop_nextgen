#!/usr/bin/python3
"""
Scanner -- steps through a set of channels, listening to each in turn.

RUN BY THE APPLICATION, NOT THE SDR

Some SDRs cannot scan, and the ones that can each do it differently. So the
application scans: it tunes the RIG to each channel in turn, through the same
uBITX_Link.tune_to() a double-click uses, and whichever SDR is attached
follows the rig as it does for any other change. Scanning therefore works with
any SDR, or none.

WHAT IT SCANS

The channels it is handed, fetched afresh at every step rather than copied at
the start -- so a channel edited or deleted mid-scan is honoured on the next
pass, not replayed from a stale list. Channels with no frequency are skipped.

WHEN IT STOPS BY ITSELF

  * Transmitting. It must never retune while the operator is on the air.
  * The frequency changes under it -- the dial turned, or the rig tuned from
    its own panel. The operator has taken the radio back.

Telling the second apart from its own retuning takes care: straight after a
retune the rig is still reporting the OLD frequency, which is not the operator
at all. So a step is "settling" until the rig reports the frequency asked
for, and only a change after that counts as someone else's.

FIX (2026-11-06): IT CAN STOP ON A SIGNAL. Two ways to scan, the operator's
choice:

  * BY TIME -- each channel for the dwell, the operator pressing Stop on one
    worth staying on. As before.
  * ON A SIGNAL -- each channel for the dwell, but one whose signal reaches
    the threshold is HELD: the scan waits there as long as the signal stays,
    and moves on SIGNAL_HANG_MS after it drops. Stop still works throughout.

The level comes from whatever the owner hands in -- the SDR's reading when
listening through it, the radio S-meter sensor when listening through the rig
-- in S-units on the meter's scale. None means no reading (SDR++ has none):
then the scan goes by time alone. A reading is trusted only SIGNAL_SETTLE_MS
after the rig has reported the new channel -- before that it may still be
the last channel's signal.
"""
import time

# The least time on a channel. A retune is a frequency command and, 150 ms
# later, a mode command -- see tune_to -- so anything much shorter would be
# moving on before the rig had arrived.
MIN_DWELL_SECONDS = 1
MAX_DWELL_SECONDS = 120

# How long a step may wait for the rig to report the frequency asked for
# before it is treated as settled anyway. The rig normally answers within a
# fraction of a second; this only stops a lost report from leaving the
# manual-retune check switched off for good.
SETTLE_TIMEOUT_MS = 2000

# FIX (2026-11-06): stopping on a signal. How often it is looked at; how
# long after arriving before it is believed (the SDR's reading lags a
# retune); how long after it drops the scan waits before moving on -- a gap
# between words is not the end of a contact.
SIGNAL_POLL_MS = 250
SIGNAL_SETTLE_MS = 700
SIGNAL_HANG_MS = 3000


class Scanner:
    """Steps through a set's channels, tuning the rig to each in turn."""

    def __init__(self, root, model, rig):
        """
        Args:
            root: The Tk root, for timing.
            model: The RadioModel -- watched for transmitting and for the
                frequency changing under the scan.
            rig: The uBITX_Link, whose tune_to() does each retune.
        """
        self.root = root
        self._model = model
        self._rig = rig

        self.running = False
        self.index = None             # the channel being listened to
        self._channels = None         # a function returning the current list
        self._dwell_ms = 5000
        self._timer = None
        self._expected_hz = None      # what the rig was last told
        self._settled = False         # has the rig reported it yet
        self._settle_timer = None
        # Stopping on a signal -- see the module docstring.
        self._signal = None           # a function: S-units, or None
        self._threshold = None        # None: scan by time
        self._poll_timer = None
        self._settled_at = None       # monotonic time the rig arrived
        self.holding = False          # waiting on a channel with a signal
        self._below_since = None

        # Called with the index each time a channel is reached, and with None
        # and a reason when the scan stops. Set by the owner. on_hold: called
        # with (index, level) when a signal holds the scan, (index, None)
        # when it moves on again.
        self.on_step = None
        self.on_stop = None
        self.on_hold = None

    # ------------------------------------------------------------------
    def start(self, channels, start_index=0, dwell_seconds=5,
              signal=None, threshold=None):
        """
        Starts scanning.

        Args:
            channels: A function returning the channels to scan, each a dict
                with "freq" and "mode". Called at every step.
            start_index: The channel to begin with.
            dwell_seconds: Time on each channel.
            signal: A function returning the signal in S-units, or None.
            threshold: Hold on a channel whose signal reaches this many
                S-units; None scans by time alone.
        """
        self.stop(None)
        self._channels = channels
        self._signal = signal
        self._threshold = threshold if signal is not None else None
        self._dwell_ms = int(max(MIN_DWELL_SECONDS,
                                 min(MAX_DWELL_SECONDS, float(dwell_seconds))) * 1000)
        if self._model.transmitting:
            self._stopped("transmitting")
            return
        first = self._next_usable(int(start_index or 0), inclusive=True)
        if first is None:
            self._stopped("nothing to scan -- every channel is empty")
            return
        self.running = True
        self._go_to(first)

    def stop(self, reason="stopped"):
        """Stops scanning. `reason` is reported to on_stop; None reports nothing."""
        was_running = self.running
        self.running = False
        self.holding = False
        for timer in ("_timer", "_settle_timer", "_poll_timer"):
            handle = getattr(self, timer)
            if handle is not None:
                try:
                    self.root.after_cancel(handle)
                except Exception:
                    pass
                setattr(self, timer, None)
        self._expected_hz = None
        self.index = None
        if was_running and reason is not None:
            self._stopped(reason)

    def skip(self):
        """
        FIX (2026-11-06): moves on to the next channel now -- the operator
        has heard enough of this one, held on a signal or not. The scan
        carries on from there as usual.
        """
        if not self.running:
            return
        if self._timer is not None:
            try:
                self.root.after_cancel(self._timer)
            except Exception:
                pass
            self._timer = None
        if self.holding:
            self.holding = False
            if callable(self.on_hold):
                self.on_hold(self.index, None)
        self._advance()

    def _stopped(self, reason):
        if callable(self.on_stop):
            self.on_stop(reason)

    # ------------------------------------------------------------------
    def _next_usable(self, start, inclusive=False):
        """
        The next channel with a frequency, from `start`, wrapping round --
        or None if there is none at all.
        """
        channels = self._channels() if self._channels else []
        count = len(channels)
        if not count:
            return None
        first = start if inclusive else start + 1
        for offset in range(count):
            i = (first + offset) % count
            if channels[i].get("freq"):
                return i
        return None

    def _go_to(self, index):
        """Tunes to a channel, and schedules the next."""
        channels = self._channels()
        if not self.running or not 0 <= index < len(channels):
            return
        channel = channels[index]
        self.index = index
        self._expected_hz = int(channel["freq"])
        self._settled = False
        self._settled_at = None
        self.holding = False
        self._below_since = None
        # The previous channel's settle timer, if it has not fired, must go:
        # left running, it would mark THIS channel settled before the rig had
        # arrived, and the old frequency still being reported would then look
        # like the operator tuning away -- stopping the scan by itself.
        if self._settle_timer is not None:
            try:
                self.root.after_cancel(self._settle_timer)
            except Exception:
                pass
            self._settle_timer = None
        self._rig.tune_to(self._expected_hz, channel.get("mode"))
        self._settle_timer = self.root.after(SETTLE_TIMEOUT_MS, self._settle_anyway)
        if callable(self.on_step):
            self.on_step(index)
        self._timer = self.root.after(self._dwell_ms, self._advance)
        if self._threshold is not None and self._poll_timer is None:
            self._poll_timer = self.root.after(SIGNAL_POLL_MS, self._poll_signal)

    def _settle_anyway(self):
        self._settle_timer = None
        self._mark_settled()

    def _mark_settled(self):
        if not self._settled:
            self._settled = True
            self._settled_at = time.monotonic()

    def _poll_signal(self):
        """
        FIX (2026-11-06): holds the scan on a channel with a signal. The
        dwell's own timer is cancelled while holding, so only this moves on.
        """
        self._poll_timer = None
        if not self.running or self._threshold is None:
            return
        self._poll_timer = self.root.after(SIGNAL_POLL_MS, self._poll_signal)
        if not self._settled or \
                time.monotonic() - self._settled_at < SIGNAL_SETTLE_MS / 1000:
            return
        level = self._signal()
        now = time.monotonic()
        if level is not None and level >= self._threshold:
            self._below_since = None
            if not self.holding:
                self.holding = True
                if self._timer is not None:
                    try:
                        self.root.after_cancel(self._timer)
                    except Exception:
                        pass
                    self._timer = None
                if callable(self.on_hold):
                    self.on_hold(self.index, level)
            return
        if not self.holding:
            return
        if self._below_since is None:
            self._below_since = now
        elif now - self._below_since >= SIGNAL_HANG_MS / 1000:
            self.holding = False
            if callable(self.on_hold):
                self.on_hold(self.index, None)
            self._advance()

    def _advance(self):
        self._timer = None
        if not self.running:
            return
        following = self._next_usable(self.index if self.index is not None else -1)
        if following is None:
            self.stop("nothing left to scan -- every channel is empty")
            return
        self._go_to(following)

    # ------------------------------------------------------------------
    def watch(self):
        """
        Called whenever the model changes. Stops the scan if the operator has
        taken the radio back.
        """
        if not self.running:
            return
        if self._model.transmitting:
            self.stop("stopped -- transmitting")
            return
        heard = self._model.role_frequency("rx")
        if not self._settled:
            # Still arriving at the channel: the old frequency is expected
            # for a moment, and is not the operator.
            if heard == self._expected_hz:
                self._mark_settled()
            return
        if heard != self._expected_hz:
            self.stop("stopped -- tuned away")
