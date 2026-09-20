#!/usr/bin/python3
"""
StubRadio -- stands in for piRadio while there is no rig attached.

WHAT IT IS FOR

The real protocol is request-then-confirm: the interface sends a command and
changes nothing, and the rig replies with an instruction to update the
display. This stub keeps that shape, so a control wired against it is wired
correctly for the real thing -- the only difference is that the confirmation
comes from a timer instead of a serial port.

Wiring a mockup straight to its state object would be quicker and would teach
the wrong habit: a control that sets `state.split = True` looks fine until
the rig refuses the command, and then the interface is showing something the
radio is not doing.

THE DELAY IS DELIBERATE

Real confirmations take a few tens of milliseconds -- the rig is effectively
synchronous, but a laptop can outrun a Nano, which is what the MCU headroom
settings exist to pace. Answering instantly here would hide any place the
interface assumes its command already took effect.
"""

CONFIRM_MS = 40


class StubRadio:
    """
    Accepts commands, and confirms them a moment later.

    Every method here corresponds to something piRadio sends down the wire.
    Nothing writes to the state directly -- each schedules a confirmation,
    which is what the real rig's reply handler would do.
    """

    def __init__(self, state, schedule):
        """
        Args:
            state: The RadioState to update when a command is confirmed.
            schedule: A function taking (milliseconds, callable) -- a
                widget's `after`.
        """
        self.stubstate = state
        self._schedule = schedule

    # ------------------------------------------------------------------
    def _confirm(self, apply_change):
        """
        Answers a command the way the rig would.

        The change happens HERE, on the reply, not in the method that sent
        the command -- so a control cannot get ahead of the radio.
        """
        def reply():
            apply_change()
            self.stubstate.changed()
        self._schedule(CONFIRM_MS, reply)

    # ------------------------------------------------------------------
    # Commands. One per thing the interface can ask for.
    # ------------------------------------------------------------------
    def set_frequency(self, which, hz):
        self._confirm(lambda: self.stubstate.set_frequency(which, hz))

    def set_role_frequency(self, role, hz):
        self._confirm(lambda: self.stubstate.set_role_frequency(role, hz))

    def set_mode(self, mode):
        def apply():
            self.stubstate.set_mode(self.stubstate.active, mode)
            # The rig reports the filter separately; the stub does it in the
            # same breath because there is nothing else to report it.
            self.stubstate.filter_hz = FILTER_DEFAULTS.get(mode,
                                                       self.stubstate.filter_hz)
        self._confirm(apply)

    def toggle_split(self):
        self._confirm(lambda: setattr(self.stubstate, "split",
                                      not self.stubstate.split))

    def toggle_rit(self):
        def apply():
            self.stubstate.rit = not self.stubstate.rit
            if not self.stubstate.rit:
                # Leaving RIT returns you to the base, which is what makes
                # the base worth showing while it is on.
                self.stubstate.rit_offset = 0
        self._confirm(apply)

    def toggle_vfo(self):
        self._confirm(lambda: setattr(self.stubstate, "active",
                                      "b" if self.stubstate.active == "a" else "a"))

    def swap_vfos(self):
        def apply():
            self.stubstate.vfo_a, self.stubstate.vfo_b = (self.stubstate.vfo_b,
                                                  self.stubstate.vfo_a)
            self.stubstate.mode_a, self.stubstate.mode_b = (self.stubstate.mode_b,
                                                    self.stubstate.mode_a)
        self._confirm(apply)

    def copy_AtoB(self):
        def apply():
            self.stubstate.vfo_b = self.stubstate.vfo_a
            self.stubstate.mode_b = self.stubstate.mode_a

        self._confirm(apply)

    def toggle_lock(self):
        self._confirm(lambda: setattr(self.stubstate, "locked",
                                      not self.stubstate.locked))

    def toggle_mute(self):
        self._confirm(lambda: setattr(self.stubstate, "muted",
                                      not self.stubstate.muted))

    def toggle_tx_inhibit(self):
        self._confirm(lambda: setattr(self.stubstate, "tx_inhibit",
                                      not self.stubstate.tx_inhibit))

    def set_filter(self, hz):
        self._confirm(lambda: setattr(self.stubstate, "filter_hz",
                                      max(200, min(4000, int(hz)))))

    # ------------------------------------------------------------------
    # Not a command -- the rig reports these unasked.
    # ------------------------------------------------------------------
    def report_meters(self, s_value=None, pwr=None, swr=None):
        if s_value is not None:
            self.stubstate.s_value = s_value
        if pwr is not None:
            self.stubstate.pwr = pwr
        if swr is not None:
            self.stubstate.swr = swr
        self.stubstate.changed()

    def report_transmitting(self, value):
        self.stubstate.transmitting = bool(value)
        self.stubstate.changed()


# Imported late so this module can be read on its own.
FILTER_DEFAULTS = {"LSB": 2600, "USB": 2600, "CWL": 500, "CWU": 500}
