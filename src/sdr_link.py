#!/usr/bin/python3
"""
SDR_Link -- keeps SDR++ in step with the rig, in both directions.

A second transport, sitting beside uBITX_Link. It talks to SDR++ through
SDRPlusPlusController over rigctl, and connects it to the same RadioModel the
interface reads.

    rig  --reports-->  RadioModel  --follow()-->  SDR++
    rig  <--commands-- uBITX_Link  <--callbacks-- SDR++

TWO DIRECTIONS

  The rig leads. When the model's receive frequency or mode changes, follow()
  sends it to SDR++, so the waterfall shows what you are listening to.

  SDR++ can lead too. Click a signal in the waterfall, or turn SDR++'s own
  dial, and the controller's poll notices and calls back here -- and that goes
  to the RIG, as a command, like any other control. The model changes only
  when the rig confirms, which is the rule everywhere else in this
  application and holds here as well.

IT FOLLOWS THE RECEIVE ROLE, NOT THE RAW REPORT

The code this replaces sent SDR++ whatever frequency the rig reported as
primary (`vc_`). That goes wrong in split: to set the transmit frequency the
rig is briefly made to swap VFOs, so for a moment the primary VFO IS the
transmit one -- and SDR++ was retuned to the transmit frequency in the middle
of every split tuning step. Following role_frequency("rx") avoids it: the
roles are frozen for the length of that swap, and the model's notifications
are held, so follow() is not even called until it is over.

NEITHER SIDE ECHOES THE OTHER

Each direction remembers what it last passed on. A change that arrives from
SDR++ is recorded as already sent, so when the rig confirms it and the model
changes, follow() does not send it straight back. The controller has its own
share of this -- see its set_frequency_hz and set_mode.
"""
import globalvars as gv
from SDRPlusPlusController import SDRPlusPlusController


# Rig modes to SDR++ modes. SDR++ has a single CW mode; the rig has one for
# each sideband.
_RIG_TO_SDR = {"LSB": "LSB", "USB": "USB", "CWL": "CW", "CWU": "CW"}



class SDR_Link:
    """Keeps SDR++ and the rig in step through the shared RadioModel."""

    def __init__(self, root, model, rig):
        """
        Args:
            root: The Tk root, for the controller's polling loop.
            model: The RadioModel shared with the interface.
            rig: The uBITX_Link. Changes made in SDR++ are sent to the rig
                through it, so the rig confirms them like any other command.
        """
        self.root = root
        self._model = model
        self._rig = rig
        self.controller = SDRPlusPlusController(root)

        # What was last passed to SDR++. Compared on every follow() so only a
        # real change is sent, and set when SDR++ leads so its own change is
        # not sent straight back once the rig confirms it.
        self._sent_hz = None
        self._sent_mode = None

        # Called with True or False when the connection comes or goes, so
        # the interface can say so. Set by the owner.
        self.on_status = None

        # Volume changes wait for the slider to settle -- see set_volume.
        self._pending_volume = None
        self._volume_timer = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    @property
    def connected(self):
        return bool(self.controller.is_connected)

    def connect(self):
        """
        Connects to SDR++ at the configured address, and brings it into step.

        Returns:
            True if connected. False if SDR++ could not be reached -- it may
            not be running, or its rigctl server may be switched off.
        """
        host = gv.config.get_sdr_server_ip()
        port = int(gv.config.get_sdr_tcp_port())

        if self.connected:
            self.controller.disconnect()

        if not self.controller.connect(host, port):
            print(f"[sdr] could not reach SDR++ at {host}:{port}")
            self._report(False)
            return False

        self.controller.startSDR()
        self.controller.on_frequency_change_primary = self._from_sdr_frequency
        self.controller.on_mode_change_primary = self._from_sdr_mode
        self.controller.on_filter_change = self._from_sdr_filter
        self.controller.on_disconnect = self._lost

        # Forget what was sent before, so the rig's current state is pushed
        # in full rather than compared against a previous connection.
        self._sent_hz = None
        self._sent_mode = None
        self.follow()

        print(f"[sdr] connected to SDR++ at {host}:{port}")
        self._report(True)
        return True

    def disconnect(self):
        """Stops SDR++ and closes the connection."""
        if self.connected:
            self.controller.stopSDR()
            self.controller.disconnect()
        self._report(False)

    def _lost(self):
        """The controller found the connection gone -- SDR++ closed, say."""
        print("[sdr] lost the connection to SDR++")
        self._report(False)

    def _report(self, connected):
        if callable(self.on_status):
            try:
                self.on_status(connected)
            except Exception as err:
                print(f"[sdr] status callback failed: {err}")

    # ------------------------------------------------------------------
    # Rig to SDR++
    # ------------------------------------------------------------------
    def follow(self):
        """
        Sends SDR++ the receive frequency and mode, if either has changed.

        Called whenever the model changes. Cheap when nothing has moved --
        two comparisons -- which matters, because the model changes for
        reasons that have nothing to do with the SDR: a meter reading, the
        split button, a mode on the other VFO.
        """
        if not self.connected:
            return

        hz = self._model.role_frequency("rx")
        if hz and hz != self._sent_hz:
            self._sent_hz = hz
            self.controller.set_frequency_hz(hz)

        rig_mode = self._model.mode_of(self._model.rx_vfo)
        sdr_mode = _RIG_TO_SDR.get(rig_mode)
        if sdr_mode and sdr_mode != self._sent_mode:
            self._sent_mode = sdr_mode
            # The mode's own default width, not whatever the last mode used:
            # a 2600 Hz SSB filter carried into CW lets in everything around
            # the signal. The defaults come from the configuration.
            width = self.controller.DEFAULT_FILTER_FALLBACKS.get(sdr_mode, 0)
            self.controller.set_mode(sdr_mode, passband_hz=width)
            self._set_model_filter(self.controller.get_filter_width_hz())

    # ------------------------------------------------------------------
    # SDR++ to rig
    # ------------------------------------------------------------------
    def _from_sdr_frequency(self, hz):
        """
        Tuned in SDR++ -- a click on the waterfall, or its own dial.

        Sent to the rig as a receive frequency. Recorded as sent first, so
        that when the rig confirms it and follow() runs, it is not sent back.
        """
        hz = int(hz)
        if hz == self._sent_hz:
            return
        self._sent_hz = hz
        self._rig.set_role_frequency("rx", hz)

    def _from_sdr_mode(self, sdr_mode):
        """
        A mode chosen in SDR++.

        LSB and USB pass straight through. CW needs a sideband the rig can
        use: if the rig is already in CW its choice is kept, so moving
        between CW and CW in SDR++ never flips CWL to CWU; only coming from
        SSB does the band decide.

        Modes the rig cannot do -- AM, FM and the rest -- are NOT passed on.
        The code this replaces forced the rig to USB and warned with a dialog
        on every poll, which changed the transmitter because of a listening
        choice. Now SDR++ can be left in AM to listen while the rig keeps
        its own mode.
        """
        sdr_mode = str(sdr_mode).upper()
        if sdr_mode == self._sent_mode:
            return

        current = self._model.mode_of(self._model.rx_vfo)
        if sdr_mode in ("LSB", "USB"):
            rig_mode = sdr_mode
        elif sdr_mode == "CW":
            if current in ("CWL", "CWU"):
                rig_mode = current
            else:
                # The band's conventional sideband -- the same rule a DFT
                # channel uses, from the model, rather than a second copy of
                # the boundary here.
                rig_mode = ("CWU" if self._model.default_sideband(
                    self._model.role_frequency("rx")) == "USB" else "CWL")
        else:
            print(f"[sdr] SDR++ is in {sdr_mode}, which the rig cannot use; "
                  f"leaving the rig in {current}")
            self._sent_mode = sdr_mode
            return

        self._sent_mode = sdr_mode
        if rig_mode != current:
            self._rig.set_mode_everywhere(rig_mode)

    def _from_sdr_filter(self, width_hz):
        """The filter was widened or narrowed in SDR++ itself."""
        self._set_model_filter(width_hz)

    # ------------------------------------------------------------------
    # Audio
    #
    # Behind the SDR rather than in the interface, deliberately. SDR++ cannot
    # set its own audio level over rigctl, so for SDR++ this is the COMPUTER'S
    # output volume, changed with a different command on each platform. A
    # different SDR can do better -- SDRangel has its own audio gain -- and
    # answering here means the interface's volume control never has to know
    # which one it is talking to.
    # ------------------------------------------------------------------
    VOLUME_SETTLE_MS = 150

    @property
    def volume_is_system_wide(self):
        """
        True when "volume" moves every application, not just the SDR.

        So the interface can say so. For SDR++ it always is.
        """
        return True

    def get_volume(self):
        """The current level, 0 to 100."""
        try:
            return int(self.controller.get_system_volume())
        except Exception:
            return 50

    def set_volume(self, percent):
        """
        Sets the level, 0 to 100 -- once the slider stops moving.

        Each change runs an external command (osascript on macOS, amixer on
        Linux) on the interface thread, and a dragged slider sends dozens a
        second. Only the value it settles on is sent, so dragging does not
        stutter.
        """
        self._pending_volume = max(0, min(100, int(float(percent))))
        if self._volume_timer is not None:
            try:
                self.root.after_cancel(self._volume_timer)
            except Exception:
                pass
        self._volume_timer = self.root.after(self.VOLUME_SETTLE_MS,
                                             self._apply_volume)

    def _apply_volume(self):
        self._volume_timer = None
        if self._pending_volume is not None:
            self.controller.set_volume(self._pending_volume / 100.0)

    def set_muted(self, muted):
        """Mutes or restores the audio."""
        if muted:
            self.controller.mute()
        else:
            self.controller.unmute()

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------
    def set_filter(self, width_hz):
        """
        Sets SDR++'s receive filter width.

        The filter belongs to SDR++, not the rig -- the uBITX has no filter
        command -- so this is the only place it can be changed.
        """
        if not self.connected:
            print("[sdr] not connected; the filter is SDR++'s to set")
            return
        width_hz = max(50, int(width_hz))
        self.controller.set_filter_width_hz(width_hz)
        self._set_model_filter(self.controller.get_filter_width_hz())

    def reset_filter(self):
        """Back to the configured default width for the current mode."""
        sdr_mode = _RIG_TO_SDR.get(self._model.mode_of(self._model.rx_vfo), "USB")
        self.set_filter(self.controller.DEFAULT_FILTER_FALLBACKS.get(sdr_mode, 2600))

    def _set_model_filter(self, width_hz):
        """
        Records the filter width SDR++ reports.

        This link is a transport, like uBITX_Link, so it writes to the model
        the way the rig's reports do -- and says so, so the interface redraws.
        """
        try:
            width_hz = int(width_hz)
        except (TypeError, ValueError):
            return
        if width_hz != self._model.filter_hz:
            self._model.filter_hz = width_hz
            self._model.changed()
