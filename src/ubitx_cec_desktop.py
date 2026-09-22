#!/usr/bin/python3
"""
uBITX CEC Desktop -- a desktop interface for KD8CEC-powered uBITX radios.

Talks to the rig over serial or network through uBITX_Link, which speaks the
protocol the Nextion display used. The SDR side is not wired yet.

HOW IT IS PUT TOGETHER

    view (this file)  reads RadioModel, sends commands
          |                                    ^
          v reads only                         | commands only
    RadioModel        what the rig last reported
          ^ writes
    uBITX_Link        the protocol, and nothing else

THE ONE RULE: no view code writes to the model. A control sends a command and
changes nothing; the rig confirms; the confirmation updates the model; the
model asks for one redraw. Grep for `self.model.<something> =` outside the
transport and the only hits should be seeding values at startup.

That discipline is what makes the display trustworthy. A control that changed
the state locally would show what it asked for rather than what happened, and
the two diverge the first time the rig refuses.

WHAT IS WORTH KNOWING WHILE READING IT

  * Two frequency panels, laid out by ROLE rather than by VFO. Receive is
    always on the left and transmit always on the right, so nothing swaps
    sides when split turns on -- only the small `vfo a` / `vfo b` label under
    each heading changes.

  * Digit-select tuning, via sCTkFrequencyDisplay. Clicking a digit selects
    it and the selection IS the step, so there is no separate tuning-preset
    control to keep in sync.

  * One meter split in two: signal under the receiving frequency, power and
    SWR under the transmitting one. Neither half is ever dead.

  * Controls a backend cannot serve yet are DISABLED rather than absent, so
    the layout does not shift when a capability arrives.

  * The rig can only write to the primary VFO, so setting a transmit
    frequency in split borrows the primary slot, writes, and hands it back --
    a sequence that waits for each confirmation. See uBITX_Link.

See ARCHITECTURE.md for the reasoning, and TODO.md for what is not done.
"""
import json
import os
import random
import serial
import tkinter as tk
import time

import customtkinter as ctk

import globalvars as gv
from configuration import ConfigurationManager
from channel_sets import ChannelSets, LABEL_MAX as SET_LABEL_MAX
from radio_model import RadioModel, LABEL_SLOTS, CHANNEL_SLOTS
from stub_radio import StubRadio
from sdr_link import SDR_Link
from scanner import Scanner
from ubitx_link import uBITX_Link

from scustomtkinter import (
    sCTk, sCTkFrame, sCTkNotebook,
    sCTkLabelPrimary, sCTkLabelSecondary, sCTkLabelTertiary,
    sCTkButtonPrimary, sCTkButtonSecondary, sCTkButtonTertiary,
    sCTkSMeterBar, sCTkDialContinuous, sCTkSpinbox,
    sCTkSegmentedButton, sCTkSwitch, sCTkComboBox, sCTkEntryPrimary,
    sCTkOptionMenuPrimary, sCTkMessagebox,
    sCTkCheckBox, sCTkFrequencyDisplay, sCTkSlider,
    sCTkProgressBar, sCTkTableview,
)

# ---------------------------------------------------------------------------
# Simulated radio
# ---------------------------------------------------------------------------
# BANDS = [
#     ("160 m", 1_840_000), ("80 m", 3_573_000), ("40 m", 7_074_000),
#     ("30 m", 10_136_000), ("20 m", 14_074_000), ("17 m", 18_100_000),
#     ("15 m", 21_074_000), ("12 m", 24_915_000), ("10 m", 28_074_000),
# ]
MODES = ["LSB", "USB", "CWL", "CWU"]
CW_TONE_HZ = 500

# The widest useful filter for each mode, and what reset returns to.
#
# Kept per mode because they are not comparable: 2600 Hz is normal for voice
# and useless for CW, where it lets in everything either side of the signal
# you are working. Both are settable under Setup.
# How long a dial target survives without another detent.
#
# Long enough that a wheel spin accumulates as one gesture, short enough that
# the next deliberate turn starts from where the radio actually is.
TURN_ACCUMULATE_SECONDS = 0.6

# The Channels tab.
RADIO_SET = "Radio (20 slots)"
# (heading, width, anchor) for each column of the channel table.
CHANNEL_COLUMNS = (("#", 40, "center"), ("label", 90, "w"),
                   ("frequency", 130, "e"), ("mode", 84, "center"),
                   ("notes", 210, "w"))
CHANNEL_LABEL_COLUMN = 1
CHANNEL_FREQ_COLUMN = 2
CHANNEL_MODE_COLUMN = 3
CHANNEL_NOTES_COLUMN = 4
# What a channel's mode may be set to. DFT is "the band's usual sideband".
CHANNEL_MODE_CHOICES = ["LSB", "USB", "CWL", "CWU", "DFT"]


def parse_frequency(text):
    """
    A frequency as typed, in hertz -- or None if it is not one.

    Accepts the forms people actually type:

        14074000       hertz
        14.074.000     grouped, the way the list shows it ("." or ",")
        14.074         megahertz, with a decimal

    Two groups means a decimal in megahertz; three or more means grouped
    hertz. Anything outside 100 kHz to 60 MHz is refused -- above that the
    rig cannot tune, and below it a mistyped kilohertz figure ("7074") would
    otherwise be stored as 7 kHz.
    """
    text = str(text).strip().replace(" ", "")
    if not text:
        return None
    parts = text.replace(",", ".").split(".")
    if not all(part.isdigit() for part in parts):
        return None
    if len(parts) == 1:
        hz = int(parts[0])
    elif len(parts) == 2:
        hz = int(parts[0]) * 1_000_000 + int(parts[1].ljust(6, "0")[:6])
    else:
        hz = int("".join(parts))
    return hz if 100_000 <= hz <= 60_000_000 else None

FILTER_DEFAULTS = {"LSB": 2600, "USB": 2600, "CWL": 500, "CWU": 500}

# Split offsets, in kHz, as a DX station calls them.
#
# "Up 5" means transmit five kilohertz above where he is transmitting -- so
# each of these is computed from the RX frequency every time, NOT applied to
# wherever TX happens to be. Pressing up 5 twice has to leave you five up,
# not ten: the operator is naming a place, not a movement.
SPLIT_OFFSETS = (("up 1", 1), ("up 2", 2), ("up 5", 5),
                 ("up 10", 10), ("dn 1", -1), ("dn 2", -2))

# Sizing. The frequency is the thing you read, so it takes what the window
# can spare; the dials are what you reach for, so they follow.
#
# The panel's height comes from whichever is taller -- the readout stack or
# the dial canvas -- so pushing one much past the other only adds empty
# space. They are kept roughly in step for that reason.
FREQ_FONT_SIZE = 56
KNOB_DIAMETER = 118

# Latching is NOT used on these dials.
#
# It exists so an accidental scroll cannot move a frequency, which is a real
# hazard -- but the protection each dial needs here is simpler and can be
# stated outright:
#
#   RX  is always live, because it is the control you are using, unless Lock
#       is on, which freezes everything.
#   TX  is live only in split. Out of split the two frequencies are the same
#       one, so a second tunable dial would be a way to move the RX frequency
#       while looking at the wrong panel.
#
# A disabled dial says that better than an armed one: it is visibly inert,
# and there is nothing to remember about how to wake it.
LATCHING_DIALS = False

# Where the window position is remembered.
#
# The panel is meant to sit against SDR++, and getting the two lined up is
# fiddly enough that nobody wants to do it twice. Reading SDR++'s own window
# geometry would be the obvious alternative, but Tk cannot see another
# application's windows -- and the answer would be stale the moment either
# one moved.
GEOMETRY_FILE = os.path.expanduser("~/.ubitx_cec_desktop_geometry.json")


# ---------------------------------------------------------------------------
# A frequency readout whose digits can be clicked
# ---------------------------------------------------------------------------
class RolePanel(sCTkFrame):
    """
    A frequency readout for a ROLE -- receive or transmit -- not for a VFO.

    RECEIVE IS ALWAYS ON THE LEFT. Making the panels stand for roles rather
    than for VFO A and VFO B means nothing swaps sides when split turns on:
    the number you are listening to stays where your eye already is, and only
    the VFO label under it changes. Panels that trade places on a state change
    are exactly what makes a display hard to read quickly.

    Which VFO currently fills each role is shown in the header, because it
    still matters -- but it is a label, not a layout.
    """

    def __init__(self, master, role, app, **kw):
        super().__init__(master, border_width=1, corner_radius=6, **kw)
        self._role = role
        self._app = app

        # Where the dial has asked to be, and when. See _on_turn.
        self._target = None
        self._target_at = 0.0
        # Remembered so state() is called only when it CHANGES.
        #
        # sCTkDial.state() repaints, and update_view() runs on every refresh
        # -- so setting it unconditionally meant turning the dial triggered a
        # refresh, which restated the dial, which repainted it, which the
        # scroll handler saw as more work. It presented as the dial locking
        # up under the wheel.
        self._dial_state = None

        header = sCTkFrame(self, fg_color="transparent", border_width=0)
        header.pack(fill="x", padx=8, pady=(5, 0))

        self.role_label = sCTkLabelSecondary(
            header, text=role, font=("Arial", 12, "bold"))
        self.role_label.pack(side="left")

        self.vfo_label = sCTkLabelTertiary(header, text="vfo a",
                                           font=("Arial", 11))
        self.vfo_label.pack(side="left", padx=(8, 0))

        if role == "tx":
            # A transmit indicator, not a control. It belongs on the TX
            # frequency because that is the thing it is telling you about:
            # this number is going out right now.
            self.led = sCTkLabelPrimary(header, text=" ON AIR ",
                                        font=("Arial", 11, "bold"),
                                        corner_radius=4)
            self.led.pack(side="right")
        else:
            # VFO B sits with the receive panel because that is what it is:
            # the frequency you would be listening to if you swapped. In
            # split it is the transmit frequency and appears on the right
            # instead, so this hides.
            # sCTkLabelSecondary, not Tertiary: this is a frequency you read,
            # not a caption explaining one. Tertiary is for the annotations
            # under the readouts -- the step size, the CW tone -- which you
            # check occasionally. VFO B you want legible at a glance.
            self.standby = sCTkLabelSecondary(header, text="",
                                              font=("Arial", 14))
            self.standby.pack(side="right")
            self._standby_shown = True

        body = sCTkFrame(self, fg_color="transparent", border_width=0)
        body.pack(fill="x", padx=8, pady=(0, 5))

        # PACKED BEFORE the readout, which expands.
        #
        # Tk gives space to packed children in order, and `left` has
        # expand=True -- so a wide readout took what it wanted and the dial
        # got whatever was left, which at a large font size was not much. The
        # dial has a fixed size it should always get; the readout is the one
        # that should give way.
        left = sCTkFrame(body, fg_color="transparent", border_width=0)

        # fg_color transparent so the knob sits on the panel's own colour.
        # The dial's theme block carries its own background, which reads as a
        # darker rectangle behind the knob when it differs from the frame.
        # width and height are the CANVAS; knob_diameter is the knob drawn on
        # it. Left at their defaults the canvas is 120x120 whatever the knob
        # does, so a bigger knob just fills more of the same box -- and a
        # smaller one leaves a wide margin. Both are set together, with just
        # enough margin for the tick marks the dial draws outside the knob.
        self.dial = sCTkDialContinuous(
            body, divisions=24, knob_diameter=KNOB_DIAMETER,
            width=KNOB_DIAMETER + 10, height=KNOB_DIAMETER + 10,
            fg_color="transparent",
            command=self._on_turn,
            left_click_callback=lambda: self._click_step(-1),
            right_click_callback=lambda: self._click_step(+1),
            double_click_command=lambda d: d.set_pressed(True),
            shift_double_click_command=lambda d: d.set_pressed(False))

        # The LIBRARY widget now, not a local class.
        #
        # This started as ten sCTkLabelPrimary widgets with the selected
        # one's background coloured, which jittered as the digits changed and
        # had resorted to hardcoded hex for its highlight. It is a real
        # widget -- themed, documented, and in the Designer palette.
        self.display = sCTkFrequencyDisplay(
            left, digits=10, value=0, font_size=FREQ_FONT_SIZE,
            min_digit=1, command=self._on_digit)
        self.display.pack(anchor="w")

        self.note = sCTkLabelTertiary(left, text="", font=("Arial", 10))
        self.note.pack(anchor="w")

        self.dial.pack(side="right", padx=(4, 0), pady=0)

        # Now the readout, with whatever room the dial did not take.
        left.pack(side="left", fill="x", expand=True)

    def _on_digit(self, step):
        self._app.refresh()

    def _click_step(self, direction):
        self._on_turn(direction)

    def show_pending(self, displayed_hz):
        """
        Draws a frequency that has been asked for but not yet confirmed.

        THE BOUNDED EXCEPTION to "the view never assumes", and the one place
        it lives. A write to the transmit VFO in split is a borrow -- toggle,
        write, toggle, each paced and the toggles confirmed -- with
        notifications held throughout. Waiting for it meant the readout sat
        still for several hundred milliseconds after the dial or button had
        been used.

        Safe because it self-corrects: update_view replaces the pending value
        with the confirmed one as soon as it arrives, and drops it after
        TURN_ACCUMULATE_SECONDS regardless, so a write the rig refused or
        clamped shows reality again rather than a number nobody agreed to.

        Drawn DIRECTLY rather than by asking for a redraw: during a borrow
        the notifications are suspended, so a redraw would not happen.
        """
        self._target = int(displayed_hz)
        self._target_at = time.monotonic()
        self.display.set(self._target)

    def _on_turn(self, clicks):
        """
        One detent of the dial.

        ACCUMULATES FROM WHAT WAS LAST ASKED FOR, not from what the rig has
        confirmed. A wheel spin produces detents far faster than the rig can
        answer, and computing each one from the confirmed frequency means ten
        clicks all read the same number, all send the same target, and the
        dial moves one step for a whole turn of the wheel.

        The running target is abandoned after a pause, so a turn that starts
        fresh always begins from reality -- which also recovers if the rig
        clamped the last request at a band edge or refused it.
        """
        radio = self._app
        if radio.model.locked:
            return

        step = self.display.step()
        now = time.monotonic()

        confirmed = radio.model.role_frequency(self._role)
        if (self._target is None
                or now - self._target_at > TURN_ACCUMULATE_SECONDS):
            base = confirmed
        else:
            base = self._target

        # Drawn now, not at the next refresh -- see show_pending.
        self.show_pending(base + clicks * step)

        # role_frequency, NOT frequency: frequency() takes a VFO NAME, and a
        # role passed to it returns VFO B whatever the dial computed.
        radio.connection.set_role_frequency(self._role, self._target)

    def update_view(self, radio):
        is_tx = self._role == "tx"

        if is_tx:
            on_air = radio.transmitting
            self.led.configure(
                text=" ON AIR " if on_air else "  off air  ",
                fg_color=("#C0392B", "#C0392B") if on_air else "transparent",
                text_color=("#FFFFFF", "#FFFFFF") if on_air
                else ("#94A3B8", "#64748B"))
        else:
            other = "b" if radio.rx_vfo == "a" else "a"
            # HIDDEN IN SPLIT, not blanked.
            #
            # configure(text="") does nothing on an sCTk label: the library
            # drops empty strings, because that is what the Designer sends to
            # mean "fall back to the theme". So the label was never cleared --
            # it kept whatever it last showed before split went on, and read
            # like a VFO B that had stopped updating while the transmit panel
            # showed the real one.
            #
            # Hiding the widget is also simply what is meant: in split, VFO B
            # is on the transmit panel and has no business here.
            if radio.split:
                if self._standby_shown:
                    self.standby.pack_forget()
                    self._standby_shown = False
            else:
                hz = radio.frequency(other)
                self.standby.configure(
                    text=f"vfo {other}   {hz // 1_000_000}."
                         f"{(hz // 1000) % 1000:03d}.{hz % 1000:03d}")
                if not self._standby_shown:
                    self.standby.pack(side="right")
                    self._standby_shown = True

        # Lock freezes both. Otherwise TX is tunable only in split -- out of
        # split it is showing the same frequency as RX, and moving it here
        # would be moving that.
        live = (not radio.locked) and (radio.split if is_tx else True)
        wanted = "normal" if live else "disabled"
        if wanted != self._dial_state:
            self._dial_state = wanted
            self.dial.state(wanted)
        # The widget disables as a whole rather than exposing an enabled
        # flag: greying the digits and refusing selection is what "disabled"
        # means for it.
        self.display.configure(state="normal" if live else "disabled")
        # SHOWS THE TARGET WHILE A COMMAND IS IN FLIGHT.
        #
        # A bounded exception to "the view never assumes". Receive is one
        # command and one confirmation, so its readout tracks the dial. A
        # transmit write in split is toggle, write, toggle -- three commands,
        # three confirmations, each behind the throttle, with notifications
        # held for the whole borrow. Waiting for that meant the number sat
        # still for several hundred milliseconds after the wheel had stopped,
        # and the two panels felt like different instruments.
        #
        # Showing the target is safe BECAUSE IT SELF-CORRECTS: the confirmed
        # value replaces it as soon as it arrives, so a rig that clamps at a
        # band edge or refuses the write is visible a moment later rather
        # than never. It is also bounded -- the target expires with the same
        # timeout that governs the accumulator, so a lost confirmation shows
        # reality again rather than a number nobody agreed to.
        confirmed = radio.role_frequency(self._role)
        if self._target is not None:
            if (confirmed == self._target
                    or time.monotonic() - self._target_at
                    > TURN_ACCUMULATE_SECONDS):
                self._target = None

        self.display.set(
            confirmed if self._target is None else self._target)
        self.vfo_label.configure(text=f"vfo {radio.role_vfo(self._role)}")

        self.configure(border_color=("#993C1D", "#993C1D") if is_tx
                       else ("#CBD5E1", "#374151"))

        if is_tx and not radio.split and radio.rit and radio.rit_base_hz:
            # RIT HOLDS TRANSMIT. This branch has to come first: the
            # "follows rx" note below is exactly wrong under RIT, where
            # transmit is precisely the thing that does NOT follow receive.
            # Receiver Incremental Tuning moves only the receiver -- the ARRL
            # definition -- so saying otherwise on screen describes the
            # opposite of what the radio is doing.
            held = radio.formatted(radio.rit_base_hz)
            if radio.mode_of(radio.tx_vfo).startswith("CW"):
                self.note.configure(
                    text=f"held by rit at {held}  ·  "
                         f"{radio.cw_offset_note(radio.mode_of(radio.tx_vfo))}")
            else:
                self.note.configure(text=f"held by rit at {held}")
        elif is_tx and not radio.split:
            if radio.mode_of(radio.tx_vfo).startswith("CW"):
                # Says BOTH things. This branch used to win outright, so out
                # of split a CW transmit frequency was quietly offset with
                # nothing on screen explaining the difference from receive.
                self.note.configure(
                    text=f"follows rx  ·  "
                         f"{radio.cw_offset_note(radio.mode_of(radio.tx_vfo))}")
            else:
                self.note.configure(text="follows rx — turn Split on to set it")
        elif radio.locked:
            self.note.configure(text="locked")
        elif is_tx and radio.mode_of(radio.tx_vfo).startswith("CW"):
            # radio.cw_tone, not a module constant: the rig reports the tone
            # and it is settable, so a fixed number here describes whatever
            # the default happened to be rather than what is applied.
            # The sign comes from the model: +tone in CWL, -tone in CWU. The
            # minus written here before was only ever right for CWU.
            self.note.configure(
                text=radio.cw_offset_note(radio.mode_of(radio.tx_vfo)))
        elif not is_tx and radio.rit:
            # From the MODEL, not composed here. This used to take the VFO as
            # the "base" -- which under the rig's RIT is the frequency being
            # tuned, not the one being kept. The model knows which is which,
            # and one place deciding the wording means the two panels and any
            # other window cannot disagree about it.
            self.note.configure(text=radio.role_note("rx"))
        else:
            self.note.configure(text=f"step {self._readable_step()}")

    def _readable_step(self):
        hz = self.display.step()
        return f"{hz // 1000} kHz" if hz >= 1000 else f"{hz} Hz"


# ---------------------------------------------------------------------------
# The application
# ---------------------------------------------------------------------------
class UbitxCecDesktop(sCTk):

    def __init__(self):
        super().__init__()
        self.title("uBITX CEC Desktop")
        self.geometry(self._remembered_geometry())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Also saved as it changes -- see _on_configure. Closing cleanly is
        # not something an IDE's stop button does.
        self._geometry_timer = None
        self.bind("<Configure>", self._on_configure)

        # CONFIGURATION FIRST. It reads ~/.ubitx_cec_desktop.ini -- the same
        # file the previous version used, so every setting carries over -- and
        # the SDR controller reads it in its own constructor, for the server
        # address and the filter defaults. It is a module-level global because
        # that is how globalvars has always published it, and the controller
        # expects it there.
        gv.config = ConfigurationManager(self)

        # The channel sets, owned here -- see channel_sets.py. The Channels
        # tab edits them and the scanner will read them; nothing else keeps a
        # copy.
        self.channel_sets = ChannelSets(gv.config)

        # on_change is _model_changed rather than refresh: the view redraws,
        # and SDR++ is brought into step, from the same notification. schedule
        # is `after`, so a burst of reports becomes one of each. See
        # RadioModel.changed().
        self.model = RadioModel(on_change=self._model_changed,
                                schedule=self.after)
        # #
        # #   open port to the ubitx
        # #
        port = "/dev/cu.usbserial-A5069RR4"
        BAUD = 57600
        RS232 = serial.Serial(port, BAUD, timeout=5, stopbits=1, parity=serial.PARITY_NONE, xonxoff=0, rtscts=0, write_timeout=1)

        self.connection = uBITX_Link(self, RS232, self.model, 250)

        # SDR++, as a second transport beside the rig. Built now so the model's
        # notifications can reach it, but not CONNECTED until the interface
        # exists to report whether that worked -- see _start_sdr.
        self.sdr = SDR_Link(self, self.model, self.connection)
        self.sdr.on_status = self._show_sdr_status

        # The scanner, run by the application rather than the SDR -- see
        # scanner.py. It tunes the rig; the SDR follows the rig as ever.
        self.scanner = Scanner(self, self.model, self.connection)
        self.scanner.on_step = self._scan_reached
        self.scanner.on_stop = self._scan_stopped

        #   initialize radio connection
        #
        # NOTHING IS SEEDED. The model starts at zero and the rig's own
        # report fills it in a moment later.
        #
        # Seeding plausible frequencies here was worse than showing nothing:
        # the readout came up with a number that looked real, and then
        # visibly jumped when read_all_values said the rig was somewhere
        # else entirely. Which reads as the frequency moving on its own --
        # indistinguishable, to anyone watching, from the transmit write
        # bug it took a while to find.
        #
        # Zero reads as 0.000, which is obviously not a frequency and
        # therefore obviously "not yet known".

        # Every control goes through here. Nothing in the view writes state:
        # a command is sent, and the confirmation updates the display -- the
        # shape the real rig imposes, kept so the controls are wired
        # correctly for it.
        self.rig = StubRadio(self.model, self.after)
        self._toggles = {}

        # refresh() touches widgets from every tab, and sCTkSpinbox.set()
        # invokes its command -- so setting an initial value while building
        # calls back into a interface that does not exist yet. The flag keeps
        # that harmless rather than relying on construction order.
        self._ready = False

        # WHICH RECEIVER YOU ARE LISTENING THROUGH -- "SDR" or "Rig". An
        # application choice, not something the rig reports, so it lives
        # here rather than in the model. It decides what Mute silences and
        # whether volume does anything. Starts on SDR if SDR++ is switched
        # on in the settings, since that is how the station is set up.
        self._listen_source = ("SDR" if str(gv.config.get_SDR_Switch()) == "True"
                               else "Rig")
        # The computer's audio, muted from this application. Not rig state
        # either, and the rig's own speaker is tracked in the model.
        self._sdr_muted = False
        # state() repaints, so it is called only when the value changes.
        self._offset_state = None

        self.notebook = sCTkNotebook(self, side="left", tab_width=30,
                                     command=self._on_tab,
                                     tab_style="rounded",
                                     text_orientation="auto",
                                     show_page_border=True)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

        self._build_operate(self.notebook.add("Operate"))
        self._build_rx(self.notebook.add("RX"))
        self._build_channels(self.notebook.add("Channels"))
        self._build_cw(self.notebook.add("CW"))
        self._build_setup(self.notebook.add("Setup"))

        # Initial values go in AFTER every tab exists, for the reason above.
        self._ready = True
        self.band_picker.set(self.model.band_name())
        # self.band_picker.set(BANDS[self.model.band_index][0])
        self.mode_picker.set(self.model.mode)

        self.refresh()
        self._tick()

        # Idle rather than immediate: the window should be up before a
        # connection attempt that can take a moment when SDR++ is not there.
        self.after_idle(self._start_sdr)

    # -- window position ---------------------------------------------------
    def _remembered_geometry(self):
        """Where it was last time, or a sensible default."""
        try:
            with open(GEOMETRY_FILE) as handle:
                return json.load(handle)["geometry"]
        except Exception:
            # Sized for a 13" MacBook Air, which is 1470 points wide.
            #
            # Two ten-digit readouts at 56pt plus their dials do not fit in
            # much less, and the first symptom of trying is a dial squeezed
            # to nothing rather than anything that says "too narrow". Wider
            # than the screen would be worse, so this is the screen.
            return "1440x520"

    def _on_close(self):
        self._save_geometry()
        self.after_cancel(self.connection.reader_process_id)
        self.sdr.disconnect()
        self.destroy()

    # -- SDR++ ---------------------------------------------------------------
    def _model_changed(self):
        """
        The model changed: redraw, and bring SDR++ into step.

        One notification, two consumers. SDR++ follows the MODEL rather than
        being told separately by each handler, so every way the receive
        frequency can change -- the dial, a band change, a split offset, a
        click in SDR++ itself coming back from the rig -- reaches it the same
        way, and none can be forgotten.
        """
        self.refresh()
        # getattr, because the rig link is built first and its startup dump
        # schedules notifications of its own -- one could run before the SDR
        # link exists.
        sdr = getattr(self, "sdr", None)
        if sdr is not None:
            sdr.follow()
        # The scanner watches too: transmitting, or the frequency changing
        # under it, stops the scan. getattr for the same reason as the SDR.
        scanner = getattr(self, "scanner", None)
        if scanner is not None:
            scanner.watch()

    def _start_sdr(self):
        """Connects to SDR++ at startup, if it is switched on in the settings."""
        # The slider starts where the level really is. Read here rather than
        # while building, because on macOS it runs osascript, and the window
        # should be up first.
        self.volume_slider.set(self.sdr.get_volume())

        # Put the rig where the listening choice needs it: quiet if SDR++ is
        # the receiver, speaking if the rig is. Done now rather than while
        # building, because it sends a command to the rig.
        self._set_listen_source(self._listen_source)
        if str(gv.config.get_SDR_Switch()) == "True":
            self.sdr.connect()
        else:
            self._show_sdr_status(False)

    def _reconnect_sdr(self):
        """The status-strip button: try SDR++ again."""
        self.sdr_status.configure(text="sdr — connecting…")
        self.update_idletasks()
        self.sdr.connect()

    def _show_sdr_status(self, connected):
        """Says whether SDR++ is connected, on the status strip."""
        self.sdr_status.configure(
            text="sdr ok" if connected else "sdr — reconnect")

    def _on_configure(self, event):
        """
        Remembers the size and position as they change.

        SAVED ON RESIZE, NOT ONLY ON EXIT. Saving in _on_close alone depends
        on the window being closed properly -- and stopping the process from
        an IDE kills it outright, so WM_DELETE_WINDOW never fires and nothing
        is ever written. The geometry silently never persisted at all.

        Debounced, because <Configure> fires for every pixel of a drag and
        writing a file that often would be absurd. Half a second after the
        window stops moving, one write.
        """
        if event.widget is not self:
            return          # a child resizing, not the window
        if self._geometry_timer is not None:
            try:
                self.after_cancel(self._geometry_timer)
            except Exception:
                pass
        self._geometry_timer = self.after(500, self._save_geometry)

    def _save_geometry(self):
        self._geometry_timer = None
        try:
            with open(GEOMETRY_FILE, "w") as handle:
                json.dump({"geometry": self.winfo_geometry()}, handle)
        except Exception:
            # Losing the position is a small cost; refusing to close is not.
            pass

    def _toggle_on_top(self):
        """
        Keeps the panel above SDR++.

        A short window sitting over a large one disappears behind it the
        moment you click the waterfall -- which is most of what you do. On
        top is almost certainly what you want here, but it is a preference
        rather than a given, so it is a switch.
        """
        wanted = not bool(self.attributes("-topmost"))
        self.attributes("-topmost", wanted)
        self.on_top_button.configure(
            text="on top" if wanted else "not on top",
            fg_color=("#1A4375", "#2471A3") if wanted else "transparent")

    # -- convenience ------------------------------------------------------
    # NAMED radio, NOT state.
    #
    # sCTk is a Tk window, and Misc.state() is Tk's own window-state method --
    # CustomTkinter's DPI tracker calls it on every open window:
    #
    #     TypeError: 'RadioState' object is not callable
    #
    # Anything subclassing a Tk widget inherits a large namespace; state,
    # place, lower and _draw are all already taken.

    def set_active(self, which):
        """
        Asks the rig to change VFO. Does not change it here.

        The rig owns which VFO is active -- it reports one with `cv` -- so
        setting it locally would be the interface deciding something the
        radio has not agreed to.
        """
        if which != self.model.active:
            self.connection.toggle_vfo()

    # -- Operate ----------------------------------------------------------
    def _build_operate(self, page):
        page.grid_columnconfigure(0, weight=1)
        # Row 5 is empty and takes every spare pixel, which holds the real
        # content at the TOP. Without it the rows share the extra height and
        # the whole panel drifts to the middle as the window grows.
        page.grid_rowconfigure(5, weight=1)

        # The two VFOs -----------------------------------------------------
        vfos = sCTkFrame(page, fg_color="transparent", border_width=0)
        vfos.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))
        vfos.grid_columnconfigure((0, 1), weight=1, uniform="vfo")

        self.panel_rx = RolePanel(vfos, "rx", self)
        self.panel_rx.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.panel_tx = RolePanel(vfos, "tx", self)
        self.panel_tx.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # The split meter --------------------------------------------------
        meters = sCTkFrame(page, fg_color="transparent", border_width=0)
        meters.grid(row=1, column=0, sticky="ew", padx=6, pady=2)
        meters.grid_columnconfigure((0, 1), weight=1, uniform="meter")

        # One instrument in two halves: signal under the receiving frequency,
        # power under the transmitting one. Neither half is ever dead.
        self.s_meter = sCTkSMeterBar(meters, hide_lower_row=True,
                                     width=460, height=46)
        self.s_meter.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.p_meter = sCTkSMeterBar(meters, hide_sig_row=True,
                                     width=460, height=46)
        self.p_meter.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # Actions ----------------------------------------------------------
        actions = sCTkFrame(page, fg_color="transparent", border_width=0)
        actions.grid(row=3, column=0, sticky="ew", padx=6, pady=(8, 2))

        sCTkButtonPrimary(actions, text="Log QSO", width=96,
                          command=self._log_qso).pack(side="left", padx=(0, 4))

        for key, label in (("split", "Split"), ("rit", "RIT")):
            btn = sCTkButtonSecondary(actions, text=label, width=64,
                                      command=lambda k=key: self._toggle(k))
            btn.pack(side="left", padx=2)
            self._toggles[key] = btn

        sCTkButtonSecondary(actions, text="A ⇄ B", width=64,
                            command=self._swap).pack(side="left", padx=2)

        sCTkButtonSecondary(actions, text="A→B", width=64,
                            command=self._copy_AtoB).pack(side="left", padx=2)

        # Lock, then TX off, then Mute and its volume -- the two "stop"
        # controls together, and the two audio controls together.
        self._toggles["locked"] = sCTkButtonSecondary(
            actions, text="Lock", width=64,
            command=lambda: self._toggle("locked"))
        self._toggles["locked"].pack(side="left", padx=2)

        # Transmit inhibit lives on Operate, not behind a tab. It is the
        # control you want when something is wrong -- a bad SWR, the wrong
        # antenna, a neighbour on frequency -- and hunting for it is exactly
        # what you cannot afford then.
        self._toggles["tx_inhibit"] = sCTkButtonSecondary(
            actions, text="TX off", width=68,
            command=lambda: self._toggle("tx_inhibit"))
        self._toggles["tx_inhibit"].pack(side="left", padx=2)

        # Wider than Lock: its label says which receiver it mutes.
        self._toggles["muted"] = sCTkButtonSecondary(
            actions, text="Mute", width=78,
            command=lambda: self._toggle("muted"))
        self._toggles["muted"].pack(side="left", padx=2)

        # Volume on Operate, beside the Mute it goes with -- it is something
        # you reach for while operating, not a setting. Asked of the SDR
        # rather than done here: see SDR_Link.set_volume. Active only when
        # listening through SDR++; the rig has no volume command, its level
        # is the knob on the front panel.
        #
        # 143 wide, up from 110: at 110 the knob took a large share of the
        # track, leaving little travel to set a level with.
        self.volume_slider = sCTkSlider(
            actions, from_=0, to=100, width=143,
            command=lambda value: self.sdr.set_volume(value))
        self.volume_slider.pack(side="left", padx=(4, 2))

        # Role controls ----------------------------------------------------
        #
        # Three columns. The outer two sit under the frequency they belong to
        # -- the filter is a RECEIVE property, the offsets are TRANSMIT ones
        # -- and band and mode go between them, because they act on both and
        # would be claiming otherwise under either panel.
        #
        # The middle column takes no spare width, so the two role groups stay
        # pinned under their own panels as the window grows.
        role_row = sCTkFrame(page, fg_color="transparent", border_width=0)
        role_row.grid(row=2, column=0, sticky="ew", padx=6, pady=(4, 0))
        role_row.grid_columnconfigure(0, weight=1)
        role_row.grid_columnconfigure(1, weight=0)
        role_row.grid_columnconfigure(2, weight=1)

        # Split offsets ----------------------------------------------------
        #
        # DIMMED out of split, not hidden.
        #
        # They mean nothing out of split -- TX and RX are the same frequency,
        # so an offset from RX is just retuning -- but hiding them moves
        # everything around them each time split toggles, and a row that
        # appears and disappears is harder to learn than one that greys. Same
        # treatment AGC and NR get on the other side.
        #
        # They exist because a pileup is the one time the dial is too slow.
        # The DX says "up 5" and fifty clicks later someone else has him.
        # A column, not a row: the buttons on the first line and the note
        # UNDER them.
        #
        # Beside them, the note changed width whenever the offset changed --
        # "transmitting 10 kHz above rx" is wider than "5 kHz" -- and pushed
        # the whole set of buttons sideways. A control that moves because its
        # own label grew is worse than no label.
        offset_column = sCTkFrame(role_row, fg_color="transparent",
                                  border_width=0)
        offset_column.grid(row=0, column=2, sticky="e")

        self.offset_row = sCTkFrame(offset_column, fg_color="transparent",
                                    border_width=0)
        self.offset_row.pack(anchor="e")
        self._offset_buttons = []

        sCTkLabelTertiary(self.offset_row, text="tx offset",
                          font=("Arial", 11)).pack(side="left", padx=(0, 6))

        simplex = sCTkButtonSecondary(self.offset_row, text="simplex", width=74,
                                      command=lambda: self._split_offset(0))
        simplex.pack(side="left", padx=2)
        self._offset_buttons.append(simplex)

        for label, khz in SPLIT_OFFSETS:
            btn = sCTkButtonSecondary(
                self.offset_row, text=label, width=58,
                command=lambda k=khz: self._split_offset(k))
            btn.pack(side="left", padx=2)
            self._offset_buttons.append(btn)

        self.offset_note = sCTkLabelTertiary(offset_column, text="",
                                             font=("Arial", 10))
        self.offset_note.pack(anchor="e", pady=(2, 0))

        # Band and mode, between the two -----------------------------------
        centre = sCTkFrame(role_row, fg_color="transparent", border_width=0)
        centre.grid(row=0, column=1, padx=16)

        # Band is a short ordered list you step through, which is what a
        # spinbox is. It also shows where you are without being read.
        self.band_picker = sCTkSpinbox(
            centre, values=[b[0] for b in self.model.BANDS], wrap=False, width=110,
            command=self._on_band)
        self.band_picker.pack(side="left", padx=(0, 8))

        # Mode is DIRECT selection, not a rotary: you jump between modes
        # rather than sweeping through them.
        self.mode_picker = sCTkSegmentedButton(
            centre, values=MODES, command=self._on_mode)
        self.mode_picker.pack(side="left")

        # Receive controls, under the receive frequency --------------------
        rx_row = sCTkFrame(role_row, fg_color="transparent", border_width=0)
        rx_row.grid(row=0, column=0, sticky="w")

        sCTkLabelTertiary(rx_row, text="filter",
                          font=("Arial", 11)).pack(side="left", padx=(0, 6))
        sCTkButtonSecondary(rx_row, text="wide", width=60,
                            command=lambda: self._filter(+300)).pack(side="left", padx=2)
        sCTkButtonSecondary(rx_row, text="narrow", width=60,
                            command=lambda: self._filter(-300)).pack(side="left", padx=2)
        sCTkButtonSecondary(rx_row, text="reset", width=56,
                            command=self._filter_reset).pack(side="left", padx=2)
        self.filter_label = sCTkLabelPrimary(rx_row, text="2400 Hz",
                                             font=("Arial", 11))
        self.filter_label.pack(side="left", padx=8)

        for label in ("AGC", "NR", "Notch"):
            btn = sCTkButtonSecondary(rx_row, text=label, width=56)
            btn.pack(side="left", padx=2)
            btn.state("disabled")

        self._build_status_strip(page)

    def _build_status_strip(self, page):
        """
        The bottom line: what the radio is doing, and whether it is reachable.

        Moved here from the top because none of it is something you act on
        mid-QSO -- it is state you glance at. The frequencies deserve the
        position your eye lands on first.

        The callsign and firmware version are gone entirely: they never
        change, so they belong in About rather than occupying the same line
        as live state.
        """
        strip = sCTkFrame(page, fg_color="transparent", border_width=0)
        strip.grid(row=6, column=0, sticky="ew", padx=6, pady=(0, 6))

        self.tx_chip = sCTkLabelPrimary(strip, text=" RX ", font=("Arial", 11),
                                        fg_color=("#0F6E56", "#0F6E56"),
                                        corner_radius=4)
        self.tx_chip.pack(side="left")

        self.mode_label = sCTkLabelTertiary(strip, text="USB",
                                            font=("Arial", 11))
        self.mode_label.pack(side="left", padx=8)

        self.sdr_status = sCTkButtonTertiary(
            strip, text="sdr — reconnect", width=130, height=22,
            command=self._reconnect_sdr)
        self.sdr_status.pack(side="right")

        # NOT part of the design. The real radio transmits from the key or the
        # PTT, so there is no transmit button to place -- this is here only so
        # this can show what the panel looks like on air, and it sits
        # apart from the controls that are real.
        sCTkButtonTertiary(strip, text="simulate transmit", width=130,
                           height=22, command=self._toggle_tx
                           ).pack(side="right", padx=8)
        sCTkLabelTertiary(strip, text="rig ok",
                          font=("Arial", 11)).pack(side="right", padx=8)

        self.on_top_button = sCTkButtonTertiary(
            strip, text="not on top", width=96, height=22,
            command=self._toggle_on_top)
        self.on_top_button.pack(side="right", padx=8)

    # -- the other tabs, sketched -----------------------------------------
    def _build_rx(self, page):
        wrap = sCTkFrame(page, fg_color="transparent", border_width=0)
        wrap.pack(fill="both", expand=True, padx=14, pady=12)

        sCTkLabelPrimary(wrap, text="Receive",
                         font=("Arial", 15, "bold")).pack(anchor="w")
        sCTkLabelTertiary(
            wrap,
            text="Everything about how you are listening. The choice below "
                 "decides where the audio and the signal reading come from, "
                 "and which of the controls under it can do anything: ATT and "
                 "IFS belong to the rig's own front end, so they are inert "
                 "while you are listening through the SDR.",
            font=("Arial", 11), wraplength=640, justify="left").pack(anchor="w", pady=(2, 12))

        row = sCTkFrame(wrap, fg_color="transparent", border_width=0)
        row.pack(anchor="w", pady=(8, 0))
        # THE MOST CONSEQUENTIAL CHOICE ON THIS TAB, so it looks like one.
        #
        # A segmented button rather than a switch: it shows BOTH receivers
        # and which one is chosen, which is exactly the question. A switch
        # means on or off, and with a receiver named on each side you are
        # left working out which way the knob points.
        #
        # It was a small control under a lowercase "receiver", level with
        # the switches below it, and read as one more option among them
        # rather than the thing that decides what those options do.
        sCTkLabelSecondary(row, text="Listen through",
                           font=("Arial", 15, "bold")).pack(side="left", padx=(0, 14))
        # dynamic_resizing=False, or `width` is IGNORED: by default each
        # segment shrinks to its own text, which is what made the first
        # enlargement look no different. Off, the width is shared equally,
        # so each segment is 140 wide around a three-letter word and reads
        # as a button rather than a label with a border.
        self.receiver_picker = sCTkSegmentedButton(
            row, values=["SDR", "Rig"], command=self._set_listen_source,
            width=280, height=40, font=("Arial", 15, "bold"),
            dynamic_resizing=False)
        self.receiver_picker.pack(side="left")
        self.receiver_picker.set(self._listen_source)

        sCTkLabelTertiary(
            wrap,
            text="Decides where the audio and the signal meter come from.",
            font=("Arial", 11)).pack(anchor="w", pady=(4, 14))

        # Volume moved to Operate, beside Mute. What is said here is how the
        # choice above changes the audio.
        sCTkLabelTertiary(
            wrap,
            text="Listening through SDR++ quiets the rig's speaker, and the "
                 "volume on Operate is then the computer's output volume -- "
                 "SDR++ cannot set its own level, so every application follows "
                 "it. Listening through the rig, the level is its front-panel "
                 "knob.",
            font=("Arial", 10), wraplength=640,
            justify="left").pack(anchor="w", pady=(4, 8))

        for label, note in (("ATT", "rig front end only"),
                            ("IFS", "rig front end only"),
                            ("Squelch", "awaiting backend"),
                            ("AGC", "awaiting backend")):
            line = sCTkFrame(wrap, fg_color="transparent", border_width=0)
            line.pack(anchor="w", pady=3)
            sw = sCTkSwitch(line, text=label)
            sw.pack(side="left")
            sCTkLabelTertiary(line, text=note,
                              font=("Arial", 10)).pack(side="left", padx=10)

    def _build_channels(self, page):
        """
        One list, one set selector, and every action working on what is in
        front of you.

        The rig's twenty memory slots and SDR++'s channel sets are shown as
        sets of one kind. A channel is a channel wherever it is kept, and
        tuning to one works the same way: the rig is told, and SDR++ follows.

        FIRST PASS: reading and tuning. The rig's memories are read the first
        time this tab is opened (see _on_tab), and fill in as the replies
        arrive. Editing, writing back to the rig, copying between sets and
        scanning come next; their buttons are here but disabled, so the
        layout does not move when they arrive.
        """
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)       # the table's row takes the slack

        # THE TOP ROW: where the radio is, at the left -- the one thing on
        # this tab about the radio rather than the list, so it is where
        # reading starts -- and what the tab is doing, right beside it.
        #
        # The status used to trail off the end of the header, after the
        # set's buttons, like a pan handle. Here it has a place of its own,
        # and the header below is left to the set alone.
        now_row = sCTkFrame(page, fg_color="transparent", border_width=0)
        now_row.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        sCTkLabelTertiary(now_row, text="now",
                          font=("Arial", 11)).pack(side="left", padx=(0, 8))
        # PRIMARY, and styled by the theme alone -- no font of its own. The
        # value is the most important on the tab, and the primary tier is how
        # the library says so; a font set here would make it primary in name
        # only.
        self.channel_now = sCTkLabelPrimary(now_row, text="")
        self.channel_now.pack(side="left")

        # Beside the frequency, not across the window from it. The BAR comes
        # first and the note after it: at the start of the run the bar has a
        # fixed position, so the note's changing length cannot push it about.
        # See _refresh_channels, which packs the bar before the note.
        self.set_note = sCTkLabelTertiary(now_row, text="", font=("Arial", 10))
        self.set_note.pack(side="left", padx=(20, 0))

        # A MOVING BAR while the rig is read or written. The count in the note
        # is easy to miss -- a read-back starting on its own after a write
        # went unnoticed -- and a bar in motion is not. Shown only while busy.
        self.channel_progress = sCTkProgressBar(now_row, width=180, height=10)
        self.channel_progress.set(0)
        self._progress_shown = False

        head = sCTkFrame(page, fg_color="transparent", border_width=0)
        head.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 4))

        sCTkLabelTertiary(head, text="set",
                          font=("Arial", 11)).pack(side="left", padx=(0, 6))
        self.set_picker = sCTkComboBox(
            head, width=200, command=self._on_set_chosen, values=self._set_names())
        self.set_picker.pack(side="left")
        self.set_picker.set(RADIO_SET)

        # THE SET MENU. Its items follow the set on show -- see
        # _update_channel_buttons -- and choosing one runs it and puts the
        # button back to "⋯". An option menu rather than a plain button, so
        # it opens a themed list with nothing more than the library's own
        # widget.
        self.set_menu = sCTkOptionMenuPrimary(
            head, values=["⋯"], width=54, command=self._on_set_menu)
        self.set_menu.set("⋯")
        self.set_menu.pack(side="left", padx=(6, 0))

        # WHOLE-SET ACTIONS sit beside the selector, since they act on the
        # set it chose rather than on a row. For the rig's set: read it,
        # write the draft, or throw the draft away. They are HIDDEN for a
        # set, not disabled -- a set is never read from or written to the
        # rig, and a control that is always greyed out there looked broken
        # rather than irrelevant. Disabled keeps one meaning: "not yet".
        self.radio_actions = sCTkFrame(head, fg_color="transparent", border_width=0)
        self.radio_actions.pack(side="left", padx=(10, 0))
        self.reread_button = sCTkButtonSecondary(
            self.radio_actions, text="Read from radio", width=120,
            command=self.connection.read_channels)
        self.reread_button.pack(side="left", padx=2)
        self.write_button = sCTkButtonPrimary(
            self.radio_actions, text="Write to radio", width=130,
            command=self._write_to_radio)
        self.write_button.pack(side="left", padx=2)
        self.discard_button = sCTkButtonSecondary(
            self.radio_actions, text="Discard", width=76,
            command=self._discard_draft)
        self.discard_button.pack(side="left", padx=2)
        self._set_kind_shown = "radio"
        self._menu_kind_shown = None

        # ASKING FOR A NAME happens here in the header, not in a pop-up:
        # the field opens beside the set selector, Enter confirms and Escape
        # cancels. Built once, shown only while in use.
        self.name_prompt = sCTkFrame(head, fg_color="transparent", border_width=0)
        self.name_prompt_label = sCTkLabelSecondary(self.name_prompt, text="")
        self.name_prompt_label.pack(side="left", padx=(12, 6))
        self.name_entry = sCTkEntryPrimary(self.name_prompt, width=180)
        self.name_entry.pack(side="left")
        self.name_entry.bind("<Return>", lambda e: self._name_prompt_ok())
        self.name_entry.bind("<Escape>", lambda e: self._close_prompts())
        self.name_ok_button = sCTkButtonPrimary(
            self.name_prompt, text="OK", width=64, command=self._name_prompt_ok)
        self.name_ok_button.pack(side="left", padx=(6, 2))
        sCTkButtonSecondary(self.name_prompt, text="Cancel", width=70,
                            command=self._close_prompts).pack(side="left", padx=2)
        self._name_prompt_action = None
        self._name_prompt_unchanged = None

        # COPY TO asks where, in the same way: a destination set, and for
        # the rig's set a slot as well, which appears only then.
        self.copy_prompt = sCTkFrame(head, fg_color="transparent", border_width=0)
        self.copy_prompt_label = sCTkLabelSecondary(self.copy_prompt, text="")
        self.copy_prompt_label.pack(side="left", padx=(12, 6))
        self.copy_target = sCTkOptionMenuPrimary(
            self.copy_prompt, values=[""], width=170,
            command=lambda value: self._update_copy_prompt())
        self.copy_target.pack(side="left")
        self.copy_slot = sCTkOptionMenuPrimary(
            self.copy_prompt, values=[f"slot {n}" for n in range(1, CHANNEL_SLOTS + 1)],
            width=90)
        self.copy_go = sCTkButtonPrimary(self.copy_prompt, text="Copy", width=64,
                                         command=self._copy_prompt_ok)
        self.copy_go.pack(side="left", padx=(6, 2))
        self.copy_cancel = sCTkButtonSecondary(self.copy_prompt, text="Cancel",
                                               width=70, command=self._close_prompts)
        self.copy_cancel.pack(side="left", padx=2)



        # An sCTkTableview, so the label and frequency are EDITED IN PLACE:
        # click a row to select it, click its label or frequency again to
        # edit that cell. The value you want to change is the one you are
        # looking at. Double-click still tunes -- edit_trigger="select" keeps
        # the double-click free for that. It scrolls, since twenty rows do
        # not fit the window.
        # height is a CEILING: the table scrolls past it rather than asking
        # to be tall enough for all twenty rows, which pushed the header row
        # out of the window. The grid stretches it to the space there is.
        self.channel_table = sCTkTableview(
            page, columns=[h for h, _, _ in CHANNEL_COLUMNS], height=240,
            num_rows=0, edit_trigger="select", editable_columns=[],
            column_choices={CHANNEL_MODE_COLUMN: CHANNEL_MODE_CHOICES})
        for index, (_, width, anchor) in enumerate(CHANNEL_COLUMNS):
            self.channel_table.set_column_properties(index, width, anchor)
        # "nsw", not "nsew": as wide as its columns, with the scrollbar
        # beside them. Stretched across the window, the scrollbar sat at the
        # far edge with a wide empty band between it and the notes.
        self.channel_table.grid(row=2, column=0, sticky="nsw", padx=10, pady=2)
        self.channel_table.bind_selection_callback(
            lambda row, values: self._select_channel(row))
        self.channel_table.bind_activate_callback(
            lambda row, values: self._tune_to_channel(row))
        self.channel_table.bind_validation_callback(self._check_channel_edit,
                                                    with_row=True)
        self.channel_table.bind_edit_callback(self._channel_edited)
        # Some cells are read-only whatever their column -- decided per CELL,
        # before an editor opens, since refusing the edit only afterwards let
        # a label be typed and then silently thrown away. See
        # _channel_cell_editable.
        self.channel_table.bind_cell_editable_callback(self._channel_cell_editable)

        # A short message in place of the set note -- why an edit was
        # refused, say -- cleared after a few seconds. See _notify.
        self._channel_notice = None
        self._notice_timer = None

        self._shown_set = None         # the set the table was loaded with
        self._shown_rows = []           # the rows it is showing, as text
        self._shown_editable = None     # the editable columns last set
        self._selected_channel = None   # index into the current set

        actions = sCTkFrame(page, fg_color="transparent", border_width=0)
        actions.grid(row=3, column=0, sticky="ew", padx=10, pady=(6, 10))

        self.tune_button = sCTkButtonPrimary(
            actions, text="Tune to", width=84, command=self._tune_to_selected)
        self.tune_button.pack(side="left", padx=(0, 4))

        # THIS BAR ACTS ON THE SELECTED CHANNEL, whichever set it is in.
        # For the rig's set, changes are held as a DRAFT -- marked in the
        # list, not sent -- until Write to radio above: EEPROM has a limited
        # number of write cycles, and overwriting a stored channel should be
        # a deliberate act. For a set, changes are saved at once.
        self.store_button = sCTkButtonSecondary(
            actions, text="Store VFO here", width=120,
            command=self._store_vfo_here)
        self.store_button.pack(side="left", padx=(12, 2))
        # "Clear" for the rig's fixed slots, "Delete" for a set, whose
        # channels come and go -- the label follows the set on show.
        self.clear_button = sCTkButtonSecondary(
            actions, text="Clear", width=70, command=self._clear_channel)
        self.clear_button.pack(side="left", padx=2)
        # Only a set can grow; the rig has twenty slots, always. Shown only
        # for a set -- see _update_channel_buttons.
        self.add_button = sCTkButtonSecondary(
            actions, text="Add VFO", width=80, command=self._add_vfo)

        # Copies the selected channel to any set -- asks where, in the
        # header. See _open_copy_prompt.
        self.copy_button = sCTkButtonSecondary(actions, text="Copy to…",
                                               width=86, command=self._open_copy_prompt)
        self.copy_button.pack(side="left", padx=(12, 2))

        # SCAN the set on show, from the selected channel, looping. The time
        # on each channel is saved with the sets -- see ChannelSets.
        self.scan_button = sCTkButtonPrimary(actions, text="▶ Scan", width=90,
                                             command=self._toggle_scan)
        self.scan_button.pack(side="left", padx=(24, 4))
        self.dwell_entry = sCTkEntryPrimary(actions, width=48)
        self.dwell_entry.pack(side="left")
        self.dwell_entry.insert(0, str(self.channel_sets.dwell_seconds))
        self.dwell_entry.bind("<Return>", lambda e: self._read_dwell())
        self.dwell_entry.bind("<FocusOut>", lambda e: self._read_dwell())
        sCTkLabelTertiary(actions, text="seconds on each",
                          font=("Arial", 11)).pack(side="left", padx=4)
        self._scan_set_name = None


        # slot -> {"freq", "mode", "label", "show_label"}: edits not yet
        # written. Overlaid on what the rig reported when the list is drawn.
        self._radio_draft = {}
        self._draft_version = 0

    # -- the sets ---------------------------------------------------------
    def _set_names(self):
        """The rig's memories first, then SDR++'s channel sets by name."""
        return [RADIO_SET] + self.channel_sets.names()

    def _set_entries(self, chosen_set):
        """
        The channels in a set, in one shape whichever set it is:
        {"number", "label", "freq", "mode", "note"}.

        The rig's memories come from the model -- the rig reported them.
        SDR++'s sets come from the configuration, which is where they are
        kept.
        """
        if chosen_set == RADIO_SET:
            entries = []
            state = self.model.channels_state
            for i, ch in enumerate(self.model.channels):
                if i in self._radio_draft:
                    # An edit not yet written. Shown as it WILL be, and
                    # marked, so the list never passes it off as the rig's.
                    d = self._radio_draft[i]
                    label = d["label"] if i < LABEL_SLOTS else ""
                    if d["freq"]:
                        note = "● not written yet"
                    elif label:
                        # Labelled but with no frequency -- a label set before
                        # the VFO is stored, not a cleared slot.
                        note = "● label only, not written"
                    else:
                        note = "● cleared, not written"
                    entries.append({
                        "number": i + 1, "label": label,
                        "freq": d["freq"], "mode": d["mode"] if d["freq"] else "",
                        "note": note})
                    continue
                # A LABEL WITH NO FREQUENCY IS STILL SHOWN. It is what the rig
                # holds, and hiding it made a label written to an empty slot
                # look as though the write had failed -- until a frequency was
                # stored there and the label seemed to appear from nowhere.
                if ch is not None and not ch["freq"] and i < LABEL_SLOTS and ch["label"]:
                    entries.append({"number": i + 1, "label": ch["label"],
                                    "freq": 0, "mode": "",
                                    "note": "label only"})
                    continue
                if ch is None or not ch["freq"]:
                    # "empty" only once the rig has SAID so. Before its reply
                    # arrives, a slot is unknown, not empty -- claiming
                    # otherwise would be the interface guessing.
                    # Every slot the rig ANSWERED has an entry, empty or not,
                    # so one with no entry after the read has finished is one
                    # it never answered -- "could not be read", not "empty".
                    if ch is not None:
                        note = "empty"
                    elif state == "read":
                        note = "could not be read"
                    elif state == "reading":
                        note = "…"
                    else:
                        note = "not read yet"
                    entries.append({"number": i + 1, "label": "", "freq": 0,
                                    "mode": "", "note": note})
                    continue
                label = ch["label"] if ch["label"] is not None else ""
                # No note for slots 10-20: that they carry no label shows
                # in the label cell itself, which will not open. A note saying
                # so on eleven rows was noise.
                note = ""
                entries.append({"number": i + 1, "label": label,
                                "freq": ch["freq"], "mode": ch["mode"],
                                "note": note})
            return entries

        return [{"number": j + 1, "label": ch["label"],
                 "freq": ch["freq_hz"], "mode": ch["mode"], "note": ch["name"]}
                for j, ch in enumerate(self.channel_sets.channels(chosen_set))]

    def _on_set_chosen(self, choice):
        """A different set was chosen -- which also ends a scan of the last."""
        if self.scanner.running and choice != self._scan_set_name:
            self.scanner.stop("stopped -- another set chosen")
        self._selected_channel = None
        self.channel_table.clear_selection()
        self._shown_set = None         # force a full reload
        self.refresh()

    # -- the rows ----------------------------------------------------------
    def _refresh_channels(self):
        """
        Keeps the list and its note in step with the model.

        Called from refresh(). The rows are rebuilt only when what they show
        has changed -- a different set, or more replies from the rig --
        because rebuilding twenty rows on every meter update would be waste.
        """
        chosen_set = self.set_picker.get()
        m = self.model

        # Whichever set is showing: a read or write of the rig is happening
        # either way, and the bar says so.
        busy = m.channels_state in ("reading", "writing")
        if busy:
            if not self._progress_shown:
                # Packed BEFORE the note, so it sits straight after the
                # frequency and the note follows it.
                self.channel_progress.pack(side="left", padx=(20, 0),
                                           before=self.set_note)
                self._progress_shown = True
            total = m.channels_expected or 1
            self.channel_progress.set(min(1.0, m.channels_progress / total))
        elif self._progress_shown:
            self.channel_progress.pack_forget()
            self._progress_shown = False

        if chosen_set == RADIO_SET:
            if m.channels_state == "unread":
                self.set_note.configure(text="the rig's memories -- not read yet")
            elif m.channels_state == "writing":
                self.set_note.configure(
                    text=f"writing to the rig -- {m.channels_progress} of "
                         f"{m.channels_expected} "
                         f"{'channel' if m.channels_expected == 1 else 'channels'}")
            elif m.channels_state == "reading":
                # In CHANNELS and LABELS, not reads. There are 38 reads, but
                # nobody thinks of the rig as having 38 of anything: the
                # frequencies come first, one per channel, then the labels,
                # each of which is two reads -- its text and its show flag.
                done = m.channels_done
                if done["Freq"] < CHANNEL_SLOTS:
                    self.set_note.configure(
                        text=f"reading channels -- {done['Freq']} of {CHANNEL_SLOTS}")
                else:
                    labels = (done["Label"] + done["ShowLabel"]) // 2
                    self.set_note.configure(
                        text=f"reading labels -- {labels} of {LABEL_SLOTS}")
            else:
                used = sum(1 for i in range(len(m.channels))
                           if not m.channel_is_empty(i))
                text = f"the rig's memories -- {used} of {len(m.channels)} in use"
                if m.channels_failed:
                    text += (f", {len(m.channels_failed)} "
                             f"{'read' if len(m.channels_failed) == 1 else 'reads'}"
                             f" unanswered")
                if m.channels_write_failed:
                    text += (f" -- {len(m.channels_write_failed)} "
                             f"{'write was' if len(m.channels_write_failed) == 1 else 'writes were'}"
                             f" not acknowledged; the list shows what the rig holds")
                self.set_note.configure(text=text)
        else:
            # The application's, not SDR++'s, since the sets moved to their
            # own file -- see channel_sets.py.
            self.set_note.configure(text="a channel set -- saved as you edit")

        # A running scan says where it is. Beneath a notice, which is more
        # urgent and short-lived.
        if self.scanner.running and self.scanner.index is not None:
            entries = self._set_entries(self._scan_set_name)
            i = self.scanner.index
            if 0 <= i < len(entries):
                usable = sum(1 for e in entries if e["freq"])
                what = entries[i]["label"] or self.model.formatted(entries[i]["freq"])
                self.set_note.configure(
                    text=f"scanning -- channel {i + 1} ({what}), "
                         f"{usable} to scan in '{self._scan_set_name}'")

        # A notice, while it lasts, takes the note's place.
        if self._channel_notice:
            self.set_note.configure(text=self._channel_notice)

        self._update_channel_buttons()

        rows = [[str(e["number"]), e["label"],
                 self.model.formatted(e["freq"]) if e["freq"] else "",
                 e["mode"], e["note"]]
                for e in self._set_entries(chosen_set)]

        # A different set, or a different number of rows, reloads the table.
        # Otherwise only the rows that changed are updated, IN PLACE: during a
        # read the list changes with every reply, and rebuilding all hundred
        # cells each time is slow and flickers.
        if chosen_set != self._shown_set or len(rows) != len(self._shown_rows):
            self.channel_table.load_dataset(rows)
            self._shown_set = chosen_set
        else:
            for index, (new, old) in enumerate(zip(rows, self._shown_rows)):
                if new != old:
                    self.channel_table.set_row(index, new)
        self._shown_rows = rows

    def _select_channel(self, index):
        """A row was chosen -- by a click, or by tuning to it."""
        self._selected_channel = index
        # From code, so it does not call back here; harmless if the table
        # already has this row selected, as it does after a click.
        self.channel_table.select_row(index)
        self._update_channel_buttons()

    # -- editing the rig's set -------------------------------------------
    def _radio_channel(self, slot):
        """A slot as it currently stands: the draft if edited, else the rig's."""
        if slot in self._radio_draft:
            return dict(self._radio_draft[slot])
        ch = self.model.channels[slot]
        if ch is None:
            return {"freq": 0, "mode": "DFT", "label": "", "show_label": False}
        return {"freq": ch["freq"], "mode": ch["mode"],
                "label": ch["label"] or "", "show_label": ch["show_label"]}

    def _can_edit_radio(self):
        """True when the rig's set is showing, fully read, with a slot chosen."""
        return (self.set_picker.get() == RADIO_SET
                and self.model.channels_state == "read"
                and self._selected_channel is not None)

    def _change_draft(self, slot, **values):
        channel = self._radio_channel(slot)
        channel.update(values)
        self._radio_draft[slot] = channel
        self._draft_version += 1
        self.refresh()

    def _set_shown(self):
        """The channel set on show, or None when it is the rig's set."""
        chosen_set = self.set_picker.get()
        return None if chosen_set == RADIO_SET else chosen_set

    def _store_vfo_here(self):
        """
        The receive frequency and mode, into the chosen channel.

        The receive VFO's own frequency -- what the rig tunes to when it
        recalls the channel -- and its mode. The label is kept. Into the draft
        for the rig's set; saved at once for a set.
        """
        m = self.model
        freq, mode = m.frequency(m.rx_vfo), m.mode_of(m.rx_vfo)
        name = self._set_shown()
        if name is not None:
            if self._selected_channel is not None:
                self.channel_sets.update(name, self._selected_channel,
                                         freq_hz=freq, mode=mode)
                self.refresh()
            return
        if not self._can_edit_radio():
            return
        self._change_draft(self._selected_channel, freq=freq, mode=mode)

    def _clear_channel(self):
        """Empties a rig slot (into the draft), or deletes a set's channel."""
        name = self._set_shown()
        if name is not None:
            if self._selected_channel is None:
                return
            self.channel_sets.delete(name, self._selected_channel)
            # The row that moved up into its place is selected, or the new
            # last row if the last was deleted -- so Delete can be pressed
            # again, down a list, without reaching for the mouse each time.
            remaining = len(self.channel_sets.channels(name))
            self._selected_channel = (min(self._selected_channel, remaining - 1)
                                      if remaining else None)
            self.channel_table.select_row(self._selected_channel)
            self.refresh()
            return
        if not self._can_edit_radio():
            return
        self._change_draft(self._selected_channel, freq=0, mode="DFT",
                           label="", show_label=False)

    def _add_vfo(self):
        """
        The receive frequency and mode, as a new channel at the end of a set.

        Carries the filter width in use, which the SDR++ sets have always
        stored with a channel. The label and name start empty, ready to be
        typed into the new row, which is selected.
        """
        name = self._set_shown()
        if name is None:
            return
        m = self.model
        self.channel_sets.add(name, {"freq_hz": m.frequency(m.rx_vfo),
                                     "mode": m.mode_of(m.rx_vfo),
                                     "bandwidth": m.filter_hz})
        self._selected_channel = len(self.channel_sets.channels(name)) - 1
        self.refresh()
        self.channel_table.select_row(self._selected_channel)

    # -- the set menu ------------------------------------------------------
    def _on_set_menu(self, choice):
        """An item was chosen from the set menu."""
        self.set_menu.set("⋯")          # back to rest; the item runs below
        current = self._set_shown()
        if choice == "New set…":
            self._ask_name("New set", "", self._make_new_set)
        elif choice == "Duplicate…" and current:
            self._ask_name(f"Copy '{current}' as", f"{current} copy",
                           lambda name: self._make_duplicate(current, name))
        elif choice == "Rename…" and current:
            self._ask_name(f"Rename '{current}' to", current,
                           lambda name: self._make_rename(current, name),
                           unchanged=current)
        elif choice == "Delete set…" and current:
            self._delete_set(current)
        elif choice == "Save as a set…":
            self._ask_name("Save the rig's memories as", "Radio memories",
                           self._save_rig_as_set)

    def _ask_name(self, prompt, initial, action, unchanged=None):
        """
        Opens the name field in the header; `action(name)` runs on OK.

        `unchanged` is a name that may be confirmed as it stands -- a set's
        own name when renaming it -- which then simply closes the field.
        """
        self._close_prompts()
        self._name_prompt_action = action
        self._name_prompt_unchanged = unchanged
        self.name_prompt_label.configure(text=prompt)
        self.name_entry.delete(0, "end")
        if initial:
            self.name_entry.insert(0, initial)
        self.name_prompt.pack(side="left")
        self.name_entry.focus_set()
        self.name_entry.select_range(0, "end")

    def _name_prompt_ok(self):
        """
        Checks the name, and runs the action if it will do.

        A name that will not do -- empty, or already a set's -- keeps the
        field open and says why, rather than closing and losing the typing.
        """
        name = self.name_entry.get()
        # Confirming a set's own name when renaming it is not a clash --
        # there is simply nothing to do.
        if self._name_prompt_unchanged is not None and \
                name.strip() == self._name_prompt_unchanged:
            self._close_prompts()
            return
        problem = self.channel_sets.check_new_name(name, reserved=(RADIO_SET,))
        if problem:
            self._notify(problem)
            self.name_entry.focus_set()
            return
        action = self._name_prompt_action
        self._close_prompts()
        if action:
            action(name)

    def _close_prompts(self):
        self.name_prompt.pack_forget()
        self.copy_prompt.pack_forget()
        self._name_prompt_action = None

    def _show_set(self, name):
        """Refreshes the set list and shows `name`."""
        self.set_picker.configure(values=self._set_names())
        self.set_picker.set(name)
        self._on_set_chosen(name)

    def _make_new_set(self, name):
        self._show_set(self.channel_sets.create_set(name))

    def _make_duplicate(self, current, name):
        self._show_set(self.channel_sets.duplicate_set(current, name))

    def _make_rename(self, current, name):
        self._show_set(self.channel_sets.rename_set(current, name))

    def _delete_set(self, name):
        """
        Deletes a whole set, after asking. It cannot be undone, so this is
        the one action here that stops to confirm -- in a proper dialog, not
        the header, where a confirmation would be too easy to click through.
        """
        count = len(self.channel_sets.channels(name))
        sure = sCTkMessagebox.askyesno(
            "Delete set",
            f"Delete the set '{name}' and its {count} "
            f"{'channel' if count == 1 else 'channels'}? This cannot be undone.",
            yes_text="Delete", no_text="Keep it", master=self)
        if sure:
            self.channel_sets.delete_set(name)
            self._show_set(RADIO_SET)

    def _save_rig_as_set(self, name):
        """
        Copies the rig's twenty slots into a new set -- a backup of its
        memories in the channel file.

        What the RIG holds, not the draft: this is a record of the radio,
        and an unwritten edit is not in it yet. Empty slots are left out;
        each channel's name records the slot it came from.
        """
        channels = []
        for i, ch in enumerate(self.model.channels):
            if ch is None or not ch["freq"]:
                continue
            channels.append({"freq_hz": ch["freq"], "mode": ch["mode"],
                             "label": ch["label"] or "", "name": f"rig slot {i + 1}"})
        self._show_set(self.channel_sets.create_set(name, channels))

    # -- copying a channel ---------------------------------------------------
    def _source_channel(self, index):
        """
        The channel at `index` in the set on show, in one shape whichever
        set it is: {"freq", "mode", "label", "name"}.
        """
        if index is None:
            return None
        name = self._set_shown()
        if name is None:
            ch = self._radio_channel(index)
            return {"freq": ch["freq"], "mode": ch["mode"],
                    "label": ch["label"], "name": ""}
        channels = self.channel_sets.channels(name)
        if not 0 <= index < len(channels):
            return None
        ch = channels[index]
        return {"freq": ch["freq_hz"], "mode": ch["mode"],
                "label": ch["label"], "name": ch["name"]}

    def _open_copy_prompt(self):
        """Asks where the selected channel should go."""
        source = self._source_channel(self._selected_channel)
        if not source or not source["freq"]:
            return
        self._close_prompts()
        targets = self.channel_sets.names()
        # The rig's set only once it has been read: a copy there goes into
        # the draft, which sits on top of what the rig reported.
        if self.model.channels_state == "read":
            targets = [RADIO_SET] + targets
        if not targets:
            self._notify("there is no set to copy to -- make a set first")
            return
        self.copy_prompt_label.configure(
            text=f"Copy {self.model.formatted(source['freq'])} to")
        self.copy_target.configure(values=targets)
        current = self.set_picker.get()
        self.copy_target.set(next((t for t in targets if t != current), targets[0]))
        self._update_copy_prompt()
        self.copy_prompt.pack(side="left")

    def _update_copy_prompt(self):
        """The slot choice appears only when the rig's set is the target."""
        if self.copy_target.get() == RADIO_SET:
            # The first empty slot, so a copy does not land on a channel by
            # default. Slot 1 if every slot is in use.
            empty = next((i for i in range(CHANNEL_SLOTS)
                          if not self._radio_channel(i)["freq"]), 0)
            self.copy_slot.set(f"slot {empty + 1}")
            self.copy_slot.pack(side="left", padx=(6, 0), before=self.copy_go)
        else:
            self.copy_slot.pack_forget()

    def _copy_prompt_ok(self):
        """
        Copies the selected channel to the chosen set.

        Into a set: added at the end and saved. Into the rig's set: into the
        DRAFT for the chosen slot, like any other edit there -- written only
        with Write to radio -- and made to fit the rig: the label cut to five
        characters, or dropped for slots 10 to 20, and a mode the rig does
        not have becoming DFT.
        """
        source = self._source_channel(self._selected_channel)
        target = self.copy_target.get()
        if not source:
            self._close_prompts()
            return
        if target == RADIO_SET:
            slot = int(self.copy_slot.get().split()[-1]) - 1
            mode = source["mode"] if source["mode"] in CHANNEL_MODE_CHOICES else "DFT"
            label = ("".join(ch for ch in source["label"] if 32 <= ord(ch) < 127)
                     .strip()[:5] if slot < LABEL_SLOTS else "")
            self._close_prompts()
            self._change_draft(slot, freq=source["freq"], mode=mode,
                               label=label, show_label=bool(label))
            self._notify(f"copied to slot {slot + 1} -- Write to radio to keep it")
            return
        self.channel_sets.add(target, {"freq_hz": source["freq"], "mode": source["mode"],
                                       "label": source["label"], "name": source["name"]})
        self._close_prompts()
        self._notify(f"copied to '{target}'")

    # -- editing in the table --------------------------------------------
    def _channel_cell_editable(self, row, column):
        """
        Whether one cell may be edited, beyond its column being editable.

        A label only in slots 1 to 9 -- the rest carry none. A mode only where
        the slot has a frequency: an empty slot has no channel to be in a
        mode. Type the frequency first, and the mode becomes editable.
        """
        name = self._set_shown()
        if name is not None:
            # A set: every label may be edited, and so may the notes -- which
            # for a set is the channel's name. The mode, as for the rig, only
            # where there is a frequency.
            if column == CHANNEL_MODE_COLUMN:
                channels = self.channel_sets.channels(name)
                return row < len(channels) and bool(channels[row]["freq_hz"])
            return True
        if column == CHANNEL_LABEL_COLUMN:
            return row < LABEL_SLOTS
        if column == CHANNEL_MODE_COLUMN:
            return bool(self._radio_channel(row)["freq"])
        return True

    def _check_channel_edit(self, row, column, value):
        """
        Checks an edit to a label or frequency cell before the table keeps it.

        Returns the value TIDIED -- the label trimmed to five printable
        characters, the frequency written the way the list shows frequencies
        -- or False to refuse it, when the cell reverts to what it was.
        """
        name = self._set_shown()
        if name is not None:
            if column == CHANNEL_LABEL_COLUMN:
                return "".join(ch for ch in value if 32 <= ord(ch) < 127).strip()[:SET_LABEL_MAX]
            if column == CHANNEL_NOTES_COLUMN:
                return "".join(ch for ch in value if 32 <= ord(ch) < 127).strip()
        elif self.model.channels_state != "read":
            return False
        if column == CHANNEL_LABEL_COLUMN:
            if row >= LABEL_SLOTS:
                return False                 # slots 10-20 carry no label
            return "".join(ch for ch in value if 32 <= ord(ch) < 127).strip()[:5]
        if column == CHANNEL_FREQ_COLUMN:
            hz = parse_frequency(value)
            if hz:
                return self.model.formatted(hz)
            # SAID, not just reverted. A frequency that silently turns back
            # into the old one looks like the edit was never made.
            if value.strip():
                self._notify(f"'{value.strip()}' isn't a frequency -- "
                             f"try 14.074 or 14.074.000")
            return False
        if column == CHANNEL_MODE_COLUMN:
            return value if value in CHANNEL_MODE_CHOICES else False
        return False

    def _notify(self, text, seconds=6):
        """Shows a short message in place of the set note, for a few seconds."""
        self._channel_notice = text
        if self._notice_timer is not None:
            self.after_cancel(self._notice_timer)
        self._notice_timer = self.after(int(seconds * 1000), self._clear_notice)
        # Idle, not now: this is called from inside the table's own save, and
        # redrawing the rows in the middle of it would race with that.
        self.after_idle(self.refresh)

    def _clear_notice(self):
        self._channel_notice = None
        self._notice_timer = None
        self.refresh()

    def _channel_edited(self, row, column, value):
        """
        A cell changed in the table.

        For the rig's set, into the draft, to be written later. For a set,
        saved at once.
        """
        name = self._set_shown()
        if name is not None:
            fields = {CHANNEL_LABEL_COLUMN: "label", CHANNEL_MODE_COLUMN: "mode",
                      CHANNEL_NOTES_COLUMN: "name"}
            if column == CHANNEL_FREQ_COLUMN:
                hz = parse_frequency(value)
                if hz:
                    self.channel_sets.update(name, row, freq_hz=hz)
            elif column in fields:
                self.channel_sets.update(name, row, **{fields[column]: value})
            self.refresh()
            return
        if column == CHANNEL_LABEL_COLUMN:
            self._change_draft(row, label=value, show_label=bool(value))
        elif column == CHANNEL_FREQ_COLUMN:
            hz = parse_frequency(value)
            if hz:
                # The slot keeps its mode. One that had none -- empty, or
                # label only -- becomes DFT, which tunes to the band's usual
                # sideband.
                mode = self._radio_channel(row)["mode"]
                if mode not in ("LSB", "USB", "CWL", "CWU", "DFT"):
                    mode = "DFT"
                self._change_draft(row, freq=hz, mode=mode)
        elif column == CHANNEL_MODE_COLUMN:
            self._change_draft(row, mode=value)

    def _discard_draft(self):
        self._radio_draft = {}
        self._draft_version += 1
        if self._selected_channel is not None:
            self._select_channel(self._selected_channel)
        self.refresh()

    def _write_to_radio(self):
        """
        Sends the draft to the rig, which then reads everything back.

        The draft is let go at once. What the list shows next comes from the
        read-back -- the rig's own account -- so a write that did not take
        appears as the value the rig still holds, with the note saying so,
        rather than as a draft that looks written.
        """
        if not self._radio_draft or self.model.channels_state != "read":
            return
        channels = [(slot, d["freq"], d["mode"], d["label"], d["show_label"])
                    for slot, d in sorted(self._radio_draft.items())]
        self._radio_draft = {}
        self._draft_version += 1
        self.connection.write_channels(channels)

    def _update_channel_buttons(self):
        """Enables what can be done now, and names how much would be written."""
        in_set = self._set_shown() is not None
        chosen = self._selected_channel is not None
        editing = (chosen if in_set else self._can_edit_radio())
        for btn in (self.store_button, self.clear_button):
            btn.state("normal" if editing else "disabled")
        self.clear_button.configure(text="Delete" if in_set else "Clear")

        # What belongs to one kind of set is HIDDEN for the other, not
        # disabled. Repacked only when the kind changes.
        kind = "set" if in_set else "radio"
        if kind != self._set_kind_shown:
            if in_set:
                self.radio_actions.pack_forget()
                self.add_button.pack(side="left", padx=2, before=self.copy_button)
            else:
                self.add_button.pack_forget()
                self.radio_actions.pack(side="left", padx=(10, 0),
                                        after=self.set_menu)
            self._set_kind_shown = kind
        # Reading waits while the rig is busy reading or writing.
        busy = self.model.channels_state in ("reading", "writing")
        self.reread_button.state("disabled" if busy else "normal")

        # The set menu offers what applies to the set on show. Saving the
        # rig's memories as a set needs them read first.
        menu_kind = (kind, self.model.channels_state == "read")
        if menu_kind != self._menu_kind_shown:
            if in_set:
                items = ["New set…", "Duplicate…", "Rename…", "Delete set…"]
            else:
                items = ["New set…"]
                if self.model.channels_state == "read":
                    items.append("Save as a set…")
            self.set_menu.configure(values=items)
            self.set_menu.set("⋯")
            self._menu_kind_shown = menu_kind

        # Copying needs a channel with a frequency to copy.
        source = self._source_channel(self._selected_channel) if chosen else None
        self.copy_button.state("normal" if source and source["freq"] else "disabled")

        # Scan: Stop while running. Otherwise only with something to scan --
        # and for the rig's set, only once it is read and not being written.
        if self.scanner.running:
            self.scan_button.configure(text="■ Stop")
            self.scan_button.state("normal")
        else:
            self.scan_button.configure(text="▶ Scan")
            scannable = any(e["freq"] for e in self._set_entries(self.set_picker.get()))
            if not in_set and self.model.channels_state != "read":
                scannable = False
            self.scan_button.state("normal" if scannable else "disabled")

        # Set on the table itself, so a cell that may not be changed never
        # opens an editor at all -- rather than opening one and refusing.
        # The rig's set once it is fully read; a set at any time, and its
        # notes too, which for a set is the channel's name.
        if in_set:
            editable = [CHANNEL_LABEL_COLUMN, CHANNEL_FREQ_COLUMN,
                        CHANNEL_MODE_COLUMN, CHANNEL_NOTES_COLUMN]
        elif self.model.channels_state == "read":
            editable = [CHANNEL_LABEL_COLUMN, CHANNEL_FREQ_COLUMN, CHANNEL_MODE_COLUMN]
        else:
            editable = []
        if editable != self._shown_editable:
            self.channel_table.configure(editable_columns=editable)
            self._shown_editable = editable

        pending = len(self._radio_draft)
        ready = pending and self.model.channels_state == "read"
        self.write_button.configure(
            text=(f"Write {pending} to radio" if pending else "Write to radio"))
        self.write_button.state("normal" if ready else "disabled")
        self.discard_button.state("normal" if pending else "disabled")

    # -- tuning ------------------------------------------------------------
    def _tune_to_selected(self):
        if self._selected_channel is not None:
            self._tune_to_channel(self._selected_channel)

    # -- scanning -----------------------------------------------------------
    def _toggle_scan(self):
        """Starts a scan of the set on show, or stops the one running."""
        if self.scanner.running:
            self.scanner.stop("stopped")
            return
        self._read_dwell()
        name = self.set_picker.get()
        self._scan_set_name = name
        # The channels are FETCHED at every step, not copied now, so an edit
        # made during the scan is honoured on the next pass.
        self.scanner.start(lambda: self._set_entries(name),
                           start_index=self._selected_channel or 0,
                           dwell_seconds=self.channel_sets.dwell_seconds)
        self.refresh()

    def _read_dwell(self):
        """Takes the time on each channel from its box, and saves it."""
        seconds = self.channel_sets.set_dwell_seconds(self.dwell_entry.get())
        # The box shows what was kept -- a number out of range comes back
        # within it, and anything unreadable shows the value still in use.
        self.dwell_entry.delete(0, "end")
        self.dwell_entry.insert(0, str(seconds))

    def _scan_reached(self, index):
        """The scan arrived at a channel: show it."""
        self._selected_channel = index
        self.channel_table.select_row(index)
        self.refresh()

    def _scan_stopped(self, reason):
        """The scan ended -- by request, or because the operator took over."""
        self._notify(f"scan {reason}")
        self.refresh()

    def _tune_to_channel(self, index):
        """
        Puts the receiver on a channel, through the rig.

        A COMMAND like any other control: the rig is told, the model changes
        when it confirms, and SDR++ follows the model. Nothing here writes a
        frequency directly.

        The mode is changed only when the channel has one the rig can use;
        DFT tunes to the band's usual sideband. A set may hold modes the rig
        does not have.

        Tuning by hand ends a scan: the operator has chosen a channel.
        """
        if self.scanner.running:
            self.scanner.stop("stopped -- you chose a channel")
        entries = self._set_entries(self.set_picker.get())
        if not 0 <= index < len(entries):
            return
        entry = entries[index]
        if not entry["freq"]:
            return
        self._select_channel(index)
        # One call, not two. Sent back to back, the rig dropped the mode --
        # see uBITX_Link.tune_to, which knows how long to wait between them.
        self.connection.tune_to(entry["freq"], entry["mode"])

    def _on_tab(self, name):
        """
        A tab was clicked.

        The rig's memories are read the first time Channels is opened, not at
        startup -- the startup dump is already long, and this adds 38 replies
        for something you may not look at.
        """
        if name == "Channels" and self.model.channels_state == "unread":
            self.connection.read_channels()

    def _build_cw(self, page):
        wrap = sCTkFrame(page, fg_color="transparent", border_width=0)
        wrap.pack(fill="both", expand=True, padx=14, pady=12)
        sCTkLabelPrimary(wrap, text="CW",
                         font=("Arial", 15, "bold")).pack(anchor="w")
        sCTkLabelTertiary(
            wrap,
            text="Keyer settings live here rather than in a dialog: you adjust "
                 "speed and tone while operating, sometimes mid-QSO.",
            font=("Arial", 11), wraplength=640, justify="left").pack(anchor="w", pady=(2, 12))

        for label, value in (("Tone (Hz)", "500"), ("Speed (wpm)", "10"),
                             ("Delay to TX (ms)", "250"),
                             ("Delay to RX (ms)", "1000")):
            line = sCTkFrame(wrap, fg_color="transparent", border_width=0)
            line.pack(anchor="w", pady=3)
            sCTkLabelSecondary(line, text=label, width=130,
                               font=("Arial", 11)).pack(side="left")
            entry = sCTkEntryPrimary(line, width=80)
            entry.pack(side="left")
            entry.insert(0, value)

        line = sCTkFrame(wrap, fg_color="transparent", border_width=0)
        line.pack(anchor="w", pady=3)
        sCTkLabelSecondary(line, text="Keyer", width=130,
                           font=("Arial", 11)).pack(side="left")
        sCTkSegmentedButton(line, values=["Straight", "Iambic A",
                                          "Iambic B"]).pack(side="left")

        practice = sCTkFrame(wrap, fg_color="transparent", border_width=0)
        practice.pack(anchor="w", pady=(14, 0))
        sCTkSwitch(practice, text="Practice mode").pack(side="left")
        sCTkLabelTertiary(
            practice,
            text="keyer and sidetone work, nothing reaches the antenna",
            font=("Arial", 10)).pack(side="left", padx=10)

        decoder = sCTkButtonSecondary(wrap, text="Decoder", width=110)
        decoder.pack(anchor="w", pady=(14, 0))
        decoder.state("disabled")
        sCTkLabelTertiary(wrap, text="awaiting a backend that decodes",
                          font=("Arial", 10)).pack(anchor="w")

    def _build_setup(self, page):
        """
        Everything set once, gathered into groups on one page.

        The dialogs this replaces were one window each -- logbook, SDR,
        machine, connection -- which meant hunting through a menu to find
        which one held a given setting. Grouped here they are all visible at
        once, and the relationships are obvious: the SDR address sits beside
        the SDR software that uses it.

        Two keep their own windows: EEPROM and machine settings both write
        values that can stop the radio working, and both deserve a deliberate
        act rather than a field on a page you are scrolling past.
        """
        wrap = sCTkFrame(page, fg_color="transparent", border_width=0)
        wrap.pack(fill="both", expand=True, padx=14, pady=10)

        groups = (
            ("Station", (
                ("Callsign", "entry", self.model.callsign),
                ("Appearance", "choice", ["Dark", "Light", "Follow system"]),
            )),
            ("Radio", (
                ("Connection", "button", "Serial or network…"),
                ("Tuning presets", "choice", ["10 Hz", "50 Hz", "100 Hz",
                                              "500 Hz", "1 kHz"]),
            )),
            ("SDR", (
                ("Software", "choice", ["SDR++", "SDRangel", "Gqrx", "None"]),
                ("Address", "entry", "127.0.0.1:4532"),
                ("Autostart", "switch", True),
                ("Default bandwidth CW", "entry", "500"),
                ("Default bandwidth SSB", "entry", "2600"),
            )),
            ("Logbook", (
                ("Enabled", "switch", True),
                ("Format", "choice", ["ADIF", "CSV"]),
                ("File", "button", "~/Downloads/ubitx_Logbook.adi"),
                ("Backup every (minutes)", "entry", "30"),
            )),
        )

        columns = sCTkFrame(wrap, fg_color="transparent", border_width=0)
        columns.pack(fill="both", expand=True)
        columns.grid_columnconfigure((0, 1), weight=1, uniform="setup")

        for index, (title, rows) in enumerate(groups):
            box = sCTkFrame(columns, border_width=1, corner_radius=6)
            box.grid(row=index // 2, column=index % 2, sticky="nsew",
                     padx=4, pady=4)

            sCTkLabelSecondary(box, text=title, font=("Arial", 12, "bold")
                               ).pack(anchor="w", padx=10, pady=(8, 4))

            for label, kind, value in rows:
                line = sCTkFrame(box, fg_color="transparent", border_width=0)
                line.pack(fill="x", padx=10, pady=2)
                sCTkLabelTertiary(line, text=label, width=150,
                                  font=("Arial", 11), anchor="w").pack(side="left")

                if kind == "entry":
                    field = sCTkEntryPrimary(line, width=150)
                    field.pack(side="left")
                    field.insert(0, value)
                elif kind == "choice":
                    sCTkComboBox(line, values=value, width=150).pack(side="left")
                elif kind == "switch":
                    sCTkSwitch(line, text="").pack(side="left")
                else:
                    sCTkButtonSecondary(line, text=value, width=200,
                                        anchor="w").pack(side="left")

            # Bottom padding comes from the LAST ROW'S pady, not a spacer.
            #
            # There used to be a spacer here -- an sCTkFrame with a height
            # and no width. It took CustomTkinter's default width of 200,
            # sat centred against the bottom edge, and "transparent" means
            # "paint in the parent's colour" -- so it painted a 200-pixel
            # strip of background straight across the group's border. Every
            # group had a gap in its bottom edge, the same span each time.
            line.pack_configure(pady=(2, 10))

        danger = sCTkFrame(wrap, fg_color="transparent", border_width=0)
        danger.pack(anchor="w", pady=(10, 0))
        sCTkButtonSecondary(danger, text="EEPROM settings…",
                            width=150).pack(side="left", padx=(0, 6))
        sCTkButtonSecondary(danger, text="Machine settings…",
                            width=150).pack(side="left", padx=(0, 10))
        sCTkButtonSecondary(danger, text="Backup and restore…", width=170,
                            command=self._eeprom_backup).pack(side="left", padx=(0, 6))
        sCTkButtonSecondary(danger, text="About…", width=90,
                            command=self._about).pack(side="left", padx=(0, 10))
        sCTkLabelTertiary(
            danger,
            text="both write to the radio — their own windows, and a confirmation",
            font=("Arial", 10)).pack(side="left")

    # -- behaviour --------------------------------------------------------
    def _toggle(self, key):
        """
        Sends a command. Does NOT change the state -- the reply does that.
        """
        # Through the CONNECTION, not the stub. Both were live and writing
        # to the same model, which is how a mode set by one and confirmed by
        # the other ends up arguing with itself.
        {"split": self.connection.Toggle_Split,
         "rit": self.connection.Toggle_RIT,
         "locked": self.connection.Toggle_Lock,
         "muted": self._mute_pressed,
         "tx_inhibit": self.connection.Toggle_Stop}[key]()

    def _mute_pressed(self):
        """
        Mutes whichever receiver you are listening through.

        It used to mute the rig's speaker whatever you were listening to, so
        with SDR++ as the receiver, Mute silenced the wrong thing -- the rig,
        which was already meant to be quiet -- and left SDR++ playing.
        """
        if self._listen_source == "SDR":
            self._sdr_muted = not self._sdr_muted
            self.sdr.set_muted(self._sdr_muted)
            self.refresh()
        else:
            self.connection.Toggle_Speaker()

    def _set_listen_source(self, source):
        """
        Chooses which receiver you are listening through.

        LISTENING THROUGH SDR++ SILENCES THE RIG, and switching back restores
        it -- otherwise you hear both at once. On the uBITX that is the
        rig's own "SDR mode" (TS_CMD_SDR, which Toggle_Speaker sends): it
        routes the audio out for an SDR and quiets the speaker.

        The command is a TOGGLE, so it is sent only when the rig is not
        already where it needs to be, judged by model.muted.
        """
        self._listen_source = source
        rig_should_be_muted = (source == "SDR")
        # Only once built. Setting the picker's starting value must not
        # reach the rig: its state is not known yet, and a second toggle at
        # startup would cancel the first.
        if self._ready and self.model.muted != rig_should_be_muted:
            self.connection.Toggle_Speaker()
        self.volume_slider.configure(
            state="normal" if source == "SDR" else "disabled")
        self.refresh()

    def _split_offset(self, khz):
        """
        Puts TX a given distance from RX.

        Measured from the RECEIVE frequency each time, not from wherever TX
        currently sits -- see SPLIT_OFFSETS. Zero is simplex: TX back onto
        the frequency you are listening to.
        """
        if self.model.locked:
            return
        # A COMMAND to the link, which works out which VFO to reach.
        #
        # Both earlier versions were wrong. connection.set_frequency takes
        # one argument, so calling it with a VFO name raised; and
        # model.set_frequency changed the readout without telling the rig,
        # so the offset appeared and the rig's next report took it away
        # again. Both also picked the transmit VFO before split had been
        # confirmed, when "b" is only right if A happens to be active.
        self.connection.set_split_offset(khz * 1000)

        # Show it now. The offset lands through a borrow, which holds the
        # display for several hundred milliseconds -- the same lag the dial
        # had until it began drawing its own target, and fixed the same way.
        self.panel_tx.show_pending(
            self.model.role_frequency("rx") + khz * 1000)

    def _toggle_tx(self):
        """Simulation only -- the rig reports transmit, it is not commanded."""
        if self.model.tx_inhibit and not self.model.transmitting:
            return
        self.rig.report_transmitting(not self.model.transmitting)

    def _swap(self):
        """
        Swaps which VFO receives and which transmits.

        A TOGGLE, not an exchange of contents. The rig has no command to
        swap two VFOs' frequencies -- and it does not need one, because
        roles follow the active VFO: make the other one primary and receive
        and transmit trade places, which is the operational effect wanted.

        Doing it in the model instead was a lie the rig never heard. It
        looked right for a moment and then reverted, because the rig's own
        reports say where the frequencies actually are.
        """
        self.connection.toggle_vfo()

    def _copy_AtoB(self):
        """
        Copies the active VFO onto the other one, frequency and mode.

        Through the CONNECTION now. It was on the stub, which changed the
        model and told the rig nothing -- so it looked right until the rig's
        next report put the old value back.

        The firmware has no copy command, so the link does it with the same
        borrow the transmit write uses: the rig only writes to whichever VFO
        is primary, so the other one is made primary for a moment.
        """
        self.connection.copy_active_to_other()

    def _on_mode(self, value):
        # The STRING, not an index. The link converts using its own MODES,
        # which is not this module's: the firmware's codes start with DFT and
        # ERR, so "USB" is 3 there and 1 here. Two lists of the same name with
        # different contents is a trap worth not walking into twice -- the
        # view names modes, the link encodes them.
        #
        # set_mode_everywhere, not set_mode: in split the transmit VFO needs
        # the new mode as well, or it goes on transmitting in the old one.
        self.connection.set_mode_everywhere(value)

    def _on_band(self, *_):
        label = self.band_picker.get()
        for i, (name, freq, endfreq) in enumerate(self.model.BANDS):
            if name == label:
                print("band change", self.model.active, freq)
                # "rx", NOT model.active.
                #
                # set_role_frequency takes a ROLE. Handing it a VFO name --
                # "a" or "b" -- misses the receive branch and falls through
                # to transmit, so in split a band change borrowed the
                # primary slot and retuned the TRANSMIT vfo while receive
                # stayed put. Changing band is a receive action: it is where
                # you want to listen.
                self.connection.set_role_frequency("rx", freq)
                # Bands imply modes -- below 10 MHz is LSB by convention.
                # If in CW mode, maintain CW mode
                if self.model.mode[0:2] == "CW":
                    mode = "CWL" if freq < 10_000_000 else "CWU"
                else:
                    mode = "LSB" if freq < 10_000_000 else "USB"
                self.connection.set_mode(mode)
                self.mode_picker.set(mode)    #MJH #probably shouldnt be here as rig should set it
                break

    def _filter_reset(self):
        """Back to the configured default width for the current mode."""
        # SDR++'s, not the rig's -- the uBITX has no filter command. The
        # defaults come from the configuration, so they match the Setup page.
        self.sdr.reset_filter()

    def _filter(self, delta):
        self.sdr.set_filter(self.model.filter_hz + delta)

    def _about(self):
        """
        Where the callsign and firmware version went.

        They were on the main screen's top line, sharing space with live
        state -- but neither changes, so neither earns a place you look at
        while operating. The file paths belong here too: you need them when
        something has gone wrong, not while working a pileup.
        """
        win = ctk.CTkToplevel(self)
        win.title("About")
        win.geometry("520x300")
        win.transient(self)

        body = sCTkFrame(win, fg_color="transparent", border_width=0)
        body.pack(fill="both", expand=True, padx=18, pady=16)

        sCTkLabelPrimary(body, text="uBITX CEC Desktop",
                         font=("Arial", 16, "bold")).pack(anchor="w")
        sCTkLabelTertiary(body, text="a visual desktop for KD8CEC-powered uBITX radios",
                          font=("Arial", 11)).pack(anchor="w", pady=(0, 10))

        for label, value in (
            ("Version", "1.0  ·  June 2026"),
            ("Author", "Mark Hatch (AJ6CU)"),
            ("Email", "markjhatch@gmail.com"),
            ("Radio firmware", self.model.firmware),
            ("Configuration", "~/.ubitx_cec_desktop.ini"),
            ("Logbook", "~/Downloads/ubitx_Logbook.adi"),
            ("Licence", "GPL v3"),
        ):
            line = sCTkFrame(body, fg_color="transparent", border_width=0)
            line.pack(anchor="w", pady=1)
            sCTkLabelTertiary(line, text=label, width=120,
                              font=("Arial", 11), anchor="w").pack(side="left")
            sCTkLabelSecondary(line, text=value,
                               font=("Arial", 11)).pack(side="left")

        sCTkButtonSecondary(body, text="Close", width=80,
                            command=win.destroy).pack(anchor="w", pady=(14, 0))

    def _eeprom_backup(self):
        """
        Compare and copy the radio's stored settings.

        Three places a value can live -- the factory default, what is in the
        radio now, and what is in the configuration file -- shown side by side
        so the differences are visible before anything is written.

        THE DIRECTION IS ABOVE THE COLUMNS, not below them in two dropdowns.
        Source and destination pickers under the table mean reading the
        values, then looking away to work out which way "Copy" goes. Putting
        the arrow in the header keeps it where the eye already is, and the
        two columns it names are the two being compared.
        """
        win = ctk.CTkToplevel(self)
        win.title("Radio settings — compare and copy")
        win.geometry("700x420")
        win.transient(self)

        body = sCTkFrame(win, fg_color="transparent", border_width=0)
        body.pack(fill="both", expand=True, padx=16, pady=14)

        direction = sCTkFrame(body, fg_color="transparent", border_width=0)
        direction.pack(anchor="w", pady=(0, 8))
        sCTkLabelTertiary(direction, text="copy",
                          font=("Arial", 11)).pack(side="left", padx=(0, 6))
        sCTkComboBox(direction, values=["Config file", "Factory", "Radio"],
                     width=130).pack(side="left")
        sCTkLabelPrimary(direction, text="  →  ",
                         font=("Arial", 14, "bold")).pack(side="left")
        sCTkComboBox(direction, values=["Radio", "Config file"],
                     width=130).pack(side="left")
        sCTkLabelTertiary(direction, text="   differences are marked",
                          font=("Arial", 10)).pack(side="left", padx=8)

        table = sCTkFrame(body, border_width=1, corner_radius=6)
        table.pack(fill="both", expand=True)

        head = sCTkFrame(table, fg_color="transparent", border_width=0)
        head.pack(fill="x", padx=8, pady=(6, 2))
        for text, width in (("", 30), ("Setting", 150), ("Factory", 120),
                            ("In the radio", 130), ("Config file", 130)):
            sCTkLabelTertiary(head, text=text, width=width,
                              font=("Arial", 11, "bold"),
                              anchor="w").pack(side="left")

        rows = (
            ("Master calibration", "85351", "148711", "—"),
            ("SSB BFO", "11056992", "11056342", "—"),
            ("CW BFO", "—", "11056042", "—"),
            ("Key type", "—", "Straight", "Straight"),
            ("CW speed (wpm)", "15", "5", "10"),
            ("Sidetone (Hz)", "600", "600", "600"),
            ("Delay to TX (ms)", "—", "0", "500"),
            ("Delay to RX (ms)", "—", "600", "5000"),
        )
        for name, factory, radio_value, config in rows:
            line = sCTkFrame(table, fg_color="transparent", border_width=0)
            line.pack(fill="x", padx=8, pady=1)
            # A CHECKBOX, not a switch. A switch says "this setting is on";
            # picking rows out of a table is selection, and a tick reads as
            # selected at a glance where a coloured track does not.
            sCTkCheckBox(line, text="", width=30).pack(side="left")
            sCTkLabelTertiary(line, text=name, width=150,
                              font=("Arial", 11), anchor="w").pack(side="left")
            sCTkLabelTertiary(line, text=factory, width=120,
                              font=("Arial", 11), anchor="w").pack(side="left")
            # A value that differs from the one beside it is the whole reason
            # for looking at this table, so it is the thing that stands out.
            differs = radio_value != config and "—" not in (radio_value, config)
            cell = sCTkLabelSecondary if differs else sCTkLabelTertiary
            cell(line, text=radio_value, width=130,
                 font=("Arial", 11, "bold") if differs else ("Arial", 11),
                 anchor="w").pack(side="left")
            cell(line, text=config, width=130,
                 font=("Arial", 11, "bold") if differs else ("Arial", 11),
                 anchor="w").pack(side="left")

        footer = sCTkFrame(body, fg_color="transparent", border_width=0)
        footer.pack(anchor="w", pady=(10, 0))
        sCTkCheckBox(footer, text="Select all").pack(side="left", padx=(0, 16))
        sCTkButtonPrimary(footer, text="Copy selected", width=120,
                          command=win.destroy).pack(side="left", padx=(0, 6))
        sCTkButtonSecondary(footer, text="Cancel", width=80,
                            command=win.destroy).pack(side="left")

    def _log_qso(self):
        """
        The log dialog: everything known is filled in, and the only field
        needing typing has the focus.
        """
        win = ctk.CTkToplevel(self)
        win.title("Log QSO")
        win.geometry("340x300")
        win.transient(self)

        body = sCTkFrame(win, fg_color="transparent", border_width=0)
        body.pack(fill="both", expand=True, padx=16, pady=14)

        sCTkLabelSecondary(body, text="Callsign",
                           font=("Arial", 11)).pack(anchor="w")
        call = sCTkEntryPrimary(body, width=200)
        call.pack(anchor="w", pady=(2, 10))
        call.focus_set()

        s = self.model
        known = (
            ("Frequency", f"{s.frequency(s.tx_vfo) / 1_000_000:.6f} MHz"),
            ("Band", s.band_name()),
            # ("Band", BANDS[s.band_index][0]),
            ("Mode", s.mode),
            ("RST sent", "599"),
            ("RST received", "599"),
        )
        for label, value in known:
            line = sCTkFrame(body, fg_color="transparent", border_width=0)
            line.pack(anchor="w", pady=1)
            sCTkLabelTertiary(line, text=label, width=110,
                              font=("Arial", 11)).pack(side="left")
            sCTkLabelSecondary(line, text=value,
                               font=("Arial", 11)).pack(side="left")

        row = sCTkFrame(body, fg_color="transparent", border_width=0)
        row.pack(anchor="w", pady=(14, 0))
        sCTkButtonPrimary(row, text="Log", width=80,
                          command=win.destroy).pack(side="left", padx=(0, 6))
        sCTkButtonSecondary(row, text="Cancel", width=80,
                            command=win.destroy).pack(side="left")

        win.bind("<Return>", lambda e: win.destroy())

    # -- redraw -----------------------------------------------------------
    def refresh(self):
        """
        Redraws everything from the state. The only place the view reads it.

        A TOP-DOWN WALK, not a broadcast. This window owns its panels, so it
        tells each one to re-read rather than having them register for
        notifications: the registration would be indirection with nothing
        gained, since the owner already knows what its parts are. It also
        keeps the ORDER explicit, which matters when one panel's size
        depends on another having been laid out first.

        Every component here is passive. None of them holds a copy of
        anything, none of them is told WHAT changed, and none of them can
        disagree with the state, because they all read it fresh.

        Cheap enough to run on every report, and RadioState coalesces a burst
        into one call -- so the rate is its problem rather than this one's.
        """
        if not self._ready:
            return

        s = self.model

        # The two frequency panels re-read themselves.
        self.panel_rx.update_view(s)
        self.panel_tx.update_view(s)

        # Transmit indicator.
        self.tx_chip.configure(
            text=" TX " if s.transmitting else " RX ",
            fg_color=("#993C1D", "#993C1D") if s.transmitting
            else ("#0F6E56", "#0F6E56"))

        # Latched controls read as lit or unlit.
        for key, btn in self._toggles.items():
            if key == "muted":
                # Lit for whichever receiver Mute acts on, and says which, so
                # there is no doubt what pressing it will silence.
                on = (self._sdr_muted if self._listen_source == "SDR"
                      else s.muted)
                btn.configure(text=("Mute SDR" if self._listen_source == "SDR"
                                    else "Mute rig"))
            else:
                on = getattr(s, key)
            btn.configure(fg_color=("#0F6E56", "#0F6E56") if on else
                          ("#E2E8F0", "#1F2937"))

        # The split offsets are live only in split. state() repaints, so it
        # is called only when the answer changes.
        if self._offset_state != s.split:
            self._offset_state = s.split
            for btn in self._offset_buttons:
                btn.state("normal" if s.split else "disabled")

        if s.split:
            delta = s.split_delta_hz()
            if delta == 0:
                self.offset_note.configure(text="transmitting on the rx frequency")
            else:
                self.offset_note.configure(
                    text=f"transmitting {abs(delta) / 1000:g} kHz "
                         f"{'above' if delta > 0 else 'below'} rx")
        else:
            # A SPACE, not an empty string: sCTk labels ignore text="" (see
            # the standby label), so this note would have gone on saying
            # "transmitting 2 kHz above rx" after split was switched off.
            # Not hidden either -- it sits under the offset buttons, and
            # removing it would move them.
            self.offset_note.configure(text=" ")

        # The rest of the readouts.
        # The band picker follows the receive frequency, like every other
        # readout here. It used to keep whatever was last chosen from it,
        # so after a swap it named the band the radio had left.
        #
        # Safe because sCTkSpinbox.set() does not fire its command -- a
        # programmatic set is the application saying what the value is, and
        # firing would turn this into a loop.
        band_now = s.band_name()
        if band_now and self.band_picker.get() != band_now:
            self.band_picker.set(band_now)

        # The mode button follows the model too. It only changed when clicked,
        # so a mode set anywhere else -- SDR++, or the rig's own buttons --
        # reached the model and never showed: the filter moved, the transmit
        # readout moved, and the button went on naming the old mode.
        #
        # Safe for the same reason as the band picker: a segmented button's
        # set() does not fire its command, so this cannot loop back into
        # _on_mode.
        if s.mode and self.mode_picker.get() != s.mode:
            self.mode_picker.set(s.mode)

        self.filter_label.configure(text=f"{s.filter_hz} Hz")
        self.mode_label.configure(text=s.mode)
        self._refresh_channels()
        self.channel_now.configure(
            text=f"{s.role_text('rx')}   {s.mode}")

        # Meters. The receive side goes quiet on transmit and the transmit
        # side wakes up -- one instrument, two halves, neither ever dead.
        self.s_meter.set(s_value=0.0 if s.transmitting else s.s_value)
        self.p_meter.set(pwr_value=s.pwr, swr_value=s.swr)

    def _tick(self):
        """
        Kept as a hook, doing nothing.

        This used to invent S-meter and power readings on a 400 ms timer.
        Right when there was no radio, wrong the moment one was attached:
        simulated values overwrite whatever the rig reports, and the
        heartbeat redraws the interface whether or not anything moved.

        Chasing what looked like an infinite loop led here -- it was this
        timer, printing three times per redraw from inside role_frequency.
        Three redraws happened in the whole run.

        Left in place rather than deleted because the meters have no real
        source yet: the rig's signal reports are not wired through, and this
        is where they will arrive.
        """
        return


if __name__ == "__main__":
    # ctk.set_appearance_mode("dark")
    UbitxCecDesktop().mainloop()