#!/usr/bin/python3
"""
SDR_Link -- keeps SDR++ in step with the rig, in both directions.

A second transport, sitting beside uBITX_Link. It talks to SDR++ through
RigctlSDR over rigctl -- SDR++, Gqrx or a rigctld, chosen by the "SDR
Software" setting -- and connects it to the same RadioModel the
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
from time import sleep

import sdr_launcher
import system_audio
from rigctl_sdr import RigctlSDR
from sdr_programs import profile_for, CW_EITHER, FILTER, VOLUME, MUTE, SQUELCH, SIGNAL


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

        "rigctl" is all there is today. SDRangel's REST will be a second
        class here, not a variation on the first: it addresses device sets
        and channels by index, needs a discovery step to find the right
        demodulator, and can push changes rather than be polled. The entry
        says WHICH transport; how each works is code.
        """
        if profile.protocol in ("rigctl", "none"):
            return RigctlSDR(self.root, profile)
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
        self.controller.on_volume = lambda level: self._audio_changed()
        self.controller.on_mute = lambda muted: self._audio_changed()
        self.controller.on_squelch = lambda level: self._audio_changed()
        self.controller.on_signal = lambda level: self._signal_changed()
        self.controller.on_disconnect = self._lost
        self._sent_frequency = None
        self._sent_mode = None
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
        self.controller.on_volume = lambda level: self._audio_changed()
        self.controller.on_mute = lambda muted: self._audio_changed()
        self.controller.on_squelch = lambda level: self._audio_changed()
        self.controller.on_signal = lambda level: self._signal_changed()
        self.controller.on_disconnect = self._lost

        if not self.controller.connect(host, port):
            print(f"[sdr] could not reach {self.profile.name} at {host}:{port}")
            self._report(False)
            return False

        self.controller.start()

        # Forget what was sent before, so the rig's current state is pushed
        # in full rather than compared against a previous connection.
        self._sent_hz = None
        self._sent_mode = None
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
            print(f"[sdr] {self.profile.name} did not answer; giving up for now")
            return
        self._waiting_for_program = self.root.after(
            wait_ms, lambda: self.connect_when_ready(attempts - 1, wait_ms))

    def _lost(self):
        """The controller found the connection gone -- SDR++ closed, say."""
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
            self.controller.set_frequency(hz)

        rig_mode = self._model.mode_of(self._model.rx_vfo)
        # The SDR's own name for the mode -- SDR++ has one CW, Gqrx two.
        sdr_mode = self.profile.to_sdr.get(rig_mode)
        if sdr_mode and sdr_mode != self._sent_mode:
            self._sent_mode = sdr_mode
            # The mode's own default width, not whatever the last mode used:
            # a 2600 Hz SSB filter carried into CW lets in everything around
            # the signal. The defaults come from the configuration.
            width = self.controller.default_filter_width(sdr_mode)
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
                and self.profile.squelch_unit == "dBFS")

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
        self.controller.set_level("SQL", round(max(bottom, min(top, level)), 1))
        self._audio_changed()

    def reset_squelch(self):
        """Opens the squelch fully -- Gqrx's R: the bottom of its range."""
        if self.has_squelch:
            self.controller.set_level("SQL", self.squelch_range()[0])
            self._audio_changed()

    def _apply_squelch(self):
        self._squelch_timer = None
        if self.has_squelch and getattr(self, "_pending_squelch", None) is not None:
            self.controller.set_level("SQL", round(self._pending_squelch, 1))

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
        """The signal in dBFS, or None where there is no real reading."""
        if SIGNAL not in self.capabilities:
            return None
        level = self.controller.signal
        if level is None or level <= self.NO_READING_DBFS:
            return None
        return level

    def s_units(self):
        """
        The signal on the S-meter's own scale -- 0 to 9 for S0 to S9, then
        9 plus the decibels over S9, as sCTkSMeterBar draws it -- or None.
        """
        dbfs = self.signal_dbfs
        if dbfs is None:
            return None
        over = dbfs - self.S9_DBFS
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