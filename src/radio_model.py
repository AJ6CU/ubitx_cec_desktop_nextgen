#!/usr/bin/python3
"""
RadioState -- what the rig last told us, and nothing else.

WHY THIS EXISTS

The frequency is currently held in a widget (theVFO), read back in at least
three forms, and quantised on the way in by a setting that belongs to the
tuning dial. Consumers ask for whatever shape they need:

    getIntPrimaryVFO()          integer Hz
    getFormattedPrimaryVFO()    a display string, with the user's delimiter
    ...plus the transmit frequency, which is sometimes offset by the CW
       sidetone and sometimes not, depending on who is asking

and channels.py opens by saving the tuning preset, forcing it to its finest
value, and restoring it on close -- because otherwise a channel recalled at
7.032.100 comes back as 7.032.000. That workaround is load-bearing in a file
about memories, and it is invisible to anyone reading either one.

THE RULE HERE

    Stored once, as an integer number of Hz. Everything else is derived.

No formatting in the model. No sidetone in the stored value. No rounding,
ever -- if the firmware quantises on write, the radio layer sets the finest
preset before writing and puts it back afterwards, always, so no caller has
to know.

WHAT THE ROLE MODEL REMOVES

theVFO spends about 228 lines on _CW, _RIT, _SPLIT and three ManageLabels
companions, deciding which frequency is displayed where and what the labels
say this time. That machinery exists because the display changes meaning
with state.

Asking instead which VFO is RECEIVING and which is TRANSMITTING makes the
question disappear: receive is always on the left, transmit always on the
right, and the only thing that changes is a small label saying which VFO is
currently filling each role.

POPULATED BY THE RIG, NOT THE INTERFACE

The protocol is request-then-confirm: the interface sends a command and waits
to be told what happened. So nothing in the interface writes to this object.
The xx_UX_ handlers in mainScreen write to it when the rig reports, and the
view redraws from it. A control that changed state locally would be guessing.

Machine firmware encodes  DFT(default) = 0, LSB=2, USB=3, CWL=4,CWU=5
DFT only used for EEPROM channels, 1 reserved for other
"""

MODES = ("DFT", "ERR", "LSB", "USB", "CWL", "CWU")

# The rig's memory channels. All twenty carry a frequency and a mode; only the
# first nine carry a label, because the tenth label slot is broken in the v2
# CEC firmware (see EEPROM.py). Slot 10 onward is still a full channel -- it
# just has no name.
# Where the conventional sideband changes: lower below, upper above. Used
# wherever the application has to CHOOSE a sideband -- a channel stored as DFT,
# or CW arriving from SDR++, which has no CWL/CWU distinction.
#
# 10 MHz rather than "20 m and up": the two agree on every band but 30 m
# (10.1 MHz), which has no voice allocation and whose digital modes run on
# USB. It is the usual convention, and the uBITX firmware's own default.
SIDEBAND_SPLIT_HZ = 10_000_000

CHANNEL_SLOTS = 20
LABEL_SLOTS = 9


class RadioModel:
    """
    Everything the interface displays, in one place and one form.

    Every frequency is an integer number of Hz. Every derived form -- the
    display string, the transmit frequency with its sidetone offset, the
    receive frequency with its RIT offset -- is a method, computed when asked.
    """

    def __init__(self, on_change=None, schedule=None):
        """
        Args:
            on_change: Called when something has changed and the view should
                redraw. One callback, not one per field -- see changed().
            schedule: A function taking (milliseconds, callable), normally a
                widget's `after`. Used to coalesce a burst of reports into a
                single redraw. Without it, every report redraws immediately.
        """
        self._on_change = on_change
        # Reports received from the rig -- see changed().
        self.reports = 0
        self._schedule = schedule
        self._pending = False

        # Held while a transport is mid-sequence. See suspend_notifications.
        self._suspended = 0
        # The active VFO as it was before a borrow began. See role_vfo.
        self._frozen_active = None

        # --- what the rig has told us ------------------------------------
        self.vfo_a = 14_000_000
        self.vfo_b = 14_000_000
        self.active = "a"              # which VFO the rig calls primary
        self.mode_a = "USB"
        self.mode_b = "USB"

        self.split = False
        self.rit = False
        # RIT AS THE RIG DOES IT, which is the opposite of the obvious model.
        #
        # With RIT on, the VFO keeps moving as you tune -- it IS the receive
        # frequency. What stays put is the frequency captured at the moment
        # RIT was switched on, which becomes where you TRANSMIT. The old
        # display called them "RIT RX Freq" and "RIT TX Freq".
        #
        # The first version here had it backwards -- VFO fixed, offset added
        # on top -- so tuning receive with RIT on wrote the unchanged VFO
        # back to the rig and nothing moved. Storing the base and DERIVING
        # the offset matches what the hardware is actually doing.
        self.rit_base_hz = 0

        self.locked = False
        self.muted = False
        self.tx_inhibit = False
        self.transmitting = False

        # --- the rig's memory channels ------------------------------------
        # One entry per slot, None until read. Read the first time the
        # Channels tab is opened, not at startup: the startup dump is already
        # long, and this is 38 more replies for something you may not look at.
        #
        # Each entry: {"freq": int, "mode": str, "label": str or None,
        #              "show_label": bool}. label is None for slots 10-20,
        # which have no label to show.
        self.channels = [None] * CHANNEL_SLOTS
        self.channels_state = "unread"      # "unread", "reading" or "read"
        self.channels_progress = 0          # replies received so far
        self.channels_expected = 0          # replies a full read produces
        # Reads the rig never answered, even after retrying: (category, slot).
        # Kept so the tab can say so, rather than showing those slots as
        # empty -- which would be the interface guessing.
        self.channels_failed = []
        # Reads finished so far, by kind -- so progress can be shown in
        # channels and labels, which is how the operator thinks of them,
        # rather than as a count of 38 reads.
        self.channels_done = {"Freq": 0, "Label": 0, "ShowLabel": 0}
        # Addresses whose write the rig never acknowledged, from the last
        # "Write to radio". The read-back that follows shows what they hold.
        self.channels_write_failed = []

        self.cw_tone = 600             # Hz. The TX offset in a CW mode.
        # Added to the tone to give the full offset. Reported by the rig from
        # its EEPROM (vh_); zero unless the operator has trimmed it.
        self.cw_tweak = 0

        # THE RIG ROUNDS EVERY FREQUENCY IT IS GIVEN to the active tuning
        # preset. Ask for 14.024.510 with the preset at 100 Hz and it stores
        # 14.024.500 and reports that back.
        #
        # It is a dial-step setting with a side effect on frequency entry,
        # which is why channels.py forced the preset to its finest value and
        # put it back afterwards. Anything comparing what it asked for
        # against what the rig confirmed has to know about it.
        self.tuning_presets = [10, 20, 50, 100, 1000]
        self.active_tuning_preset = 4          # 1-based, as the rig counts
        self.filter_hz = 2600

        # --- telemetry, as reported -------------------------------------
        # Held raw. The meters decide how to show them; nothing here knows
        # about S units or bar segments.
        self.s_value = 0.0             # S units, 0-9 then dB over
        self.pwr = 0.0                 # watts
        self.swr = 1.0

        self._callsign = "AJ6CU/9"
        self._firmware = "CEC 2.0"

        # --- how the user wants it shown ---------------------------------
        # A display preference the formatter needs, NOT a property of the
        # frequency. It is REGISTERED for rather than read on demand: the
        # configuration manager already notifies observers when a value
        # changes, and theVFO, channels and piRadio all use it. That is the
        # right channel -- a consumer that polls, or reaches into the main
        # screen for a label, gets a stale answer the moment the setting
        # changes while its window is open.
        self.delimiter = "."

    # ------------------------------------------------------------------
    # Telling the view
    # ------------------------------------------------------------------
    def changed(self):
        """
        Says that something has changed, without saying what.

        ONE NOTIFICATION, NOT ONE PER FIELD, because almost everything the
        view shows is derived. role_frequency("tx") depends on vfo_a, vfo_b,
        active, split, rit, rit_offset, mode and cw_tone -- so a view
        registered for "mode" would not know to redraw when split changed.
        Per-field observers would need either a dependency graph or every
        consumer registering for eight things, and the first person to add a
        derived value would forget one.

        Recomputing everything cannot be out of step. That is worth more than
        the redraws it costs, and the cost is handled below rather than by
        making the notification cleverer.

        Note this is deliberately unlike ConfigurationManager's per-key
        observers. Preferences are independent of each other, change rarely,
        and have distant consumers -- exactly the case where per-key is right.
        """
        # HOW MANY REPORTS HAVE ARRIVED. Only the transport writes to the
        # model, so this counts what the rig has actually said -- which is
        # the only way to tell a radio that is answering from one that is
        # switched off behind an open port. The starting values below are
        # seeded, so they cannot be used for that.
        self.reports += 1

        if self._on_change is None:
            return

        if self._schedule is None:
            self._on_change()
            return

        # COALESCED. A burst of reports -- the startup dump, or an S-meter
        # arriving ten times a second -- becomes one redraw on the next idle
        # pass instead of ten. The view stays simple and the rate stops
        # being its problem.
        if not self._pending:
            self._pending = True
            self._schedule(0, self._flush)

    def _flush(self):
        self._pending = False
        if self._suspended:
            # Still mid-sequence. The change is not lost -- resuming asks
            # for a redraw, which will show wherever things ended up.
            return
        if self._on_change is not None:
            self._on_change()

    def suspend_notifications(self):
        """
        Stops the view redrawing until the matching resume.

        FOR TRANSIENT STATES THE OPERATOR SHOULD NOT SEE. Writing a transmit
        frequency in split means borrowing the primary slot: the rig really
        does make the other VFO primary for a moment and really does report
        it, and a view that redraws faithfully shows the transmit frequency
        appearing in the receive panel and then vanishing. Accurate, and
        confusing.

        The borrow is a detail of how the transport reaches a VFO the rig
        will not address directly. Holding the redraw until the slot has been
        handed back shows the operator the result rather than the mechanism.

        Counted rather than a flag, so nested or overlapping sequences cannot
        resume each other early.
        """
        self._suspended += 1
        print(f"[susp] suspend -> {self._suspended}")
        if self._frozen_active is None:
            self._frozen_active = self.active

    def resume_notifications(self):
        """Releases a suspend, and redraws if that was the last one."""
        if self._suspended:
            self._suspended -= 1
        print(f"[susp] resume  -> {self._suspended}")
        if not self._suspended:
            self._frozen_active = None
            self.changed()

    def follow_configuration(self, config):
        """
        Takes the display preferences from configuration, and keeps them.

        Called once at startup. Anything registered here updates itself
        afterwards, so no consumer has to ask twice or know where the value
        came from.
        """
        self.delimiter = config.get_NUMBER_DELIMITER()
        config.register_observer("NUMBER DELIMITER", self._set_delimiter)

    def _set_delimiter(self, value):
        self.delimiter = value

    # ------------------------------------------------------------------
    # Roles. Ask which VFO is doing what, never which VFO is "primary".
    # ------------------------------------------------------------------
    @property
    def tx_vfo(self):
        """
        The VFO that transmits: the one NOT displayed when split, otherwise
        the active one.

        NOT hardcoded to "b". The rig transmits on whichever VFO is not
        currently primary, and primary can be either -- so with B active and
        split on, the transmit VFO is A. Assuming B is right half the time,
        which is the worst kind of wrong.
        """
        if not self.split:
            return self._role_active
        return "b" if self._role_active == "a" else "a"

    @property
    def _role_active(self):
        """
        The active VFO for the purpose of working out roles.

        FROZEN DURING A BORROW. Writing a transmit frequency in split makes
        the rig switch primary for a moment, and `active` follows it --
        which inverts tx_vfo, because transmit is defined as the VFO that is
        not active. A dial turned in that window computed against the
        receive VFO and wrote to it, so adjusting transmit moved receive.

        Suspending notifications hid the borrow from the DISPLAY but not
        from this. Freezing the value hides it from both, which is what
        "the borrow is a mechanism, not a state" has to mean.
        """
        return self._frozen_active or self.active

    @property
    def rx_vfo(self):
        """The VFO that receives. Always the active one."""
        return self._role_active

    @property
    def rit_offset(self):
        """
        How far receive has been tuned from where RIT was switched on.

        DERIVED, never stored: it is a consequence of the VFO and the base,
        and storing a consequence is how two values get out of step.
        """
        if not self.rit or not self.rit_base_hz:
            return 0
        return self.frequency(self.rx_vfo) - self.rit_base_hz

    def role_vfo(self, role):
        """
        Which VFO currently fills a role.

        RAISES ON ANYTHING BUT "rx" OR "tx", deliberately. This used to
        treat every argument that was not "tx" as receive, which meant a VFO
        NAME passed by mistake -- "a" or "b" -- silently became a role and
        did something plausible. It happened twice: once sending VFO B's
        frequency to the rig, and once retuning the transmit VFO when the
        band picker meant receive.

        The same reasoning as frequency(): a method that cannot fail hides
        its misuse, and both mistakes cost far more to find than a traceback
        would have.
        """
        if role == "tx":
            return self.tx_vfo
        if role == "rx":
            return self.rx_vfo
        raise ValueError(
            f'role_vfo() takes a role -- "rx" or "tx" -- not {role!r}. '
            f'For a VFO, use frequency() or mode_of().')

    # ------------------------------------------------------------------
    # Frequencies. Integer Hz throughout.
    # ------------------------------------------------------------------
    def frequency(self, which):
        """
        The stored frequency of a VFO. No offsets, no formatting.

        Args:
            which: "a", "b", or "p" for whichever is primary.

        RAISES ON ANYTHING ELSE, deliberately. This used to return vfo_b for
        any argument that was not "a", so passing a ROLE -- "rx" or "tx" --
        silently handed back VFO B's frequency. The caller got a plausible
        number, the rig was told to tune to it, and the only symptom was a
        dial that appeared to jump somewhere unrelated.

        A method that cannot fail is a method that hides its misuse. Use
        role_frequency() for a role; this one takes a VFO.
        """
        if which == "a" or (which == "p" and self.active == "a"):
            return self.vfo_a
        if which == "b" or (which == "p" and self.active == "b"):
            return self.vfo_b
        raise ValueError(
            f'frequency() takes a VFO name -- "a", "b" or "p" -- not {which!r}. '
            f'For a role, use role_frequency().')

    def set_frequency(self, which, hz):
        """
        Stores a frequency exactly as given.

        NOT ROUNDED. The tuning preset decides how far the DIAL moves per
        click; it has nothing to do with what a frequency may be. If the
        firmware quantises on write, that belongs in the radio layer, which
        can set the finest preset around the write and restore it -- once,
        for every caller, instead of channels.py doing it by hand.

        which is vfo ("a" or "b").  If which is "p", then the active vfo is updated
        """
        print("model set_frequency", which, hz)
        hz = int(hz)
        if which == "a" or (which == "p" and self.active =="a"):
            self.vfo_a = hz
        else:
            self.vfo_b = hz

    def cw_tx_offset(self, mode):
        """
        How far the transmit frequency sits from the VFO in a CW mode, signed.

        THE SIGN DEPENDS ON THE SIDEBAND. CWL transmits above the dial and
        CWU below it:

            CWL   tx = vfo + (tone + tweak)
            CWU   tx = vfo - (tone + tweak)

        This is what the previous interface did against the real rig -- its
        theVFO.set_CW_OffsetforTX -- and it is the ONE place the rule lives.
        The first version here subtracted the tone for both sidebands, so
        every CWL transmit frequency on screen was out by twice the tone: a
        500 Hz tone showed a transmit frequency 1 kHz from where the rig
        actually transmitted.

        Zero outside CW.
        """
        magnitude = int(self.cw_tone) + int(self.cw_tweak)
        if mode == "CWL":
            return magnitude
        if mode == "CWU":
            return -magnitude
        return 0

    def role_frequency(self, role):
        """
        What a role is actually on, offsets included.

        This is the number to DISPLAY. Receive carries the RIT offset when
        RIT is on; transmit carries the CW sidetone offset in a CW mode.
        Neither is stored, because neither is a property of the VFO -- they
        are consequences of the current state, and storing a consequence is
        how the two get out of step.
        """
        which = self.role_vfo(role)
        hz = self.frequency(which)

        # Receive is simply the VFO, RIT or not: under RIT the VFO is what
        # moves. Transmit, out of split, stays where RIT was switched on.
        # In split, transmit is the other VFO as usual and RIT only
        # concerns receive.
        if role == "tx" and self.rit and not self.split and self.rit_base_hz:
            hz = self.rit_base_hz
        if role == "tx":
            return hz + self.cw_tx_offset(self.mode_of(which))
        return hz

    def tuning_step_hz(self):
        """The active preset's size, which is also the rounding granularity."""
        index = max(1, min(len(self.tuning_presets),
                           int(self.active_tuning_preset)))
        return int(self.tuning_presets[index - 1])

    def as_the_rig_would_store(self, hz):
        """
        What the rig will actually hold if asked for this frequency.

        Used to decide whether a confirmation matches: comparing the exact
        value fails whenever the preset is coarser than the step, and the
        sequence then waits for a report that can never arrive.
        """
        step = self.tuning_step_hz()
        if step <= 1:
            return int(hz)
        return int(round(int(hz) / step) * step)

    def role_to_vfo_hz(self, role, displayed_hz):
        """
        The value to WRITE to a VFO, given what the operator sees.

        THE INVERSE OF role_frequency, and it has to exist. That method
        subtracts the CW sidetone from the transmit frequency for display, so
        a caller that takes the displayed number, adds a step, and writes the
        result straight to the VFO loses the offset:

            displayed = vfo - 600
            asked for = displayed + 1000  =  vfo + 400
            written   = vfo + 400
            displayed = vfo + 400 - 600   -- moved 400, not 1000

        Which is exactly what a 1 kHz step did while the tone was 600 Hz.

        Receive under RIT returns the VFO unchanged: tuning there moves the
        offset, not the frequency, so there is nothing to write.
        """
        which = self.role_vfo(role)
        # No RIT case. Under RIT the VFO IS the receive frequency, so tuning
        # receive writes the VFO like any other time -- which is exactly
        # what the rig expects. The earlier version returned the unchanged
        # VFO here, so the write was a no-op and RIT tuning did nothing.
        if role == "tx":
            return self.transmit_vfo_hz(which, displayed_hz)
        return int(displayed_hz)

    def transmit_vfo_hz(self, which, displayed_hz):
        """
        What to write to VFO `which` for it to TRANSMIT at displayed_hz.

        The CW rule in ONE place. role_to_vfo_hz uses it for a role; the
        split offsets use it for a VFO NAME, because they have to address
        the VFO that is not primary before split has been confirmed -- when
        the "tx" role would still resolve to the active VFO.
        """
        # The inverse of role_frequency: what is shown has the offset added,
        # so what is written has it taken away again.
        return int(displayed_hz) - self.cw_tx_offset(self.mode_of(which))

    def set_role_frequency(self, role, hz):
        """
        Moves what a role is on.

        Under RIT this moves the VFO, which is the receive frequency; the
        offset follows from it. See rit_base_hz.
        """
        which = self.role_vfo(role)
        self.set_frequency(which, hz)

    def set_active(self, which):
        """
        Records which VFO the rig is displaying.

        THIS IS WHAT `cv` MEANS. The rig reports 0 for A and 1 for B, and it
        is telling you which one is primary -- not asking you to exchange the
        two frequencies.

        Swapping contents here instead was the source of the confusion about
        where the transmit VFO lives: exchange them on every toggle and the
        active one is always in vfo_a, so the model can no longer say which
        VFO is which. It also fights the va/vb handlers, which write to a
        named VFO.
        """
        self.active = "a" if which in ("a", 0, "0") else "b"

    def swap_vfos(self):
        """
        Exchanges the two VFOs' contents.

        A DIFFERENT THING from set_active, and a different rig command. This
        is the A<>B swap an operator asks for deliberately; toggling which
        VFO is displayed leaves both frequencies where they were.
        """
        self.vfo_a, self.vfo_b = (self.vfo_b, self.vfo_a)
        self.mode_a, self.mode_b = (self.mode_b, self.mode_a)

    # ------------------------------------------------------------------
    # Band. DERIVED, not stored.
    #
    # The band is a fact about the frequency, so storing it separately gives
    # two things that can disagree -- and they will, because the rig reports
    # frequency changes and says nothing about bands.
    # ------------------------------------------------------------------
    BANDS = (
        ("160 m", 1_800_000, 2_000_000), ("80 m", 3_500_000, 4_000_000),
        ("60 m", 5_330_000, 5_410_000), ("40 m", 7_000_000, 7_300_000),
        ("30 m", 10_100_000, 10_150_000), ("20 m", 14_000_000, 14_350_000),
        ("17 m", 18_068_000, 18_168_000), ("15 m", 21_000_000, 21_450_000),
        ("12 m", 24_890_000, 24_990_000), ("10 m", 28_000_000, 29_700_000),
    )

    def band_name(self, which=None):
        """
        The amateur band a VFO is in, or None outside one.

        None is a real answer -- the uBITX tunes continuously and general
        coverage receive is a normal thing to do. A caller wanting a label
        can say "out of band" rather than being handed a nearest guess.
        """
        hz = self.frequency(which or self.rx_vfo)
        for name, low, high in self.BANDS:
            if low <= hz <= high:
                return name
        return None

    # ------------------------------------------------------------------
    # Modes
    # ------------------------------------------------------------------
    def mode_of(self, which):
        """The mode of a VFO. Same argument rules as frequency()."""
        if which == "a" or (which == "p" and self.active == "a"):
            return self.mode_a
        if which == "b" or (which == "p" and self.active == "b"):
            return self.mode_b
        raise ValueError(
            f'mode_of() takes a VFO name -- "a", "b" or "p" -- not {which!r}.')

    def set_mode(self, which, mode):
        # newmode = MODES[mode]
        if (which == "a") or (which == "p" and self.active == "a"):
            self.mode_a = mode
        else:
            self.mode_b = mode

    @property
    def mode(self):
        """The active VFO's mode, which is what the interface shows."""
        return self.mode_of(self.active)

    # ------------------------------------------------------------------
    # Display. A function of a number, not a method on a widget.
    # ------------------------------------------------------------------
    def formatted(self, hz, places=3):
        """
        A frequency as a string, grouped with the user's delimiter.

        Here rather than in the view because the delimiter is a preference
        several windows share, and passing a formatter around is less
        trouble than each one reaching into the main screen for a label.

        It takes a NUMBER, not a role or a VFO name -- so the caller has
        already decided what it wants to show, and this only decides how.
        """
        hz = int(hz)
        mhz, rest = divmod(hz, 1_000_000)
        khz, units = divmod(rest, 1000)
        return f"{mhz}{self.delimiter}{khz:03d}{self.delimiter}{units:03d}"

    def role_text(self, role):
        """The string for a role's readout. What the view actually wants."""
        return self.formatted(self.role_frequency(role))

    # ------------------------------------------------------------------
    # Annotations -- the small print under each readout
    # ------------------------------------------------------------------
    def role_note(self, role):
        """
        One line explaining anything unusual about a role's frequency.

        Everything here is DERIVED. Nothing sets a note; it is worked out
        from the state, so it cannot disagree with the number above it.
        """
        if self.locked:
            return "locked"
        if role == "tx":
            if not self.split:
                return "follows rx"
            if self.mode_of(self.tx_vfo).startswith("CW"):
                return self.cw_offset_note(self.mode_of(self.tx_vfo))
            return ""
        if self.rit and self.rit_base_hz:
            base = self.formatted(self.rit_base_hz)
            # The snapshot MEANS different things. Out of split it is where
            # you will transmit; in split transmit is the other VFO, and the
            # snapshot is only where receive started. The original display
            # drew the same distinction, labelling it "RIT TX Freq" in one
            # case and "RIT Base RX Freq" in the other.
            if self.split:
                # Where receive STARTED, which is a raw VFO value -- receive
                # never carries the CW offset.
                return f"rit {self.rit_offset:+d} Hz · from {base}"
            # Where you will TRANSMIT, so it goes through role_frequency and
            # carries the CW sidetone offset like every other transmit
            # figure on screen. Formatting the base directly showed a number
            # 500 Hz away from what the transmit panel said in CW.
            tx = self.formatted(self.role_frequency("tx"))
            return f"rit {self.rit_offset:+d} Hz · tx stays at {tx}"
        return ""

    def cw_offset_note(self, mode):
        """
        The CW offset in words, with its real sign -- "+500 Hz cw tone" in
        CWL, "\u2212500 Hz cw tone" in CWU.

        Every note that names the offset uses this. They used to write the
        minus sign themselves, which was only right for CWU.
        """
        offset = self.cw_tx_offset(mode)
        if offset == 0:
            return ""
        sign = "+" if offset > 0 else "\u2212"
        return f"{sign}{abs(offset)} Hz cw tone"

    # ------------------------------------------------------------------
    # Memory channels -- written by the link as the rig reports each slot
    # ------------------------------------------------------------------
    def _channel(self, index):
        """The entry for a slot, created on first report."""
        if self.channels[index] is None:
            self.channels[index] = {"freq": 0, "mode": "DFT",
                                    "label": None, "show_label": False}
        return self.channels[index]

    def set_channel_freq_mode(self, index, freq, mode):
        if 0 <= index < CHANNEL_SLOTS:
            entry = self._channel(index)
            entry["freq"], entry["mode"] = int(freq), mode

    def set_channel_label(self, index, label):
        # Only the first nine slots HAVE a label; anything reported beyond
        # them is not one.
        if 0 <= index < LABEL_SLOTS:
            self._channel(index)["label"] = str(label).strip()

    def set_channel_show_label(self, index, show):
        if 0 <= index < LABEL_SLOTS:
            self._channel(index)["show_label"] = bool(show)

    @staticmethod
    def default_sideband(hz):
        """The conventional sideband for a frequency: "USB" or "LSB"."""
        return "USB" if int(hz) >= SIDEBAND_SPLIT_HZ else "LSB"

    def channel_is_empty(self, index):
        """True for a slot holding no frequency -- never written."""
        entry = self.channels[index]
        return entry is None or not entry["freq"]

    def split_delta_hz(self):
        """How far transmit sits from receive. Zero when simplex."""
        return self.frequency(self.tx_vfo) - self.frequency(self.rx_vfo)

    # ------------------------------------------------------------------
    # About. Manges information provided in the About page
    # ------------------------------------------------------------------

    def set_callsign(self, callsign):
        self._callsign = callsign

    @property
    def callsign(self):
        return self._callsign

    def set_firmware(self, firmware):
        self._firmware = firmware

    @property
    def firmware(self):
        return self._firmware