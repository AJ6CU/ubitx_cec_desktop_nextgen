#!/usr/bin/python3
"""
StubRadio -- simulation, and placeholders for things with no backend yet.

WHAT IT IS NOW

Two methods, neither of which stands in for the rig:

  * report_transmitting -- drives the "simulate transmit" button, so the
    on-air indicator and the meter swap can be seen without keying up.
  * set_filter -- the receive filter, which belongs to the SDR backend. That
    backend does not exist yet, so the control needs somewhere to go.

Both write the model directly, which the view must never do. They are here
precisely because they have no real source: when the SDR backend arrives,
set_filter moves to it, and when the rig's transmit report is wired,
report_transmitting goes too.

WHAT IT USED TO BE

A stand-in for the rig while there was no link: every command accepted and
confirmed a moment later, so controls could be wired correctly before a
radio was attached. That job ended when uBITX_Link took over, and thirteen of
its fifteen methods were left uncalled.

They were deleted rather than kept in step, because keeping them in step by
hand did not work: they drifted twice, and by the end the stub could not
have been swapped in for the link at all -- the two did not even share
method names. A no-rig mode would be genuinely useful, but it wants a shared
interface that both implement, designed as such, not a copy maintained from
memory.
"""



class StubRadio:
    """Simulation, and placeholders for things with no backend yet."""

    def __init__(self, state, schedule):
        """
        Args:
            state: The RadioModel to update.
            schedule: A function taking (milliseconds, callable) -- a
                widget's `after`. Kept so the filter change arrives on the
                event loop like a real confirmation would, rather than
                synchronously inside the click.
        """
        self.stubstate = state
        self._schedule = schedule

    def set_filter(self, hz):
        """
        The receive filter width, until the SDR backend can set it for real.

        Clamped to 200-4000 Hz, the range the controls step through.
        """
        def apply():
            self.stubstate.filter_hz = max(200, min(4000, int(hz)))
            self.stubstate.changed()
        self._schedule(40, apply)

    def report_transmitting(self, value):
        """
        Pretends the rig reported going on or off air.

        Only the "simulate transmit" button calls this. The real report
        arrives from the rig and should replace it once wired.
        """
        self.stubstate.transmitting = bool(value)
        self.stubstate.changed()