#!/usr/bin/python3
"""
SDR_Link -- keeps SDR in step with the rig, in both directions.

A second transport, sitting beside uBITX_Link. It talks to SDR++ through
RigctlSDR over rigctl -- SDR++, Gqrx, sdrOxide, or a rigctld, chosen by the "SDR
Software" setting -- and connects it to the same RadioModel the
interface reads.

    rig  --reports-->  RadioModel  --follow()-->  SDR
    rig  <--commands-- uBITX_Link  <--callbacks-- SDR

TWO DIRECTIONS

  The rig leads. When the model's receive frequency or mode changes, follow()
  sends it to the SDR, so the waterfall shows what you are listening to.

  The SDR can lead too. Click a signal in the waterfall, or turn the SDR's own
  dial, and the controller's poll notices and calls back here -- and that goes
  to the RIG, as a command, like any other control. The model changes only
  when the rig confirms, which is the rule everywhere else in this
  application and holds here as well.

IT FOLLOWS THE RECEIVE ROLE, NOT THE RAW REPORT

The code this replaces sent SDR whatever frequency the rig reported as
primary (`vc_`). That goes wrong in split: to set the transmit frequency the
rig is briefly made to swap VFOs, so for a moment the primary VFO IS the
transmit one -- and SDR was retuned to the transmit frequency in the middle
of every split tuning step. Following role_frequency("rx") avoids it: the
roles are frozen for the length of that swap, and the model's notifications
are held, so follow() is not even called until it is over.

NEITHER SIDE ECHOES THE OTHER

Each direction remembers what it last passed on. A change that arrives from
SDR is recorded as already sent, so when the rig confirms it and the model
changes, follow() does not send it straight back. The controller has its own
share of this -- see its set_frequency_hz and set_mode.
"""
import globalvars as gv
from time import sleep, monotonic

import sdr_launcher
import system_audio
from rigctl_sdr import RigctlSDR
from rest_sdr import RestSDR
from sdr_programs import (profile_for, CW_EITHER, FILTER, VOLUME, MUTE, SQUELCH, SIGNAL,
                          AGC, NR, NOTCH, NB, CW_PEAK, SQUELCH_SWITCH, RF_GAIN,
                          BANDWIDTH, DECODER)

# A mode asked of the rig because the SDR changed is PENDING until the rig
# reports it. Meanwhile the rig's older mode is not pushed back to the SDR:
# drag SDRangel's high cut to USB and back to LSB inside a second, and the
# rig's late confirmation of USB used to be sent to SDRangel as the rig's
# choice, leaving both in USB. Given up after this long, in case the rig
# never takes it.
RIG_MODE_PENDING_SECONDS = 2.0


# How long to let the operating system take the SDR device back after the
# program holding it has gone. Claimed again too quickly, the new program
# finds it still busy.
DEVICE_RELEASE_SECONDS = 1.0


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
        # WHICH SDR, from the "SDR Software" setting -- SDR++, Gqrx or a
        # plain rigctld. The profile says how it names modes and what it is
        # known not to do; the controller finds out the rest at connect.
        self.profile = profile_for(gv.config.get_sdr_software())
        self.controller = self._transport_for(self.profile)

        # What was last passed to SDR++. Compared on every follow() so only a
        # real change is sent, and set when SDR++ leads so its own change is
        # not sent straight back once the rig confirms it.
        self._sent_hz = None
        self._sent_mode = None
        self._rig_mode_asked = None     # see RIG_MODE_PENDING_SECONDS
        self._rig_mode_asked_at = 0.0

        # Called with True or False when the connection comes or goes, so
        # the interface can say so. Set by the owner.
        self.on_status = None
        # THE PROGRAM THIS APPLICATION STARTED, if it started one. An SDR
        # that was already running is the operator's: it is attached to and
        # left running. Only what is held here is ever closed -- see
        # close_program() and disconnect().
        self._program = None
        self._waiting_for_program = None
        # Called with no arguments when the SDR's own volume or mute changes
        # in the SDR itself, so the interface can move its controls to match.
        self.on_audio = None
        # Called with no arguments when a new signal reading arrives -- five
        # times a second where the SDR reports one. The interface redraws the
        # meter alone, not the whole window.
        self.on_signal = None
        # Asked before closing or forcing another program -- see
        # _close_for_switch. Each is called with the program's name and
        # answers True to go ahead. Nothing here opens a window: this link
        # says what it needs and the interface decides how to ask.
        self.on_needs_force = None      # ours, and it will not close
        self.on_needs_closing = None    # theirs, and it holds the device
        # The computer's mute, as this application last set it -- the state
        # used when the SDR has no mute of its own.
        self._system_muted = False

        # The CW decoder -- see _set_decoding. Called with each piece of
        # decoded text. Set by the owner.
        self.on_decoded = None
        self._decoding = False
        self._decode_saved = None       # what decoding changed, to put back

        # Volume changes wait for the slider to settle -- see set_volume.
        self._pending_volume = None
        self._volume_timer = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    @property
    def connected(self):
        return bool(self.controller.is_connected)

    def _transport_for(self, profile):
        """
        The code that drives this program, chosen by the protocol its entry
        names.

        "rigctl" for SDR++, Gqrx and rigctld; "rest" for SDRangel's own API
        -- a second class, not a variation on the first: it addresses device
        sets and channels by index and needs a discovery step to find the
        right demodulator. The entry says WHICH transport; how each works is
        code.
        """
        if profile.protocol in ("rigctl", "none"):
            return RigctlSDR(self.root, profile)
        if profile.protocol == "rest":
            return RestSDR(self.root, profile)
        print(f"[sdr] {profile.name} speaks {profile.protocol}, which this "
              f"version cannot drive yet")
        return RigctlSDR(self.root, profile_for("none"))

    def reload_profile(self):
        """
        Reads which SDR program the settings now name, and prepares for it.

        The link object STAYS THE SAME. Controls are bound to its methods
        when the window is built -- the squelch's A and R among them -- so
        replacing it on a change of program would leave those buttons calling
        an object nobody else uses. This only changes what connect() will
        talk to.

        THE OLD PROGRAM IS DEALT WITH FIRST, and by the same rule as closing:
        one this application started is stopped, disconnected and asked to
        quit; one that was already running keeps its receiver and only loses
        the connection. Changing from an SDR++ this application started to
        Gqrx would otherwise leave that SDR++ running with nothing holding
        it -- it would never be closed, by anything, for the rest of the
        session.

        The program being closed is the OLD one, which is why a Started
        carries its own profile: by the time it is asked to quit, this
        object's profile is the new program's.
        """
        wanted = profile_for(gv.config.get_sdr_software())
        if wanted.key == self.profile.key and self.connected:
            return                      # the same program; nothing to change

        self._close_for_switch(wanted)
        self.profile = wanted
        self.controller = self._transport_for(self.profile)
        self.controller.on_frequency = self._from_sdr_frequency
        self.controller.on_mode = self._from_sdr_mode
        self.controller.on_filter = self._from_sdr_filter
        self.controller.on_rit = self._from_sdr_rit
        self.controller.on_split = self._from_sdr_split
        self.controller.on_volume = lambda level: self._audio_changed()
        self.controller.on_mute = lambda muted: self._audio_changed()
        self.controller.on_dsp = lambda function: self._audio_changed()
        self.controller.on_rf_gain = lambda: self._audio_changed()
        self.controller.on_squelch = lambda level: self._audio_changed()
        self.controller.on_signal = lambda level: self._signal_changed()
        self.controller.on_decoded = self._decoded_text
        self.controller.on_disconnect = self._lost
        self._sent_hz = None            # FIX: was _sent_frequency, which nothing reads
        self._sent_mode = None
        self._rig_mode_asked = None     # see RIG_MODE_PENDING_SECONDS
        self._rig_mode_asked_at = 0.0
        print(f"[sdr] now set up for {self.profile.name}")

    @property
    def started_here(self):
        """Whether this application started the SDR program it is talking to."""
        return self._program is not None

    @property
    def capabilities(self):
        """
        What this SDR can do, found out at connect -- see sdr_programs for
        the names. Empty when not connected. The interface greys out what is
        missing.
        """
        return self.controller.capabilities

    def connect(self):
        """
        Connects to the SDR at the configured address, finds out what it can
        do, and brings it into step.

        Returns:
            True if connected. False if it could not be reached -- it may not
            be running, or its remote control may be switched off.
        """
        # "No SDR" is a setting, not a failure: nothing is tried, and the
        # interface greys what an SDR would have served.
        if not gv.config.sdr_enabled():
            print("[sdr] no SDR selected in the settings")
            self._report(False)
            return False

        host = gv.config.get_sdr_host()
        port = int(gv.config.get_sdr_port())

        if self.connected:
            self.controller.disconnect()

        self.controller.on_frequency = self._from_sdr_frequency
        self.controller.on_mode = self._from_sdr_mode
        self.controller.on_filter = self._from_sdr_filter
        self.controller.on_rit = self._from_sdr_rit
        self.controller.on_split = self._from_sdr_split
        self.controller.on_volume = lambda level: self._audio_changed()
        self.controller.on_mute = lambda muted: self._audio_changed()
        self.controller.on_dsp = lambda function: self._audio_changed()
        self.controller.on_rf_gain = lambda: self._audio_changed()
        self.controller.on_squelch = lambda level: self._audio_changed()
        self.controller.on_signal = lambda level: self._signal_changed()
        self.controller.on_decoded = self._decoded_text
        self.controller.on_disconnect = self._lost

        if not self.controller.connect(host, port):
            # RestSDR says why; rigctl can only fail to answer. "Nothing to
            # tune" is said by the transport itself, once.
            if getattr(self.controller, "last_failure", "unreachable") == "unreachable":
                print(f"[sdr] could not reach {self.profile.name} at {host}:{port}")
            self._report(False)
            return False

        self.controller.start()

        # Forget what was sent before, so the rig's current state is pushed
        # in full rather than compared against a previous connection.
        self._sent_hz = None
        self._sent_mode = None
        self._rig_mode_asked = None     # see RIG_MODE_PENDING_SECONDS
        self._rig_mode_asked_at = 0.0
        self.follow()

        print(f"[sdr] connected to {self.profile.name} at {host}:{port}; "
              f"it can do: {', '.join(sorted(self.capabilities))}")
        self._report(True)

        # ASK AGAIN SHORTLY. A program still starting accepts a connection
        # before its remote control is fully up, and answers "l ?" with
        # nothing -- which discovery takes as final, greying out volume,
        # squelch and the signal for the whole session. That is the ordinary
        # case when this application started the program itself.
        #
        # HERE, not in the callers: pressing Connect on the Setup page calls
        # this directly, so a second look scheduled only by connect_when_ready
        # never happened -- which is exactly when the fault was seen.
        self.root.after(self.CAPABILITY_RECHECK_MS, self.recheck_capabilities)
        return True

    def shutdown(self):
        """
        Everything this application should do about the SDR as it closes.

        One call, because the ORDER is the whole point -- see close_program.
        A program this application started is stopped, disconnected and asked
        to quit, in that order; one that was already running keeps its
        receiver and only loses the connection.
        """
        # SAYS WHAT IT IS DOING, because the interesting case is the one
        # where it does nothing: a closing application that prints not a word
        # about the SDR gives no way to tell "left it alone deliberately"
        # from "thought there was nothing to close".
        print(f"[sdr] closing: started by us = {self.started_here}, "
              f"connected = {self.connected}")
        if self.started_here:
            self.close_program()
            return
        print(f"[sdr] {self.profile.name} was not started here; leaving it running")
        self.disconnect()

    def disconnect(self):
        """
        Closes the connection.

        DOES NOT STOP THE SDR'S RECEIVER unless this application started it.
        It used to, always -- the SDR++ controller had done so since before
        there was a reason -- and with Gqrx the effect was plain: quitting
        the panel, changing SDR, or even pressing Connect (which disconnects
        first) sent "U DSP 0" and left Gqrx with no waterfall and no audio
        until its play button was pressed.

        An SDR the operator started is theirs. When this application learns
        to launch one -- see TODO -- it will stop that one, and only that
        one; `started_here` is what will say so.
        """
        if self.connected:
            # ITS RECEIVER IS NOT TOUCHED HERE, even for a program this
            # application started. Closing it is close_program()'s job, and
            # that asks the application to quit, which stops its own
            # receiver properly and writes its settings. Stopping the DSP
            # first and then closing the window is two shutdowns racing --
            # and Gqrx is fragile about how it is shut down: an unclean exit
            # leaves its configuration half-written.
            self.controller.disconnect()
        self._report(False)

    # -- starting the program ------------------------------------------------
    def start_program(self):
        """
        Makes sure the SDR program is running, if autostart is on.

        Attaches to one already running -- the operator's, left alone when
        this closes -- or starts one, which becomes ours to close.

        Returns a sentence for the interface, or "" when there was nothing to
        do.
        """
        if not gv.config.sdr_enabled():
            return ""
        if str(gv.config.get_SDR_Autostart()) not in ("1", "True", "true"):
            return ""
        if self.started_here and self._program.is_running():
            return ""                   # already ours, still running

        if sdr_launcher.running_process(self.profile) is not None:
            print(f"[sdr] {self.profile.name} is already running; "
                  f"attaching to it and leaving it running on exit")
            return f"{self.profile.name} is already running"

        handle, note = sdr_launcher.start(self.profile, gv.config.get_sdr_path())
        print(f"[sdr] {note}")
        if handle is None:
            return note
        self._program = handle
        return note

    def close_program(self, force_if_needed=False):
        """
        Closes the SDR program IF this application started it.

        An instance that was already running was never held, so it cannot be
        closed by mistake: there is nothing here to close it with.
        """
        if self._program is None:
            print("[sdr] nothing to close -- no program is held")
            return True

        # THE ORDER MATTERS, and getting it wrong is what broke Gqrx.
        #
        # 1. Stop its receiver, so nothing is streaming.
        # 2. Close our socket, so its remote control has no client.
        # 3. Only then ask it to quit.
        #
        # Asking it to quit with our connection still open leaves its server
        # thread holding a live client while the application tries to shut
        # down -- which is what "Gqrx quit unexpectedly" and a configuration
        # that forgot which SDR was in use looked like. Nothing in flight,
        # then the request.
        if self.connected:
            self.controller.stop()
            self.controller.disconnect()

        running = self._program.is_running()
        print(f"[sdr] asking {self._program.profile.name} to quit "
              f"(still running = {running}, process id = {self._program.pid})")
        closed, note = sdr_launcher.stop(self._program,
                                         force_if_needed=force_if_needed)
        print(f"[sdr] {note or ('it had already gone' if closed else 'it is still there')}")
        # Let go either way: a program left running is the operator's to
        # close, and holding a handle would only tempt a later version into
        # forcing it.
        self._program = None
        return closed

    def recheck_capabilities(self):
        """
        Asks the SDR again what it can do, a few seconds after connecting.

        A PROGRAM STILL STARTING ANSWERS BADLY. Its remote control accepts a
        connection before everything behind it is ready, so "l ?" can come
        back empty or refused -- and discovery, taking that as final, greys
        out volume, squelch and the signal for the whole session. Connecting
        the moment the port opens, which is what autostart does, makes this
        the normal case rather than a rare one.

        Cheap to repeat: a handful of short questions. Anything gained is
        reported so the interface can light up what it had greyed.
        """
        if not self.connected:
            return
        before = set(self.capabilities)
        try:
            self.controller.discover()
        except Exception as err:
            print(f"[sdr] asking {self.profile.name} again failed: {err}")
            return
        gained = set(self.capabilities) - before
        if gained:
            print(f"[sdr] {self.profile.name} can also do: {', '.join(sorted(gained))}")
            self._report(self.connected)

    def _close_for_switch(self, wanted):
        """
        Clears the way for another SDR program.

        AN SDR DONGLE BELONGS TO ONE PROGRAM AT A TIME, so whatever is using
        it has to go before the next one can start -- there is nothing to
        switch to otherwise. That applies to a program this application
        started AND to one the operator started themselves, which is the case
        that was missed: switching away from a Gqrx they had opened merely
        disconnected from it, Gqrx kept the device, and the program they had
        just chosen could not open it. The switch failed quietly.

        WHOSE IT IS DECIDES WHAT IS ASKED:

          * ours, and it closes when asked -- done, no question;
          * ours, and it refuses -- the operator is asked before it is
            forced, since forcing can cost it its settings;
          * THEIRS -- the operator is asked before it is closed at all. They
            opened it; it is not this application's to close on a whim.

        With nobody to ask, nothing is closed and the switch fails honestly
        rather than taking a liberty.
        """
        leaving = self.profile
        ours = self.started_here
        started = self._program

        if self.connected:
            self.controller.stop()
            self.controller.disconnect()

        if not ours:
            # Is one of theirs actually holding the device? Switching from
            # "none", or from a program that is not running, needs nothing.
            process = sdr_launcher.running_process(leaving)
            if process is None or leaving.key == "none" or leaving.key == wanted.key:
                return True
            name = leaving.name
            if not (callable(self.on_needs_closing) and self.on_needs_closing(name)):
                print(f"[sdr] {name} is yours and is left running; it holds the "
                      f"SDR device, so {wanted.name} may not be able to start")
                return False
            started = sdr_launcher.Started(leaving,
                                           pid=getattr(process, "pid", None))

        closed, note = sdr_launcher.stop(started)
        if note:
            print(f"[sdr] {note}")

        if not closed:
            name = started.profile.name
            if callable(self.on_needs_force) and self.on_needs_force(name):
                closed, note = sdr_launcher.stop(started, force_if_needed=True)
                print(f"[sdr] {note}")
            else:
                print(f"[sdr] {name} is still running and holds the SDR device; "
                      f"{wanted.name} may not be able to start")

        self._program = None
        if closed:
            sleep(DEVICE_RELEASE_SECONDS)   # let the device come free
        return closed

    def connect_when_ready(self, attempts=12, wait_ms=1500):
        """
        Keeps trying to connect while the SDR program starts up.

        A freshly started SDR takes seconds to open its remote control, so a
        single attempt straight after launching always fails. This tries
        again on a timer -- not in a loop, which would freeze the window for
        the whole wait.
        """
        if self.connected:
            return
        if self.connect():
            return                      # connect() looks again by itself
        if attempts <= 1:
            if getattr(self.controller, "last_failure", None) == "nothing to tune":
                print(f"[sdr] {self.profile.name} is running but never offered "
                      f"anything to tune; giving up for now. Check its window: "
                      f"is the SDR device there, with an SSB demodulator?")
            else:
                print(f"[sdr] {self.profile.name} did not answer; giving up for now")
            return
        self._waiting_for_program = self.root.after(
            wait_ms, lambda: self.connect_when_ready(attempts - 1, wait_ms))

    def _lost(self):
        """The controller found the connection gone -- SDR++ closed, say."""
        self._decoding, self._decode_saved = False, None
        print(f"[sdr] lost the connection to {self.profile.name}")
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
            # After a band change, the new band FRAMED -- see frame_band.
            band = self._framing_for(hz)
            if band is not None:
                self.controller.set_frequency(hz, band=band)
            else:
                self.controller.set_frequency(hz)

        rig_mode = self._model.mode_of(self._model.rx_vfo)
        if self._rig_mode_asked is not None:
            waited = monotonic() - self._rig_mode_asked_at
            if rig_mode == self._rig_mode_asked or waited > RIG_MODE_PENDING_SECONDS:
                self._rig_mode_asked = None
            else:
                # The rig has not caught up with what the SDR asked for; its
                # current mode is older than the SDR's, so it is not sent.
                return
        # The SDR's own name for the mode -- SDR++ has one CW, Gqrx two.
        sdr_mode = self.profile.to_sdr.get(rig_mode)
        if sdr_mode and sdr_mode != self._sent_mode:
            previous = self._sent_mode
            self._sent_mode = sdr_mode
            # Out of CW, the decoder stops -- its filter is the new mode's.
            if self._decoding and not str(rig_mode).upper().startswith("CW"):
                self._set_decoding(False, restore_filter=False)
            # Between SSB and CW, the new mode's own default width: a 2600 Hz
            # SSB filter carried into CW lets in everything around the
            # signal. The defaults come from the configuration.
            #
            # Within one kind -- LSB to USB, CWL to CWU -- the width the
            # operator had is KEPT: only the sideband changed, and resetting
            # it undid an adjustment for no reason.
            same_kind = (previous is not None
                         and ("CW" in str(previous).upper()) == ("CW" in str(sdr_mode).upper()))
            width = self.controller.filter_width if same_kind else None
            if not width:
                width = self.controller.default_filter_width(sdr_mode)
            # The rig's CW tone, for a transport that places a CW passband
            # round it (RestSDR). Others have no such attribute and ignore it.
            if hasattr(self.controller, "cw_pitch"):
                self.controller.cw_pitch = getattr(self._model, "cw_tone", None)
            self.controller.set_mode(sdr_mode, width)
            if FILTER in self.capabilities:
                self._set_model_filter(self.controller.filter_width)
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
        # The profile translates. A mode it leaves out is one the rig
        # cannot use; CW_EITHER is a CW with no sideband of its own.
        rig_mode = self.profile.from_sdr.get(sdr_mode)
        if rig_mode is CW_EITHER:
            # A CW with no sideband of its own. The rig's own choice is kept
            # if it is already in CW, so CW to CW never flips CWL to CWU;
            # otherwise the band's conventional sideband -- the same rule a
            # DFT channel uses.
            if current in ("CWL", "CWU"):
                rig_mode = current
            else:
                rig_mode = ("CWU" if self._model.default_sideband(
                    self._model.role_frequency("rx")) == "USB" else "CWL")
        elif rig_mode is None:
            # A mode the rig cannot use: not passed on.
            print(f"[sdr] {self.profile.name} is in {sdr_mode}, which the rig "
                  f"cannot use; leaving the rig in {current}")
            self._sent_mode = sdr_mode
            return

        self._sent_mode = sdr_mode
        # Compared with what was last ASKED of the rig as well as what it
        # reports: a request still on its way leaves `current` behind, and
        # comparing with that alone skipped changing back.
        if rig_mode != current or (self._rig_mode_asked is not None
                                   and rig_mode != self._rig_mode_asked):
            self._rig_mode_asked = rig_mode
            self._rig_mode_asked_at = monotonic()
            self._rig.set_mode_everywhere(rig_mode)

    def _from_sdr_filter(self, width_hz):
        """The filter was widened or narrowed in SDR++ itself."""
        self._set_model_filter(width_hz)
    # MJH
    def _from_sdr_rit(self, newrit):
        print("rit enabled from sdr", newrit)

    def _from_sdr_split(self):
        print("split enabled from sdr")

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
    # How long after connecting to ask the SDR again what it can do.
    CAPABILITY_RECHECK_MS = 3000

    VOLUME_SETTLE_MS = 150

    @property
    def volume_is_system_wide(self):
        """
        True when "volume" moves every application, not just the SDR -- the
        SDR has no audio level of its own, as SDR++ has none. So the
        interface can say so.
        """
        return VOLUME not in self.capabilities

    def audio_description(self):
        """A sentence for the interface: what the volume and mute control."""
        if not self.connected:
            return "Volume and mute act on the SDR once it is connected."
        if not self.volume_is_system_wide:
            return (f"Volume and mute are {self.profile.name}'s own -- they "
                    f"change nothing else on the computer.")
        return (f"{self.profile.name} cannot set its own level, so the volume "
                f"is the computer's output volume -- every application follows it.")

    def _level_range(self):
        return self.profile.volume_range or (0.0, 100.0)

    def get_volume(self):
        """
        The current level, 0 to 100 -- the SDR's own where it has one, spread
        evenly across its range (for Gqrx, decibels from -80 to +50), else
        the computer's.
        """
        if not self.volume_is_system_wide and self.controller.volume is not None:
            bottom, top = self._level_range()
            share = (self.controller.volume - bottom) / (top - bottom)
            return int(round(max(0.0, min(1.0, share)) * 100))
        try:
            return int(system_audio.get_volume())
        except Exception:
            return 50

    def set_volume(self, percent):
        """
        Sets the level, 0 to 100 -- once the slider stops moving.

        Each change is a command to the SDR, or for the computer's volume an
        external program on the interface thread, and a dragged slider sends
        dozens a second. Only the value it settles on is sent.
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
        if self._pending_volume is None:
            return
        if not self.volume_is_system_wide:
            bottom, top = self._level_range()
            level = bottom + (top - bottom) * self._pending_volume / 100
            self.controller.set_level("AF", round(level, 1))
        else:
            system_audio.set_volume(self._pending_volume)

    @property
    def muted(self):
        """Whether the SDR's audio is muted -- by its own mute, or the computer's."""
        if MUTE in self.capabilities and self.controller.muted is not None:
            return bool(self.controller.muted)
        return self._system_muted

    def set_muted(self, muted):
        """
        Mutes or restores the audio -- the SDR's own mute where it has one,
        which silences it and nothing else; otherwise the computer's.
        """
        if MUTE in self.capabilities:
            self.controller.set_mute(muted)
            return
        if muted:
            system_audio.mute()
        else:
            system_audio.unmute()
        self._system_muted = bool(muted)

    # -- The listening aids: AGC, NR, notch, squelch, NB, CW peak -----------
    #
    # ONE WAY OF DESCRIBING EVERY FUNCTION, whatever the SDR, so the window
    # needs no SDR's name and no SDR's numbers. By name -- "agc", "nr",
    # "notch", "squelch", "nb", "cw" -- each function:
    #
    #   has_dsp          exists with this SDR
    #   dsp_blocked      why it cannot be used just now, or None
    #   dsp_switchable   has an on/off switch of its own
    #   dsp_on           is on
    #   toggle_dsp       what clicking its lamp does
    #   dsp_knob_names   its adjustments, in order, each described by
    #                    dsp_info / dsp_range / dsp_setting / dsp_setting_text
    #                    and set by set_dsp_setting
    #   dsp_actions      buttons of its own -- (label, action, enabled)
    #
    # TWO KINDS BEHIND IT. A SWITCHED function (SDRangel's) is described by
    # the transport, from sdr_controls.json. A THRESHOLD SQUELCH (Gqrx's, a
    # rigctld's) has no switch -- fully open is its "off" -- and is described
    # here from the program's entry in sdr_programs.json: one threshold knob
    # in the program's own units, and its A and R.

    DSP_CAPABILITY = {"agc": AGC, "nr": NR, "notch": NOTCH,
                      "squelch": SQUELCH_SWITCH, "nb": NB, "cw": CW_PEAK}

    # Functions that must stay off in CW, and why -- the transport turns
    # them off on entering CW (see RestSDR._automate_mode); this keeps the
    # operator from turning them back on.
    OFF_IN_CW = {"notch": "off in CW -- it would notch out the signal"}

    THRESHOLD = "threshold"         # the threshold squelch's one knob

    def _switched(self, function):
        return self.DSP_CAPABILITY.get(function) in self.capabilities

    def _threshold_squelch(self, function):
        return function == "squelch" and not self._switched(function) and self.has_squelch

    def _decoder(self, function):
        return function == "decode" and DECODER in self.capabilities

    def has_dsp(self, function):
        return (self._switched(function) or self._threshold_squelch(function)
                or self._decoder(function))

    def dsp_blocked(self, function):
        """Why a function cannot be used just now -- or None if it can."""
        if not self.has_dsp(function):
            return (f"not available with {self.profile.name}" if self.connected
                    else "needs a connected SDR")
        in_cw = str(self._model.mode_of(self._model.rx_vfo)).upper().startswith("CW")
        reason = self.OFF_IN_CW.get(function)
        if reason and in_cw:
            return reason
        if function == "decode" and not in_cw:
            return "CW only -- the decoder reads Morse"
        return None

    def dsp_switchable(self, function):
        return self._switched(function) or self._decoder(function)

    def dsp_on(self, function):
        """Whether a function is on -- None where the SDR has none."""
        if self._decoder(function):
            return self._decoding
        if self._threshold_squelch(function):
            threshold = self._squelch_now()
            return threshold is not None and threshold > self.squelch_range()[0]
        if not self._switched(function):
            return None
        return getattr(self.controller, "dsp_on", {}).get(function)

    def set_dsp(self, function, on):
        """Turns a switched function on or off."""
        if self._decoder(function):
            if not (on and self.dsp_blocked(function)):
                self._set_decoding(bool(on))
            return
        if self._switched(function) and not (on and self.dsp_blocked(function)):
            self.controller.set_dsp(function, bool(on))

    def toggle_dsp(self, function):
        """
        What clicking a function's lamp does: a switched one flips; the
        threshold squelch opens fully if closed (R), and otherwise closes
        just above what is heard now (A).
        """
        if self.dsp_blocked(function):
            return
        if self._threshold_squelch(function):
            if self.dsp_on(function):
                self.reset_squelch()
            elif self.can_auto_squelch:
                self.auto_squelch()
            return
        self.set_dsp(function, not self.dsp_on(function))

    def dsp_defaults(self, function):
        """A function's adjustments' defaults, {name: value} -- {} where none are known."""
        if not self._switched(function) or not hasattr(self.controller, "dsp_defaults"):
            return {}
        return self.controller.dsp_defaults(function)

    def reset_dsp(self, function):
        """Puts a function's adjustments back to their defaults; its switch is left alone."""
        if self.dsp_defaults(function):
            self.controller.reset_dsp(function)
            self._audio_changed()

    # -- The CW decoder ------------------------------------------------------
    #
    # DEC, the seventh lamp: the SDR's CW decoder (SDRangel's Morse Decoder
    # feature), its text handed to on_decoded as it arrives. CW only.
    #
    # DECODING SETS THE RECEIVER FOR IT, and puts it back after -- the
    # operator's choice, 2026-09-27. A decoder needs one signal in the
    # passband and a clean keying envelope, which is most of the fiddling
    # people do by hand: so the filter is narrowed to DECODE_FILTER_HZ (or
    # left if already narrower), AGC is turned off (it pumps the level
    # between elements), and the CW peak filter is turned on at the tone.
    # Stopping restores all three as they were; leaving CW stops it, and
    # the filter is then the new mode's, not restored.
    DECODE_FILTER_HZ = 250

    def _set_decoding(self, on, restore_filter=True):
        if on == self._decoding:
            return
        if on:
            if not self.controller.set_decoder(True):
                print(f"[sdr] {self.profile.name}'s CW decoder could not be started")
                return
            self._decode_saved = {
                "filter": self.controller.filter_width,
                "agc": self.dsp_on("agc") if self._switched("agc") else None,
                "cw": self.dsp_on("cw") if self._switched("cw") else None,
            }
            width = self.controller.filter_width
            if FILTER in self.capabilities and (not width or width > self.DECODE_FILTER_HZ):
                self.set_filter(self.DECODE_FILTER_HZ)
            if self._decode_saved["agc"]:
                self.controller.set_dsp("agc", False)
            if self._decode_saved["cw"] is False:
                self.controller.set_dsp("cw", True)
            self._decoding = True
            print(f"[sdr] decoding CW through {self.profile.name}")
        else:
            self.controller.set_decoder(False)
            saved, self._decode_saved = self._decode_saved or {}, None
            self._decoding = False
            if restore_filter and saved.get("filter"):
                self.set_filter(saved["filter"])
            if saved.get("agc"):
                self.controller.set_dsp("agc", True)
            if saved.get("cw") is False:
                self.controller.set_dsp("cw", False)
        self._audio_changed()

    def _decoded_text(self, text):
        if self._decoding and callable(self.on_decoded):
            try:
                self.on_decoded(text)
            except Exception as err:
                print(f"[sdr] decoder callback failed: {err}")

    def dsp_actions(self, function):
        """A function's own buttons: [(label, action, enabled)] -- Gqrx's A and R."""
        if self._threshold_squelch(function):
            return [("A", self.auto_squelch, self.can_auto_squelch),
                    ("R", self.reset_squelch, True)]
        return []

    # The threshold squelch's knob is in DIAL UNITS like every other: whole
    # numbers, each one squelch_step of the program's own units -- 1 dB for
    # Gqrx; a hundredth of the range for one as narrow as rigctld's 0 to 1.
    def _squelch_step(self):
        bottom, top = self.squelch_range()
        return 1.0 if top - bottom >= 10 else (top - bottom) / 100.0

    def _squelch_now(self):
        """The threshold asked for and not yet sent, else the SDR's."""
        pending = getattr(self, "_pending_squelch", None)
        return pending if pending is not None else self.squelch

    def dsp_knob_names(self, function):
        """The adjustments a function's knobs show, in order -- [] without it."""
        if self._threshold_squelch(function):
            return [self.THRESHOLD]
        if not self._switched(function):
            return []
        return self.controller.dsp_knob_names(function)

    def dsp_info(self, function, name):
        """Caption, kind, range, labels and unit for an adjustment's knob."""
        if self._threshold_squelch(function):
            low, high = self.dsp_range(function, name)
            return {"caption": "Squelch", "kind": "range", "low": low, "high": high,
                    "labels": None, "short": None, "unit": self.profile.squelch_unit}
        return self.controller.dsp_info(function, name) if self._switched(function) else None

    def has_dsp_setting(self, function, name):
        if self._threshold_squelch(function):
            return name == self.THRESHOLD and self.squelch is not None
        return (self._switched(function)
                and name in getattr(self.controller, "dsp_settings", {}).get(function, {}))

    def dsp_setting(self, function, name):
        """An adjustment's value in dial units, or None."""
        if not self.has_dsp_setting(function, name):
            return None
        if self._threshold_squelch(function):
            return int(round(self._squelch_now() / self._squelch_step()))
        return self.controller.dsp_settings[function][name]

    def dsp_range(self, function, name):
        if self._threshold_squelch(function):
            step = self._squelch_step()
            bottom, top = self.squelch_range()
            return int(round(bottom / step)), int(round(top / step))
        return self.controller.dsp_range(function, name)

    def dsp_adjustable(self, function, name):
        """Whether an adjustment can be set from here, or only shown -- SSB NR's scheme."""
        if self._threshold_squelch(function):
            return self.has_dsp_setting(function, name)
        return (self.has_dsp_setting(function, name)
                and self.controller.dsp_adjustable(function, name))

    def dsp_setting_text(self, function, name, value):
        """As the SDR's dial shows it: "128 ms", "-100 dB", "Medium", "-95 dBFS"."""
        if self._threshold_squelch(function):
            return self.squelch_text(value * self._squelch_step())
        return self.controller.dsp_setting_text(function, name, value)

    def set_dsp_setting(self, function, name, value):
        """Sets an adjustment -- once its knob stops moving."""
        if self._threshold_squelch(function):
            self.set_squelch(float(value) * self._squelch_step())
            return
        key = (function, name)
        pending = self.__dict__.setdefault("_pending_dsp", {})
        timers = self.__dict__.setdefault("_dsp_timers", {})
        pending[key] = float(value)
        if timers.get(key) is not None:
            try:
                self.root.after_cancel(timers[key])
            except Exception:
                pass
        timers[key] = self.root.after(self.VOLUME_SETTLE_MS,
                                      lambda: self._apply_dsp_setting(key))

    def _apply_dsp_setting(self, key):
        self._dsp_timers[key] = None
        value = self._pending_dsp.pop(key, None)
        if value is not None and self.has_dsp_setting(*key):
            self.controller.set_dsp_setting(*key, value)

    # -- The sampled band: its width, and where it sits ---------------------
    #
    # What the SDR's spectrum and waterfall show. Its WIDTH is the device's
    # (SDRangel: decimation), set from the slider under the modes. Where it
    # SITS follows the frequency -- see the transport's set_frequency -- and,
    # after a band change, starts at the band's edge: on 20 m there is no
    # reason to look below 14 MHz.

    # How long after a band is chosen the rig's arrival there frames it.
    FRAME_BAND_SECONDS = 5.0

    @property
    def has_bandwidth(self):
        return BANDWIDTH in self.capabilities

    @property
    def bandwidth(self):
        """The sampled band's width in Hz, or None."""
        return self.controller.bandwidth if self.has_bandwidth else None

    def bandwidth_choices(self):
        """The widths the SDR can sample, narrowest first."""
        return self.controller.bandwidth_choices() if self.has_bandwidth else []

    def set_bandwidth(self, hz):
        """Sets the width -- once the slider settles -- then frames the band again."""
        self._pending_bandwidth = int(hz)
        timer = getattr(self, "_bandwidth_timer", None)
        if timer is not None:
            try:
                self.root.after_cancel(timer)
            except Exception:
                pass
        self._bandwidth_timer = self.root.after(self.VOLUME_SETTLE_MS,
                                                self._apply_bandwidth)

    def _apply_bandwidth(self):
        self._bandwidth_timer = None
        width = getattr(self, "_pending_bandwidth", None)
        if not self.has_bandwidth or width is None:
            return
        if self.controller.set_bandwidth(width):
            # Wider or narrower, the view is placed afresh on the band the
            # receiver is in -- a narrower one may no longer hold the signal.
            hz = self._model.role_frequency("rx")
            if hz:
                self._sent_hz = hz
                band = self._band_of(hz)
                if band is not None:
                    self.controller.set_frequency(hz, band=band)
                else:
                    self.controller.set_frequency(hz)

    def frame_band(self, start, end):
        """
        A band was chosen: when the rig arrives in it, the SDR's view starts
        at its lower edge. Only where the transport can place its view.
        """
        self._frame_band = (int(start), int(end), monotonic())

    def _framing_for(self, hz):
        """The (start, end) to frame `hz` in, if a band was just chosen and hz is in it."""
        pending = getattr(self, "_frame_band", None)
        if pending is None or not self.has_bandwidth:
            return None
        start, end, asked = pending
        if monotonic() - asked > self.FRAME_BAND_SECONDS:
            self._frame_band = None
            return None
        if start <= hz <= end:
            self._frame_band = None
            return (start, end)
        return None

    def _band_of(self, hz):
        """The amateur band (start, end) holding hz, from the model's list, or None."""
        for entry in getattr(self._model, "BANDS", ()) or ():
            try:
                _, start, end = entry[:3]
            except (TypeError, ValueError):
                continue
            if start <= hz <= end:
                return (int(start), int(end))
        return None

    # -- RF gain -------------------------------------------------------------
    #
    # The SDR hardware's front-end gain, where the transport knows how to set
    # it (SDRangel with an RTL dongle; over rigctl, a program with Hamlib's RF
    # level -- SDRoxide once released -- in percent of its range, not dB). Ridden while listening -- CW operators
    # turn it down to drop the noise under a weak signal -- so it is sent once
    # the slider settles, as volume and squelch are.

    @property
    def has_rf_gain(self):
        return RF_GAIN in self.capabilities

    @property
    def rf_gain(self):
        """The RF gain -- in dB, or percent over rigctl -- or None."""
        return self.controller.rf_gain if self.has_rf_gain else None

    @property
    def rf_gain_auto(self):
        """True while the hardware's own AGC sets the gain -- the slider does nothing then."""
        return bool(self.has_rf_gain and getattr(self.controller, "rf_gain_auto", False))

    def rf_gain_range(self):
        """(lowest, highest) in dB."""
        return (self.controller.rf_gain_range() if self.has_rf_gain else None) or (0.0, 50.0)

    def rf_gain_steps(self):
        """The hardware's gain steps, in dB -- what one knob click moves between."""
        return self.controller.rf_gain_steps() if self.has_rf_gain else []

    def rf_gain_text(self, db):
        """
        A gain as it will be set -- at the hardware's nearest step: "32.8 dB",
        or over rigctl, which knows no dB, a share of the range: "60 %".
        """
        if not self.has_rf_gain:
            return ""
        value = self.controller.snap_rf_gain(db)
        # FIX: the transport says what its gain is counted in -- dB unless it says.
        if getattr(self.controller, "rf_gain_unit", "dB") == "%":
            return f"{value:.0f} %"
        return f"{value:.1f} dB"

    def rf_gain_blocked(self):
        """Why the RF gain cannot be set just now -- or None if it can."""
        if not self.has_rf_gain:
            return (f"not available with {self.profile.name}" if self.connected
                    else "needs a connected SDR")
        if self.rf_gain_auto:
            return f"set by the hardware's AGC -- switch it off in {self.profile.name}"
        return None

    def rf_gain_toward(self, shown, value):
        """
        The gain a knob move reaches: the move read as a DIRECTION, to the
        hardware's next real step that way, however far apart they are -- an
        RTL dongle's run 0, 0.9, 1.4, 2.7 ... 49.6 dB. None if it goes nowhere.
        """
        steps = self.rf_gain_steps()
        if not steps:
            return None
        shown = shown or 0.0
        if value > shown:
            above = [step for step in steps if step > shown + 1e-6]
            return min(above) if above else max(steps)
        if value < shown:
            below = [step for step in steps if step < shown - 1e-6]
            return max(below) if below else min(steps)
        return None

    def set_rf_gain(self, db):
        """Sets the RF gain -- once the slider stops moving."""
        self._pending_rf_gain = float(db)
        timer = getattr(self, "_rf_gain_timer", None)
        if timer is not None:
            try:
                self.root.after_cancel(timer)
            except Exception:
                pass
        self._rf_gain_timer = self.root.after(self.VOLUME_SETTLE_MS, self._apply_rf_gain)

    def _apply_rf_gain(self):
        self._rf_gain_timer = None
        if self.has_rf_gain and getattr(self, "_pending_rf_gain", None) is not None:
            self.controller.set_rf_gain(self._pending_rf_gain)

    # -- squelch -------------------------------------------------------------
    @property
    def has_squelch(self):
        return SQUELCH in self.capabilities

    def squelch_range(self):
        """(bottom, top) of the squelch threshold, in the SDR's own units."""
        return self.profile.squelch_range or (-150.0, 0.0)

    @property
    def squelch(self):
        """The squelch threshold, in the SDR's own units -- or None."""
        return self.controller.squelch if self.has_squelch else None

    def squelch_text(self, value):
        """A threshold as the SDR would show it: "-95 dBFS"."""
        unit = self.profile.squelch_unit
        return f"{value:.0f} {unit}" if unit else f"{value:.2f}"

    def set_squelch(self, value):
        """Sets the threshold -- once the slider stops moving, as volume does."""
        self._pending_squelch = float(value)
        timer = getattr(self, "_squelch_timer", None)
        if timer is not None:
            try:
                self.root.after_cancel(timer)
            except Exception:
                pass
        self._squelch_timer = self.root.after(self.VOLUME_SETTLE_MS,
                                              self._apply_squelch)

    # Gqrx's own A button, reproduced -- its MainWindow::setSqlLevelAuto():
    # the current signal plus 3 dB, unless that comes out above -10 dBFS, in
    # which case the squelch is left alone rather than set where nothing
    # could open it. (Older Gqrx added 1 dB; this follows the current one.)
    AUTO_SQUELCH_MARGIN_DB = 3.0
    AUTO_SQUELCH_CEILING_DBFS = -10.0

    @property
    def can_auto_squelch(self):
        """A needs the signal level as well as a squelch, both in dBFS."""
        return (self.has_squelch and SIGNAL in self.capabilities
                and self.profile.squelch_unit == "dBFS"
                and not self._signal_over_s9)

    def auto_squelch(self):
        """
        Sets the squelch just above what is being received now -- Gqrx's A.

        On a quiet channel that closes the squelch over the noise; on a busy
        one, it sets it just above that signal. The signal is read fresh, not
        taken from the last poll, so it is what is there as the button is
        pressed.
        """
        if not self.can_auto_squelch:
            return
        signal = self.controller.get_level("STRENGTH")
        if signal is None:
            return
        level = signal + self.AUTO_SQUELCH_MARGIN_DB
        if level > self.AUTO_SQUELCH_CEILING_DBFS:
            return
        # With the SDR's receiver stopped, the signal reads -200 dBFS and the
        # sum lands below the range; held at the bottom, which is "open".
        bottom, top = self.squelch_range()
        self._pending_squelch = None
        self.controller.set_level("SQL", round(max(bottom, min(top, level)), 1))
        self._audio_changed()

    def reset_squelch(self):
        """Opens the squelch fully -- Gqrx's R: the bottom of its range."""
        if self.has_squelch:
            self._pending_squelch = None
            self.controller.set_level("SQL", self.squelch_range()[0])
            self._audio_changed()

    def _apply_squelch(self):
        self._squelch_timer = None
        pending, self._pending_squelch = getattr(self, "_pending_squelch", None), None
        if self.has_squelch and pending is not None:
            # To a thousandth: a rigctld's squelch runs 0 to 1.
            self.controller.set_level("SQL", round(pending, 3))

    # -- signal strength ------------------------------------------------------
    # WHERE S9 IS, in dBFS. Not derivable: dBFS is "below the loudest signal
    # the SDR can digitise", so the figure a true S9 gives depends on the
    # hardware and its gain. Gqrx itself shows dBFS, not S-units.
    #
    # CALIBRATED TO BAND NOISE, the one reference to hand: on the first
    # station this ran against, HF noise sat near -80 dBFS on Gqrx's -100 to
    # 0 meter, and a quiet band conventionally reads about S3. Six S-units of
    # 6 dB above that puts S9 at -44 dBFS. (The first guess, -60, had that
    # noise reading nearly S6.) A different SDR or gain moves the noise, and
    # this with it; a signal the rig's own meter calls S9 would be a better
    # reference once the rig's S-meter reports are wired.
    S9_DBFS = -44.0
    DB_PER_S_UNIT = 6.0
    # Gqrx reports -200 when its receiver is stopped: "no reading", not a
    # very weak signal. Anything this low is taken the same way.
    NO_READING_DBFS = -190.0

    @property
    def signal_dbfs(self):
        """
        The signal as the SDR gives it -- in dBFS, or over S9 where its
        profile says so (see signal_text) -- or None where there is no real
        reading.
        """
        if SIGNAL not in self.capabilities:
            return None
        level = self.controller.signal
        if level is None or level <= self.NO_READING_DBFS:
            return None
        return level

    # S9 in dBm on HF -- 50 microvolts into 50 ohms -- for showing a
    # reading given relative to S9 (Hamlib's STRENGTH) as dBm.
    S9_DBM = -73.0

    @property
    def _signal_over_s9(self):
        """
        True where the SDR gives the signal as decibels over S9 -- Hamlib's
        own meaning of STRENGTH (SDRoxide, rigctld) -- rather than dBFS.
        """
        return getattr(self.profile, "signal_unit", "dBFS") == "S9dB"

    def signal_text(self):
        """
        The signal as a figure with its unit -- "-73 dBFS", or "-72 dBm" where
        the SDR gives it over S9 -- or "" without one.
        """
        level = self.signal_dbfs
        if level is None:
            return ""
        if self._signal_over_s9:
            return f"{level + self.S9_DBM:.0f} dBm"
        return f"{level:.0f} dBFS"

    def s_units(self):
        """
        The signal on the S-meter's own scale -- 0 to 9 for S0 to S9, then
        9 plus the decibels over S9, as sCTkSMeterBar draws it -- or None.

        FIX: a reading already over S9 (Hamlib's STRENGTH -- SDRoxide) is used
        as it is; it was taken as dBFS, so SDRoxide's -72 dBm (+1 over S9)
        read as "1 dBFS", pinned far over S9.
        """
        level = self.signal_dbfs
        if level is None:
            return None
        over = level if self._signal_over_s9 else level - self.S9_DBFS
        if over <= 0:
            return max(0.0, 9.0 + over / self.DB_PER_S_UNIT)
        return 9.0 + over

    def _signal_changed(self):
        if callable(self.on_signal):
            try:
                self.on_signal()
            except Exception as err:
                print(f"[sdr] signal callback failed: {err}")

    def _audio_changed(self):
        """The SDR's own level, mute or squelch was changed in the SDR itself."""
        if callable(self.on_audio):
            try:
                self.on_audio()
            except Exception as err:
                print(f"[sdr] audio callback failed: {err}")

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
        if FILTER not in self.capabilities:
            print(f"[sdr] {self.profile.name} does not accept a filter width")
            return
        if self.controller.set_filter_width(width_hz):
            self._set_model_filter(self.controller.filter_width)

    def reset_filter(self):
        """Back to the configured default width for the current mode."""
        sdr_mode = self.profile.to_sdr.get(self._model.mode_of(self._model.rx_vfo), "USB")
        self.set_filter(self.controller.default_filter_width(sdr_mode))

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