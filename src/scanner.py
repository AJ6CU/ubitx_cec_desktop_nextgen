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

It does not stop on a signal. That needs a signal level, and SDR++ gives none;
it becomes possible once the rig's S-meter reports are wired.
"""

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

        # Called with the index each time a channel is reached, and with None
        # and a reason when the scan stops. Set by the owner.
        self.on_step = None
        self.on_stop = None

    # ------------------------------------------------------------------
    def start(self, channels, start_index=0, dwell_seconds=5):
        """
        Starts scanning.

        Args:
            channels: A function returning the channels to scan, each a dict
                with "freq" and "mode". Called at every step.
            start_index: The channel to begin with.
            dwell_seconds: Time on each channel.
        """
        self.stop(None)
        self._channels = channels
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
        for timer in ("_timer", "_settle_timer"):
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

    def _settle_anyway(self):
        self._settle_timer = None
        self._settled = True

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
                self._settled = True
            return
        if heard != self._expected_hz:
            self.stop("stopped -- tuned away")
