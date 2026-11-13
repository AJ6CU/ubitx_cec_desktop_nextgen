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
import atexit
import json
import os
import webbrowser                      # FIX (2026-11-10): the Help button
from datetime import datetime, timezone   # FIX (2026-11-10): Log QSO, UTC
import logbook                         # FIX (2026-11-10): Log QSO writes
import signal
import random
import serial
import tkinter as tk
import tkinter.font as tkfont
import time

import customtkinter as ctk

import globalvars as gv
from configuration import ConfigurationManager
from channel_sets import ChannelSets, LABEL_MAX as SET_LABEL_MAX
from serial_ports import list_rig_ports, parse_rig_port, open_rig_port
from radio_model import RadioModel, LABEL_SLOTS, CHANNEL_SLOTS
from sdr_link import SDR_Link
from scanner import Scanner
import sdr_programs
import sdr_controls
from app_paths import config_path, shown as shown_path
from sdr_programs import profile_for, choices as sdr_choices, MUTE
from ubitx_link import uBITX_Link, MCU_COMMAND_HEADROOM, MCU_COMMAND_HEADROOM_MAX
import ubitx_link            # FIX (2026-11-06): its adjustable timings
TIMING_KEY = "Link Timing"   # where they are saved in the settings file

from scustomtkinter import (
    sCTk, sCTkFrame, sCTkNotebook,
    sCTkLabelPrimary, sCTkLabelSecondary, sCTkLabelTertiary,
    sCTkButtonPrimary, sCTkButtonSecondary, sCTkButtonTertiary,
    sCTkSMeterBar, sCTkDialContinuous, sCTkDialRange, sCTkSpinbox,
    sCTkSegmentedButton, sCTkSwitch, sCTkComboBox, sCTkEntryPrimary,
    sCTkOptionMenuPrimary, sCTkMessagebox,
    sCTkCheckBox, sCTkFrequencyDisplay, sCTkSlider,
    sCTkProgressBar, sCTkTableview, sCTkScrollableFrame,
    sCTkFrameLabeledSecondary,
)
# From its module, as the Designer's builder file imports it -- whether or not
# the package's top level exports it.
from scustomtkinter.sctk_dial import sCTkDialSelector
# FIX: pop-up windows are sCTkToplevel, themed like the rest -- were plain
# ctk.CTkToplevel, the one widget not from the library. Imported from its
# module, as sCTkDialSelector is.
from scustomtkinter.sctk_toplevel import sCTkToplevel

# ---------------------------------------------------------------------------
# Simulated radio
# ---------------------------------------------------------------------------
# BANDS = [
#     ("160 m", 1_840_000), ("80 m", 3_573_000), ("40 m", 7_074_000),
#     ("30 m", 10_136_000), ("20 m", 14_074_000), ("17 m", 18_100_000),
#     ("15 m", 21_074_000), ("12 m", 24_915_000), ("10 m", 28_074_000),
# ]
MODES = ["LSB", "USB", "CWL", "CWU"]

# The SDR programs offered on Setup come from sdr_programs.json -- see
# sdr_choices(), imported above. A program added to that file appears here
# with no change to this code, which is the point of the file.

# Logbook formats: what the setting holds, and what it is called. The setting
# IS the file's extension -- see _choose_logbook_file.
LOGBOOK_FORMATS = (("adi", "ADIF"), ("csv", "CSV"))
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

# How long the rig has to answer the startup dump before it counts as silent.
# The reports normally begin within a fraction of a second.
RIG_ANSWER_MS = 2500
# FIX (2026-11-06): how many times the rig is restarted at connect to fetch
# values its startup burst lost -- see _check_rig_answered.
RIG_REPORT_RETRIES = 2
# FIX (2026-11-06): how long a rig that is SENDING (zeros, while it boots) is
# waited for before it is called silent -- seen on the station: 17 352 zero
# bytes, about three seconds, before the first report.
RIG_ANSWER_MAX_MS = 10000

# One row of a Setup group, and the controls in it. Fixed so the rows keep
# the same pitch whatever kind of control they hold.
SETTINGS_ROW_HEIGHT = 30
SETTINGS_CONTROL_HEIGHT = 24
# FIX: the first field of each Logbook line -- the File button, and the cell
# the Enabled switch sits in -- so Format and Backup form a column.
LOGBOOK_FIELD_WIDTH = 250

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
# The dial runs the panel's full height, beside the header line and the
# readout stack together; the panel is as tall as the taller of the two. They
# are kept roughly in step, since pushing one much past the other only adds
# empty space.
FREQ_FONT_SIZE = 56
KNOB_DIAMETER = 118

# The small knobs beside the receive aids -- RF gain and the AGC's
# adjustments. See SmallKnob.
SMALL_KNOB_DIAMETER = 30
# Each small knob's column: wide enough for "Average" or "2048 ms" beneath it.
SMALL_KNOB_COLUMN = 60
# A RANGE knob draws its two end values beside the arc's ends, below and to
# either side of the knob; its canvas is sized to hold them -- see
# _range_canvas_size. The labels are small, to fit.
RANGE_KNOB_LABEL_FONT = ("Arial", 8)

# RF gain's knob, on its own beside the listening aids: large, since it is
# ridden. A RANGE knob in whole dB -- or, over rigctl, whole percent of the
# SDR's range -- see _rf_gain_set.
RF_GAIN_KNOB_DIAMETER = 72
RF_GAIN_KNOB_COLUMN = 130


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
# The panel is meant to sit against the SDR program, and getting the two lined
# up is fiddly enough that nobody wants to do it twice. Reading the SDR's own window
# geometry would be the obvious alternative, but Tk cannot see another
# application's windows -- and the answer would be stale the moment either
# one moved.
#
# In the application's folder, ~/.ubitx_cec_desktop/ -- see app_paths.
GEOMETRY_FILE = config_path("geometry.json")

# Which listening-aid pop-ups were left PINNED, and where -- see AidPopup.
PINNED_AIDS_FILE = config_path("pinned_aids.json")


class NullRig:
    """
    Stands in for uBITX_Link when no port is open.

    Every command is accepted and does nothing, so the interface runs with no
    radio attached -- which is what the operator sees while choosing a port,
    and what they are left with if none works. The alternative is a check
    before every command, in every handler, forever.

    It reports NOTHING back, so the model stays empty and the readouts show
    zeros: obviously "not known", which is the truth.
    """

    reader_process_id = None
    # FIX (2026-11-10): THE LINK'S DATA, not commands, answered as "nothing
    # yet". __getattr__ below hands back a do-nothing function for any name,
    # so `"sc" in getattr(connection, "seen_reports", ())` met a function and
    # raised -- with no rig plugged in the window never opened (Mark).
    # Anything the window READS from the link, rather than calls, goes here.
    seen_reports = frozenset()
    bytes_seen = 0

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


# ---------------------------------------------------------------------------
# A frequency readout whose digits can be clicked
# ---------------------------------------------------------------------------
def _range_canvas_size(diameter, widest_label):
    """
    (width, height) of a RANGE knob's canvas: the knob, and room for its two
    end labels as the dial draws them.

    sCTkDialRange puts each end label at 0.707 x (radius + 9 + font size)
    from the centre -- the arc's ends are 45 degrees below horizontal -- and
    grows it OUTWARD from there, right-anchored on the left and left-anchored
    on the right (see sCTKDialBase._label_placement). So the room each side
    needs is that distance plus the label's own width, which is measured
    rather than guessed: a fixed margin clipped "-119" and "500" on the small
    knobs and "50" on RF gain. Below the centre it is the same distance plus
    half the text's height. The canvas is centred on the knob, so each
    half-size is the larger of what the knob and the labels need.
    """
    radius = diameter / 2.0
    size = int(RANGE_KNOB_LABEL_FONT[1])
    reach = 0.7072 * (radius + 9 + size)
    font = tkfont.Font(family=RANGE_KNOB_LABEL_FONT[0], size=size)
    half_width = max(radius + 3, reach + font.measure(widest_label) + 3)
    half_height = max(radius + 3, reach + font.metrics("linespace") / 2.0 + 2)
    return int(2 * half_width + 0.5), int(2 * half_height + 0.5)


def _backdrop_colour(widget):
    """
    The colour actually behind a widget: the nearest ancestor whose fg_color
    is not "transparent". Handed to a dial as its own fg_color, because the
    dial looks only six parents up for one and otherwise falls back to a
    fixed dark grey -- the dark squares behind the knobs, which sit more
    than six transparent frames deep.
    """
    parent = widget
    while parent is not None:
        try:
            colour = parent.cget("fg_color")
        except Exception:
            colour = None
        if colour and colour != "transparent":
            return colour
        parent = getattr(parent, "master", None)
    return "transparent"


class SmallKnob(sCTkFrame):
    """
    A small knob with what it sets above it and the value below. A column of
    fixed width, so knobs side by side line up. Left click one step down,
    right click one step up, turned or scrolled as many steps as it turns.
    Two kinds, as the setting suits:

    FLYWHEEL (on_step) -- sCTkDialContinuous, the tuning dial's kind, small.
    It keeps no value: each step is handed to `on_step` with its sign, and
    the owner works out the value. For settings whose stored numbers are not
    what an operator reads -- the AGC time constant's power of two, RF gain's
    list of steps -- and for one that only shows (NR's scheme).

    RANGE (on_set, span) -- sCTkDialRange, with end stops and a pointer that
    shows where the value sits, its two end values labelled. It keeps its own
    value and hands each new one to `on_set`. set_position() moves it to a
    value from the SDR WITHOUT calling on_set: the dial's own set() reports
    every change, so without the guard a value the SDR sent would be sent
    straight back to it.

    CHOICE (on_set, labels) -- sCTkDialSelector, one position per label, the
    labels drawn round it (short ones: "L S M F"); the value beneath says the
    choice in full. Handed the chosen index; set_position() as for RANGE.

    The caption can change -- NR's middle knob says which setting its scheme
    uses.

    Every kind sits in a HOLDER of one size for a given diameter -- the Range
    canvas's, which is the larger -- so knobs side by side keep their
    captions on one line and their values on another.
    """

    def __init__(self, master, caption, on_step=None, on_set=None, span=None,
                 labels=None, diameter=SMALL_KNOB_DIAMETER, column=SMALL_KNOB_COLUMN,
                 widest_label="000", on_double=None, **kwargs):
        super().__init__(master, fg_color="transparent", border_width=0, **kwargs)
        # Every knob of a diameter gets the RANGE canvas's size, flywheel
        # too, so side by side their captions and values line up.
        range_width, range_height = _range_canvas_size(diameter, widest_label)
        holder_width = max(column, range_width)
        self.caption = sCTkLabelTertiary(self, text=caption,
                                         width=holder_width, height=14, anchor="center")
        self.caption.pack(side="top")
        self._on_set = on_set
        self._syncing = False
        holder = sCTkFrame(self, fg_color="transparent", border_width=0,
                           width=holder_width, height=range_height)
        holder.pack(side="top")
        holder.pack_propagate(False)
        backdrop = _backdrop_colour(self)
        self.kind = "choice" if labels else ("range" if span is not None else "step")
        if labels:
            # Placed as a Range knob's end labels are -- on the arc's
            # diagonals -- so the same canvas holds them.
            self.is_range = True            # set_position applies
            self._span = (0, len(labels) - 1)
            width, height = range_width, range_height
            self.dial = sCTkDialSelector(
                holder, labels=list(labels), arc_angle=270,
                knob_diameter=diameter, width=width, height=height,
                fg_color=backdrop, label_font=RANGE_KNOB_LABEL_FONT,
                command=self._on_range)
        elif span is not None:
            self.is_range = True
            self._span = (int(span[0]), int(span[1]))
            width, height = range_width, range_height
            # Two divisions: a tick and a label at each end, nothing between
            # -- the numbers between are what the value beneath is for.
            self.dial = sCTkDialRange(
                holder, from_=self._span[0], to=self._span[1], divisions=2,
                knob_diameter=diameter, width=width, height=height,
                fg_color=backdrop, label_font=RANGE_KNOB_LABEL_FONT,
                command=self._on_range)
        else:
            self.is_range = False
            width = height = diameter + 6
            self.dial = sCTkDialContinuous(
                holder, divisions=12, knob_diameter=diameter,
                width=width, height=height,
                fg_color=backdrop,
                command=on_step,
                left_click_callback=lambda: on_step(-1),
                right_click_callback=lambda: on_step(+1))
        # The canvas size is applied through configure(), which takes an
        # explicit width and height as given. The constructor sizes the
        # canvas for the knob plus a generous label margin -- 110px round a
        # 30px knob -- which is right for a dial laid out in the Designer and
        # too big here.
        self.dial.configure(width=width, height=height)
        if on_double is not None:
            # The dial's own double-click; it hands back the dial.
            self.dial.configure(double_click_command=lambda dial: on_double())
        self.dial.pack(expand=True)          # centred in the holder
        # FIX: Tertiary, not Primary. With no font of its own the Primary
        # tier drew the value larger than the knob it belongs to.
        self.value = sCTkLabelTertiary(self, text="",
                                      width=holder_width, height=14, anchor="center")
        self.value.pack(side="top")
        # state() repaints -- called only when it changes, as the tuning
        # dial's is (see RolePanel).
        self._state = None
        self.set_live(False)

    def _on_range(self, value):
        if not self._syncing and self._on_set is not None:
            self._on_set(value)

    def set_span(self, low, high):
        """A RANGE knob's ends -- redrawn only when they change."""
        span = (int(low), int(high))
        if self.kind == "range" and span != self._span:
            self._span = span
            self.dial.configure(from_=span[0], to=span[1])

    def set_position(self, value):
        """Moves a RANGE knob's pointer to a value, without reporting it."""
        if not self.is_range or value is None:
            return
        self._syncing = True
        try:
            self.dial.set(int(round(float(value))))
        finally:
            self._syncing = False

    def set_live(self, live):
        wanted = "normal" if live else "disabled"
        if wanted != self._state:
            self._state = wanted
            self.dial.state(wanted)

    def show(self, text):
        self.value.configure(text=text)

    def set_caption(self, text):
        self.caption.configure(text=text)


class HoverNote:
    """
    FIX (2026-11-06): a short note shown under a widget while the pointer
    rests on it -- the app had none. A borderless sCTkToplevel with one
    tertiary label, so it takes the theme like everything else; shown after
    HOVER_DELAY_MS and gone as the pointer leaves or the widget is pressed.
    """
    HOVER_DELAY_MS = 600

    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self._timer = self._window = None
        widget.bind("<Enter>", self._arm, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _arm(self, _event=None):
        self._cancel()
        self._timer = self.widget.after(self.HOVER_DELAY_MS, self._show)

    def _cancel(self):
        if self._timer is not None:
            try:
                self.widget.after_cancel(self._timer)
            except Exception:
                pass
            self._timer = None

    def _show(self):
        self._timer = None
        if self._window is not None or not self.widget.winfo_exists():
            return
        window = sCTkToplevel(self.widget)
        # FIX (2026-11-06): it never showed on the Mac. An overrideredirect
        # window made after the main one opens BEHIND it there, so the note
        # was drawn out of sight. Given the Mac's help-window style (what
        # IDLE's tooltips use: floats on top, takes no focus), placed, then
        # raised and kept on top.
        try:
            window.tk.call("::tk::unsupported::MacWindowStyle", "style",
                           window._w, "help", "noActivates")
        except Exception:
            pass                                      # not a Mac
        window.overrideredirect(True)
        sCTkLabelTertiary(window, text=self.text, justify="left",
                          wraplength=320).pack(padx=8, pady=6)
        window.geometry(f"+{self.widget.winfo_rootx()}"
                        f"+{self.widget.winfo_rooty() + self.widget.winfo_height() + 4}")
        try:
            window.attributes("-topmost", True)
        except Exception:
            pass
        window.lift()
        self._window = window

    def _hide(self, _event=None):
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None


class AidPopup(sCTkToplevel):
    """
    One listening aid's controls -- AGC, NR, ... -- in a small window of its
    own, opened by the arrow beside its lamp.

    WHY A WINDOW. The controls behind a function differ from SDR to SDR, in
    names as well as number, and are shown in each SDR's own terms rather
    than mapped onto one invented set. The lamps, which are the same for
    every SDR, stay on the Operate tab; these open on demand, so they cost
    the tab no height.

    OPEN AND CLOSE. It opens under its lamp and closes on Escape or a click
    elsewhere -- a quick adjustment stays quick. PINNED, it stays until
    closed, can be dragged anywhere, and is reopened where it was on the
    next start; several can be pinned at once. One per function: opening an
    open one brings it forward.

    The controls in it are the application's -- built by
    _build_aid_content, updated like everything else -- and registered
    while it is open, so a closed one is simply not updated.
    """

    def __init__(self, app, key, label, position=None):
        super().__init__(app)
        self.app, self.key, self.label = app, key, label
        self.pinned = False
        self._closing = False
        self.title(label)
        self.transient(app)
        self.resizable(False, False)
        # A themed body, so the knobs find a real colour behind them.
        body = sCTkFrame(self, border_width=0)
        body.pack(fill="both", expand=True)
        top = sCTkFrame(body, fg_color="transparent", border_width=0)
        top.pack(fill="x", padx=8, pady=(6, 0))
        # FIX: Tertiary -- with no font of its own the Secondary tier drew
        # the heading larger than the small pop-up it names.
        self.heading = sCTkLabelTertiary(top, text=label)
        self.heading.pack(side="left")
        # Secondary, for its pressed look -- pressed while pinned.
        self.pin_button = sCTkButtonSecondary(top, text="pin", width=44, height=22, command=self.toggle_pin)
        self.pin_button.pack(side="right")
        self.content = sCTkFrame(body, fg_color="transparent", border_width=0)
        self.content.pack(padx=8, pady=(4, 8))
        if position:
            self.geometry(position)
        self.bind("<Escape>", lambda event: self.close())
        self.bind("<FocusOut>", self._focus_out)
        self.bind("<Configure>", self._moved)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._move_timer = None

    def place_under(self, widget):
        """Opens just below a widget -- the lamp's arrow."""
        widget.update_idletasks()
        self.geometry(f"+{widget.winfo_rootx()}"
                      f"+{widget.winfo_rooty() + widget.winfo_height() + 4}")

    def bring_forward(self):
        self.deiconify()
        self.lift()
        self.after(50, self._take_focus)

    def _take_focus(self):
        if not self._closing and self.winfo_exists():
            self.focus_force()

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.pin_button.configure(text="pinned" if self.pinned else "pin")
        self.pin_button.set_pressed(self.pinned)
        self.app._save_pinned_aids()

    def _focus_out(self, event):
        # FocusOut arrives for the window's children too -- a knob taking
        # focus as the pointer enters it. Looked at a moment later: closed
        # only if focus has gone outside this window altogether.
        if not self.pinned and not self._closing:
            self.after(200, self._close_if_elsewhere)

    def _close_if_elsewhere(self):
        if self.pinned or self._closing or not self.winfo_exists():
            return
        try:
            focus = self.focus_get()
        except Exception:
            focus = None
        if focus is None or not str(focus).startswith(str(self)):
            self.close()

    def _moved(self, event):
        # Saved when a pinned one stops moving, as the main window's is.
        if self.pinned and event.widget is self:
            if self._move_timer is not None:
                self.after_cancel(self._move_timer)
            self._move_timer = self.after(500, self.app._save_pinned_aids)

    def close(self):
        if self._closing:
            return
        self._closing = True
        self.app._aid_closed(self.key)
        self.destroy()


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
        # FIX (2026-11-11): 2 / 8, not 1 / 6 -- see the settings table.
        super().__init__(master, border_width=2, corner_radius=8, **kw)
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

        # THE DIAL RUNS THE FULL HEIGHT OF THE PANEL, beside the header as
        # well as the readout. It was in the body, under the header, and as
        # the tallest thing there it set the body's height -- leaving an
        # empty band under the frequency, with the header line stacked on
        # top of that. Now the header and readout share the dial's height
        # rather than adding to it.
        #
        # Built and packed FIRST so it claims the right-hand side before the
        # header and body take what is left. fg_color transparent so the knob
        # sits on the panel's own colour -- the dial's theme block carries
        # its own background, which reads as a darker rectangle otherwise.
        # width and height are the CANVAS, knob_diameter the knob drawn on
        # it; set together, with just enough margin for the tick marks the
        # dial draws outside the knob.
        self.dial = sCTkDialContinuous(
            self, divisions=24, knob_diameter=KNOB_DIAMETER,
            width=KNOB_DIAMETER + 10, height=KNOB_DIAMETER + 10,
            fg_color="transparent",
            command=self._on_turn,
            left_click_callback=lambda: self._click_step(-1),
            right_click_callback=lambda: self._click_step(+1),
            double_click_command=lambda d: d.set_pressed(True),
            shift_double_click_command=lambda d: d.set_pressed(False))
        # FIX: the canvas size through configure(), as the small knobs do.
        # The constructor takes width and height only as a starting point and
        # sizes the canvas for the knob plus a generous label margin -- room
        # this dial has no labels to fill. That margin made the canvas, and
        # so the whole panel, much taller than the frequency beside it: an
        # empty band under the readout that no window height could remove,
        # and a panel whose border was cut off when the window was shortened.
        self.dial.configure(width=KNOB_DIAMETER + 10, height=KNOB_DIAMETER + 10)
        self.dial.pack(side="right", padx=(4, 6), pady=2)

        header = sCTkFrame(self, fg_color="transparent", border_width=0)
        header.pack(fill="x", padx=8, pady=(5, 0))

        # FIX (2026-11-09): RX AND TX STAND OUT (Mark). In split the receive
        # VFO can be B and transmit A -- the reverse of the firmware's usual
        # A receives, B transmits -- and a small "rx"/"tx" did not say which
        # panel was which strongly enough. A primary button in the buttons'
        # blue, capitals, with no command and no hover: a badge, not a control.
        self.role_label = sCTkButtonPrimary(
            header, text=role.upper(), width=36, height=22,
            hover=False, command=None)
        self.role_label.pack(side="left")

        self.vfo_label = sCTkLabelTertiary(header, text="VFO A")
        self.vfo_label.pack(side="left", padx=(8, 0))

        if role == "tx":
            # A transmit indicator, not a control. It belongs on the TX
            # frequency because that is the thing it is telling you about:
            # this number is going out right now.
            self.led = sCTkLabelPrimary(header, text=" ON AIR ",
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
            self.standby = sCTkLabelSecondary(header, text="")
            self.standby.pack(side="right")
            self._standby_shown = True

        body = sCTkFrame(self, fg_color="transparent", border_width=0)
        body.pack(fill="x", padx=8, pady=(0, 5))

        # The readout and its note. The dial was packed first, on the panel
        # itself, so it always gets its fixed size; the readout is the one
        # that gives way.
        left = sCTkFrame(body, fg_color="transparent", border_width=0)

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

        # THE PANEL'S OWN BUTTONS, under the frequency, at the Split
        # button's size, with the note beside them. RX: RIT and Lock -- the
        # frequency they act on. Lock freezes both panels, but receive is
        # where you tune; the note under each frequency says "locked" too.
        # Pressed while on (see refresh). TX: TX off -- transmit inhibit,
        # the control you want when something is wrong (a bad SWR, the wrong
        # antenna, a neighbour on frequency) -- in the ALARM colour while on,
        # since it means the rig will not transmit.
        under = sCTkFrame(left, fg_color="transparent", border_width=0)
        under.pack(anchor="w", pady=(2, 0))
        # FIX: no fonts on sCTk widgets in this panel, the knobs or the aid
        # pop-ups -- the theme's tiers set them (see _build_operate).
        size = dict(width=60, height=26)
        if role == "rx":
            app._toggles["rit"] = sCTkButtonSecondary(
                under, text="RIT", command=lambda: app._toggle("rit"), **size)
            app._toggles["rit"].pack(side="left", padx=(0, 4))
            app._toggles["locked"] = sCTkButtonSecondary(
                under, text="Lock", command=lambda: app._toggle("locked"), **size)
            app._toggles["locked"].pack(side="left", padx=(0, 4))
        else:
            app.tx_off_button = sCTkButtonSecondary(
                under, text="TX off", command=lambda: app._toggle("tx_inhibit"), **size)
            app.tx_off_button.pack(side="left", padx=(0, 4))
            # FIX (2026-11-06): what it really is. KD8CEC's TX OFF keeps the
            # T/R relays in receive and lets the rest of transmit happen --
            # its startTx() skips only digitalWrite(TX_RX, 1) -- so it is a
            # practice mode: checked on the rig, no relay click with it on.
            HoverNote(app.tx_off_button,
                      "Practice mode: the rig keys and the sidetone sounds, "
                      "but its relays stay in receive -- nothing goes to the "
                      "antenna. (KD8CEC's TX OFF.)")
        self.note = sCTkLabelTertiary(under, text="")
        self.note.pack(side="left", padx=(4, 0))

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
        self.vfo_label.configure(text=f"VFO {radio.role_vfo(self._role).upper()}")

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

        # THE APPLICATION MENU'S QUIT, on macOS. Tk handles that menu itself
        # and answers it with Tcl's own `exit`, which tears the interpreter
        # down where it stands -- so Python's atexit and every `finally`
        # never run. Quitting from the menu therefore left the rig's port
        # open and an SDR this application had started still running, while
        # closing the window behaved perfectly.
        #
        # ::tk::mac::Quit is Tk's hook for that menu item. Elsewhere it does
        # not exist, and createcommand simply defines something nothing
        # calls.
        try:
            self.createcommand("::tk::mac::Quit", self._on_close)
        except Exception:
            pass

        # Also saved as it changes -- see _on_configure. Closing cleanly is
        # not something an IDE's stop button does.
        self._geometry_timer = None
        self.bind("<Configure>", self._on_configure)

        # CONFIGURATION FIRST. It reads ~/.ubitx_cec_desktop/settings.json --
        # see app_paths -- and
        # the SDR controller reads it in its own constructor, for the server
        # address and the filter defaults. It is a module-level global because
        # that is how globalvars has always published it, and the controller
        # expects it there.
        gv.config = ConfigurationManager(self)
        # FIX (2026-11-10): THE SAVED APPEARANCE, before anything is built, so
        # the window is drawn once in it -- see _set_appearance.
        self._set_appearance(self._appearance_saved(), save=False)

        # The channel sets, owned here -- see channel_sets.py. The Channels
        # tab edits them and the scanner will read them; nothing else keeps a
        # copy.
        self.channel_sets = ChannelSets()
        # FIX (2026-11-06): WWV, CW calling and FT8 sets for an operator with
        # none yet -- once; see ChannelSets.add_starter_sets.
        added = self.channel_sets.add_starter_sets()
        if added:
            print(f"[channels] starter sets added: {', '.join(added)}")

        # on_change is _model_changed rather than refresh: the view redraws,
        # and the SDR is brought into step, from the same notification. schedule
        # is `after`, so a burst of reports becomes one of each. See
        # RadioModel.changed().
        self.model = RadioModel(on_change=self._model_changed,
                                schedule=self.after)
        # THE RIG'S PORT COMES FROM THE SETTINGS, and opening it may fail:
        # not plugged in, a different adapter, the radio switched off, a
        # bridge address that is wrong. None of those should stop the
        # application -- it starts on the Setup tab instead, saying which.
        #
        # Until a port opens, commands go to NullRig and do nothing, so every
        # control works without knowing whether there is a radio.
        self.connection = NullRig()
        self.rig_stream = None          # the open serial port, to be closed
        self.rig_state = "unchosen"     # unchosen | failed | silent | connected
        self.rig_note = "no port chosen yet"
        self._open_rig()

        # The SDR, as a second transport beside the rig. Built now so the model's
        # notifications can reach it, but not CONNECTED until the interface
        # exists to report whether that worked -- see _start_sdr.
        self.sdr = SDR_Link(self, self.model, self.connection)
        self.sdr.on_status = self._show_sdr_status
        self.sdr.on_audio = self._sdr_audio_changed
        self.sdr.on_signal = self._update_s_meter
        self.sdr.on_decoded = self._decoded_text
        self.sdr.on_needs_force = self._ask_to_force_sdr
        self.sdr.on_needs_closing = self._ask_to_close_their_sdr

        # The scanner, run by the application rather than the SDR -- see
        # scanner.py. It tunes the rig; the SDR follows the rig as ever.
        self.scanner = Scanner(self, self.model, self.connection)
        self.scanner.on_step = self._scan_reached
        self.scanner.on_stop = self._scan_stopped
        self.scanner.on_hold = self._scan_held         # FIX (2026-11-06)

        #   initialize radio connection
        #
        # The model holds starting values -- a frequency, the firmware
        # string, the callsign -- which the rig's own reports replace a
        # moment later. They are NOT evidence that a rig is there: only
        # model.reports says that. See _check_rig_answered.
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
        self._toggles = {}
        # What each latched control last showed -- see refresh.
        self._toggle_shown = {}

        # refresh() touches widgets from every tab, and sCTkSpinbox.set()
        # invokes its command -- so setting an initial value while building
        # calls back into a interface that does not exist yet. The flag keeps
        # that harmless rather than relying on construction order.
        self._ready = False

        # WHICH RECEIVER YOU ARE LISTENING THROUGH -- "SDR" or "Rig". An
        # application choice, not something the rig reports, so it lives
        # here rather than in the model. It decides what Mute silences and
        # whether volume does anything. Starts on SDR if an SDR is switched
        # on in the settings, since that is how the station is set up.
        self._listen_source = "SDR" if gv.config.sdr_enabled() else "Rig"
        self._att_last = 0          # FIX (2026-11-10): ATT's level to switch on at
        # Whether the OPERATOR chose that, as against it being where the
        # application started. An SDR connecting later takes over the
        # listening -- but never over a choice somebody made.
        self._listen_chosen = False
        # The SDR's mute is NOT kept here: SDR_Link.muted reports it -- the
        # SDR's own mute where it has one, which can also be changed in the
        # SDR itself, and only otherwise the computer's.
        # state() repaints, so it is called only when the value changes.
        self._offset_state = None

        self.notebook = sCTkNotebook(self, side="left", tab_width=30,
                                     command=self._on_tab,
                                     tab_style="rounded",
                                     text_orientation="auto",
                                     show_page_border=True)
        # Vertical margins kept small: the window's height is better left to
        # the SDR's window beside it.
        self.notebook.pack(expand=True, fill="both", padx=10, pady=4)

        self._build_operate(self.notebook.add("Operate"))
        self._build_rx(self.notebook.add("RX"))
        self._build_channels(self.notebook.add("Channels"))
        self._build_cw(self.notebook.add("CW"))
        self._build_setup(self.notebook.add("Setup"))

        # Initial values go in AFTER every tab exists, for the reason above.
        self._ready = True
        self.band_picker.set(self.model.band_name() or self.OFF_BAND)
        # self.band_picker.set(BANDS[self.model.band_index][0])
        self.mode_picker.set(self.model.mode)

        self.refresh()
        self._tick()

        # Idle rather than immediate: the window should be up before a
        # connection attempt that can take a moment when the SDR is not there.
        self.after_idle(self._start_sdr)

        # NOTHING TO TALK TO: start on Setup, which is where it is fixed.
        # Better than a working-looking panel wired to nothing -- and better
        # than the traceback a missing port used to cause before any window
        # existed.
        if self.rig_state != "connected":
            self.after_idle(lambda: self.notebook.set("Setup"))

    # -- the rig's connection ----------------------------------------------
    def _open_rig(self):
        """
        Opens the rig's port, as the settings name it.

        THREE THINGS CAN GO WRONG, and each has its own words, because each
        needs a different thing done about it:

          * nothing chosen, or an address that cannot be read at all;
          * the port will not open -- not plugged in, held by another
            program, or permissions;
          * it opens and the rig never answers, which is what "the adapter is
            plugged in but the radio is switched off" looks like. That one is
            checked a moment later -- see _check_rig_answered -- because the
            link asks the rig for everything as it starts, so silence is the
            evidence.
        """
        setting = gv.config.get_rig_port()
        kind, value, problem = parse_rig_port(setting)
        if not kind:
            self.rig_state, self.rig_note = "unchosen", problem
            return False

        self._close_rig()               # never two streams on one port
        try:
            stream = open_rig_port(value, gv.config.get_rig_baud())
        except Exception as err:
            self.rig_state = "failed"
            self.rig_note = f"{value} would not open -- {err}"
            print(f"[rig] {self.rig_note}")
            return False

        self.rig_stream = stream
        self.connection = uBITX_Link(self, stream, self.model, 250)
        # FIX (2026-11-06): the operator's command headroom and timings --
        # Machine settings.
        self.connection.command_headroom = self._headroom_setting()
        ubitx_link.apply_timing(self._timing_setting())
        self.rig_state, self.rig_note = "connected", f"connected on {value}"
        print(f"[rig] {self.rig_note}")
        # Give the rig time to answer the startup dump before believing it.
        self._report_retries = 0
        self._answer_waited_ms = 0
        self._connected_note = self.rig_note
        self.after(RIG_ANSWER_MS, self._check_rig_answered)
        return True

    def _close_rig(self):
        """
        Stops the reader and CLOSES THE PORT.

        Closing matters more than it looks. The rig sends its 26 values when
        it boots, and it boots because opening the port pulls DTR -- so a
        port left open from a previous attempt is not reset when it is opened
        again, no values arrive, and the link waits five seconds before
        asking whether the radio is switched on. Connecting twice in one
        session did exactly that.
        """
        if self.connection.reader_process_id is not None:
            try:
                self.after_cancel(self.connection.reader_process_id)
            except Exception:
                pass
        self.connection = NullRig()
        if self.rig_stream is not None:
            try:
                self.rig_stream.close()
            except Exception:
                pass
            self.rig_stream = None

    def _check_rig_answered(self):
        """
        Did anything come back? The link asks the rig for every value as it
        starts, so a report by now means the radio is there.

        COUNTED REPORTS, not the values themselves: the model SEEDS a
        frequency, a firmware string and the callsign, so reading those would
        call a switched-off radio "answering" -- which is the very case this
        exists to catch.
        """
        if self.rig_state != "connected":
            return
        if self.model.reports:
            # It is answering. Say which of the values the interface needs
            # have not arrived -- the rig sends them as it boots and the
            # reader takes what comes, so a gap is something to ask for
            # rather than an error.
            missing = self.connection.check_expected_reports()
            # FIX (2026-11-06): AND ASK FOR THEM, by restarting the rig. It
            # does not answer a request for one value -- it sends them all as
            # it boots -- so a restart is the only way to ask. A report torn
            # in the startup burst (bytes skipped, a frame dropped) is the
            # usual cause, and a second burst fills it in: values that
            # arrived the first time stay counted, so only what is still
            # missing matters. Twice at most, then it is said and left. Not
            # while transmitting: a restart drops the rig out of it.
            if (missing and self._report_retries < RIG_REPORT_RETRIES
                    and not self.model.transmitting):
                self._report_retries += 1
                print(f"[rig] restarting the rig for the missing values "
                      f"({self._report_retries} of {RIG_REPORT_RETRIES})")
                self.connection.restart_rig()
                self.after(RIG_ANSWER_MS, self._check_rig_answered)
            elif missing:
                print("[rig] still missing after restarting -- shown as not known")
            return
        # FIX (2026-11-06): NOT SILENT WHILE IT IS STILL BOOTING. The rig
        # holds its line low as it starts, and took longer than this check's
        # 2.5 s on the station -- so it was called silent, the backup dialog
        # said "no radio", and the missing-values restart never ran. Bytes
        # arriving, even zeros, mean wait; up to RIG_ANSWER_MAX_MS.
        self._answer_waited_ms += RIG_ANSWER_MS
        if (getattr(self.connection, "bytes_seen", 0)
                and self._answer_waited_ms < RIG_ANSWER_MAX_MS):
            print(f"[rig] the rig is still starting -- waiting "
                  f"({self._answer_waited_ms / 1000:.1f} s so far)")
            self.after(RIG_ANSWER_MS, self._check_rig_answered)
            return
        self.rig_state = "silent"
        self.rig_note = ("the port opened but the radio is not answering -- "
                         "is it switched on?")
        print(f"[rig] {self.rig_note}")
        self._show_rig_status()
        self.notebook.set("Setup")

    def _rig_answered_late(self):
        """
        FIX (2026-11-06): A RIG CALLED SILENT THAT ANSWERS AFTER ALL is
        connected -- the first report puts it right, rather than the window
        going on saying "no radio" over a working rig. Its values are checked
        as on a normal connect, the missing-values restart included.
        """
        if self.rig_state == "silent" and self.model.reports:
            self.rig_state = "connected"
            self.rig_note = getattr(self, "_connected_note", "connected")
            print(f"[rig] the rig answered after all -- {self.rig_note}")
            self._show_rig_status()
            self.after(RIG_ANSWER_MS, self._check_rig_answered)

    def _show_rig_status(self):
        """Puts the connection's state on the Setup page and the status line."""
        box = getattr(self, "radio_box", None)
        if box is not None:
            self._group_note(box, self.rig_note)

    # -- window position ---------------------------------------------------
    def _remembered_geometry(self):
        """Where it was last time, or a sensible default."""
        try:
            with open(GEOMETRY_FILE) as handle:
                return json.load(handle)["geometry"]
        except Exception:
            # A first start -- nothing remembered yet. Size only: where the
            # window belongs depends on where the SDR's window sits on each
            # screen, so the window manager places it.
            #
            # macOS: 1470x364 at +0+33, MEASURED -- the size the finished layout was
            # set to by hand on a 13" MacBook Air (1470 points wide), read
            # back from the geometry file. Two ten-digit readouts at 56pt
            # plus their dials do not fit in much less width, and the first
            # symptom of trying is a dial squeezed to nothing rather than
            # anything that says "too narrow".
            #
            # Elsewhere: the earlier estimate, until someone measures one.
            # Fonts and window borders differ enough that the Mac figure may
            # clip there.
            import sys
            return "1470x364+0+33" if sys.platform == "darwin" else "1440x520"

    def _on_close(self):
        """The window's close button."""
        print("[app] closing")
        self.close_down()
        self.destroy()

    def close_down(self):
        """
        Everything that must happen before this application ends.

        SEPARATE FROM _on_close, AND SAFE TO CALL TWICE, because the window
        can go without the close button being pressed -- and did: none of
        this ran, so the geometry went unsaved, the rig's port was left open
        and the SDR this application had started was left running with no
        word about it. Whatever closes the window, the main loop returns, so
        the end of the program calls this as well.
        """
        if getattr(self, "_closed_down", False):
            return
        self._closed_down = True

        self._save_geometry()
        self._close_rig()
        # An SDR that was already running is the operator's and is left
        # alone; one this application started is closed with it. One call,
        # because stopping the receiver, closing the socket and asking the
        # program to quit have to happen in that order -- see
        # SDR_Link.shutdown().
        self.sdr.shutdown()

    # -- The SDR -------------------------------------------------------------
    def _model_changed(self):
        """
        The model changed: redraw, and bring the SDR into step.

        One notification, two consumers. The SDR follows the MODEL rather than
        being told separately by each handler, so every way the receive
        frequency can change -- the dial, a band change, a split offset, a
        click in the SDR itself coming back from the rig -- reaches it the same
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
        """Connects to the SDR at startup, if it is switched on in the settings."""
        # Put the rig where the listening choice needs it: quiet if the SDR is
        # the receiver, speaking if the rig is. Done now rather than while
        # building, because it sends a command to the rig.
        self._set_listen_source(self._listen_source)
        if not gv.config.sdr_enabled():
            self._show_sdr_status(False)
            return
        # Start the program first if that is wanted -- attaching to one
        # already running, or launching one, which is then ours to close --
        # and keep trying while it comes up, since a freshly started SDR
        # takes seconds to open its remote control.
        self.sdr.start_program()
        self.sdr.connect_when_ready()

    def _reconnect_sdr(self):
        """The status-strip button: try the SDR again."""
        self.sdr_status.configure(text="sdr — connecting…")
        self.update_idletasks()
        self.sdr.connect()

    def _show_sdr_status(self, connected):
        """
        Says whether the SDR is connected -- and, since what it can do is
        only known once it is, sets up everything that depends on that.
        """
        # ALERT COLOURS when there is no SDR to listen to -- chosen but not
        # answering, or not chosen at all. It is a small control at the end of
        # a row, and in the ordinary colours it reads as just another label
        # while half the panel is greyed out and nothing says why.
        #
        # Coloured here rather than by style: the library has no alert button.
        # One would be better -- see TODO.
        if connected:
            self.sdr_status.configure(text="sdr ok")
            self.sdr_status.set_alarm_state(False)
        else:
            chosen = gv.config.sdr_enabled()
            self.sdr_status.configure(
                text="sdr — reconnect" if chosen else "no sdr — choose one")
            self.sdr_status.set_alarm_state(True)

        # What the SDR cannot do is GREYED, not left to fail when pressed.
        self._show_filter_buttons()
        # The listening aids: every lamp repainted afresh, and each open
        # pop-up rebuilt -- another SDR, or another demodulator, has other
        # controls for the same function.
        self._lamp_live.clear()
        self._lamp_states.clear()
        for popup in list(self._popups.values()):
            if popup.winfo_exists():
                self._build_aid_content(popup)
        self._show_lamps()

        # AN SDR THAT CONNECTS BECOMES THE RECEIVER. With no SDR at startup
        # -- which is how a new settings file begins -- the application comes
        # up listening to the rig, and choosing an SDR on Setup afterwards
        # left it there: the volume slider stayed greyed, because it belongs
        # to whichever receiver you are listening through, and everything
        # else about the SDR worked. Connecting one is as clear a statement
        # as pressing the button.
        #
        # NOT over a choice the operator made, though. Once they have picked
        # a receiver themselves, reconnecting never moves it.
        if connected and self._listen_source == "Rig" and not self._listen_chosen:
            self.receiver_picker.set("SDR")
            self._set_listen_source("SDR")
        elif connected:
            # FIX: an SDR connecting while you listen through the rig is
            # silenced -- see _sdr_quiet_for_rig. A fresh connection, so
            # whatever was remembered from the last one is forgotten first.
            self._sdr_muted_before = None
            self._sdr_quiet_for_rig()

        self.audio_note.configure(
            text="Listening through the SDR quiets the rig's speaker. "
                 "Double-click the volume knob to mute. "
                 f"{self.sdr.audio_description()} Listening through the rig, "
                 "the level is its front-panel knob.")

        self._sdr_audio_changed()

    # The listening aids: each one's key, and the text on its lamp.
    AIDS_LAMPS = (("agc", "AGC"), ("nr", "NR"), ("notch", "Notch"),
                  ("squelch", "SQL"), ("nb", "NB"), ("cw", "CW"),
                  ("decode", "DEC"))

    def _is_cw(self):
        """Whether the receiving VFO is in a CW mode."""
        return str(self.model.mode_of(self.model.rx_vfo)).upper().startswith("CW")

    def _dsp_step(self, function, index, clicks):
        """
        A FLYWHEEL knob clicked or turned: one dial step per click, in the
        adjustment's own units -- the SSB demodulator's AGC time constant
        doubles or halves -- shown at once and sent when the knob settles.
        Stepped from what was last SHOWN, so a quick run of clicks adds up
        rather than each starting again from the SDR's value.
        """
        names = self.sdr.dsp_knob_names(function)
        if index >= len(names):
            return
        name = names[index]
        if not self.sdr.dsp_adjustable(function, name):
            return
        low, high = self.sdr.dsp_range(function, name)
        key = (function, name)
        shown = self._knob_values.get(key, self.sdr.dsp_setting(function, name))
        value = max(low, min(high, shown + clicks))
        self._knob_values[key] = value
        self.dsp_knobs[function][index].show(
            self.sdr.dsp_setting_text(function, name, value))
        self.sdr.set_dsp_setting(function, name, value)

    def _dsp_set(self, function, index, value):
        """
        A RANGE or CHOICE knob moved to a value: shown at once, sent when it
        settles. The knob itself keeps the position, so there is nothing to
        step from.
        """
        names = self.sdr.dsp_knob_names(function)
        if index >= len(names):
            return
        name = names[index]
        if not self.sdr.dsp_adjustable(function, name):
            return
        self._knob_values[(function, name)] = value
        self.dsp_knobs[function][index].show(self.sdr.dsp_setting_text(function, name, value))
        self.sdr.set_dsp_setting(function, name, value)

    def _lamp_on(self, key):
        """Whether a function is on -- as the SDR link describes it."""
        return bool(self.sdr.dsp_on(key))

    def _aid_live(self, key):
        """Whether a function can be used just now -- see SDR_Link.dsp_blocked.
        FIX: and not while the rig is locked -- see _show_lock."""
        return not self.model.locked and not self.sdr.dsp_blocked(key)

    def _show_lamps(self):
        """
        The lamps -- pressed while their function is on, plain while off,
        greyed where the SDR has none -- and, in any open pop-up, the switch
        to match. Each is repainted only when it changes.

        A lamp is made live BEFORE it is pressed: the button ignores
        set_pressed() while disabled, so a lamp coming back is pressed afresh.
        """
        for key, lamp in getattr(self, "aids_lamps", {}).items():
            live = self._aid_live(key)
            if live != self._lamp_live.get(key):
                self._lamp_live[key] = live
                lamp.state("normal" if live else "disabled")
                self._lamp_states.pop(key, None)
            on = self._lamp_on(key)
            if on != self._lamp_states.get(key):
                self._lamp_states[key] = on
                lamp.set_pressed(on)
                switch = self.dsp_switches.get(key)
                if switch is not None:
                    switch.select() if on else switch.deselect()
            # An open pop-up's switch, action buttons and note, on a change.
            if key in self._dsp_notes and live != self._switch_states.get(key):
                self._switch_states[key] = live
                switch = self.dsp_switches.get(key)
                if switch is not None:
                    switch.state("normal" if live else "disabled")
                self._show_dsp_note(key)
            buttons = self._aid_actions.get(key)
            if buttons:
                for button, (_, _, enabled) in zip(buttons, self.sdr.dsp_actions(key)):
                    wanted = "normal" if live and enabled else "disabled"
                    if button.state() != wanted:
                        button.state(wanted)

    def _lamp_clicked(self, key):
        """
        A lamp clicked: whatever the SDR link says clicking it does -- a
        switched function flips; a squelch with no switch opens or closes
        (see SDR_Link.toggle_dsp). Its knobs are read afresh after.
        """
        if not self._aid_live(key):
            return
        self.sdr.toggle_dsp(key)
        self._forget_knob_values(key)
        self._draw_dsp_knobs()
        self.refresh()

    def _aid_action(self, key, action):
        """One of a function's own buttons -- Gqrx's A or R -- then its knobs afresh."""
        action()
        self._forget_knob_values(key)
        self._draw_dsp_knobs()
        self.refresh()

    def _forget_knob_values(self, function):
        """A function's knobs shown from the SDR again, not from what was last turned."""
        for key in [k for k in self._knob_values
                    if isinstance(k, tuple) and k[0] == function]:
            del self._knob_values[key]

    def _show_dsp_note(self, key):
        """A pop-up's note: why its function cannot be used just now, or nothing."""
        note = self._dsp_notes.get(key)
        if note is None:
            return
        text = (self.LOCKED_NOTE if self.model.locked
                else self.sdr.dsp_blocked(key) or "")
        note.configure(text=text)
        if text:
            note.pack(side="left", padx=(4, 0))
        else:
            note.pack_forget()

    def _dsp_switched(self, function, value):
        """
        A function's switch moved: the function set to what the switch now
        shows -- `value`, as sCTkSwitch passes it (1 on, 0 off). Its lamp is
        pressed while on -- see _show_lamps.
        """
        on = value not in (0, False, "0", "off", "", None)
        if not self.model.locked:           # FIX: see _show_lock
            self.sdr.set_dsp(function, on)
        # The switch put back to what the SDR reports: if it refused the
        # change, the switch would otherwise stay where the click left it.
        switch = self.dsp_switches[function]
        switch.select() if self.sdr.dsp_on(function) else switch.deselect()
        self.refresh()

    def _open_aid(self, key, position=None, pinned=False):
        """
        The arrow beside a lamp: that function's pop-up, opened under it --
        or, if already open, brought forward. See AidPopup.
        """
        popup = self._popups.get(key)
        if popup is not None and popup.winfo_exists():
            popup.bring_forward()
            return popup
        label = dict(self.AIDS_LAMPS)[key]
        popup = AidPopup(self, key, f"{label} \u2014 {self.sdr.profile.name}", position)
        self._popups[key] = popup
        self._build_aid_content(popup)
        if position is None:
            popup.place_under(self._lamp_arrows[key])
        if pinned:
            popup.toggle_pin()
        else:
            popup.bring_forward()
        return popup

    def _forget_aid_controls(self, key):
        """A pop-up's controls no longer on screen: nothing updates them."""
        for table in (self.dsp_switches, self.dsp_knobs, self._knob_boxes,
                      self._dsp_notes, self._knob_layout, self._switch_states,
                      self._aid_actions):
            table.pop(key, None)

    def _build_aid_content(self, popup):
        """
        A pop-up's controls, built from what the SDR offers for that function
        -- and built again whenever it connects, since another SDR, or
        another demodulator, has other controls. Registered, so the rest of
        the application updates them as it does everything else.
        """
        key = popup.key
        self._forget_aid_controls(key)
        for child in popup.content.winfo_children():
            child.destroy()
        popup.title(f"{dict(self.AIDS_LAMPS)[key]} \u2014 {self.sdr.profile.name}")
        popup.heading.configure(text=popup.title())
        page = popup.content

        # WHAT THE SDR LINK DESCRIBES, the same way for every SDR: a switch
        # where the function has one, its knobs, its own buttons where it has
        # any (Gqrx's squelch: A and R, and no switch -- fully open is its
        # "off"), and a note saying why it cannot be used, when it cannot.
        #
        # FIX: sCTkSwitch calls its command WITH the switch's new value
        # (1 or 0) when the command can take one -- and a lambda with a
        # default argument can, so that value arrived as the function's
        # name: KeyError: 1. The value is taken explicitly.
        if self.sdr.dsp_switchable(key):
            switch = sCTkSwitch(page, text="", width=44,
                                command=lambda value, f=key: self._dsp_switched(f, value))
            switch.pack(side="left", padx=(2, 6))
            switch.select() if self._lamp_on(key) else switch.deselect()
            self.dsp_switches[key] = switch
        # 1 x 1, not the default 200 x 200: an EMPTY frame keeps its default
        # size, and the notch's box is empty under WDSP.
        box = sCTkFrame(page, fg_color="transparent", border_width=0,
                        width=1, height=1)
        box.pack(side="left")
        actions = self.sdr.dsp_actions(key)
        if actions:
            column = sCTkFrame(page, fg_color="transparent", border_width=0)
            column.pack(side="left", padx=(4, 0))
            buttons = []
            for label, action, _ in actions:
                button = sCTkButtonSecondary(
                    column, text=label, width=26,
                    command=lambda a=action, f=key: self._aid_action(f, a))
                button.pack(pady=1)
                buttons.append(button)
            self._aid_actions[key] = buttons
        # DEFAULTS: the function's knobs back to the SDR's own defaults
        # (from sdr_controls.json), where they are known. The switch stays
        # as it is.
        if self.sdr.dsp_defaults(key):
            sCTkButtonSecondary(page, text="Defaults", width=62, height=24,
                                command=lambda f=key: self._aid_action(f, lambda: self.sdr.reset_dsp(f))
                                ).pack(side="left", padx=(6, 0))
        note = sCTkLabelTertiary(page, text="",
                                 wraplength=190, justify="left")
        self._knob_boxes[key], self._dsp_notes[key] = box, note
        self.dsp_knobs[key], self._knob_layout[key] = [], None
        self._switch_states.pop(key, None)
        self._draw_dsp_knobs()
        self._show_lamps()
        self._show_dsp_note(key)

    def _aid_closed(self, key):
        self._popups.pop(key, None)
        self._forget_aid_controls(key)
        self._save_pinned_aids()

    def _save_pinned_aids(self):
        """The pinned pop-ups and where they are, for the next start."""
        # Not while they are being reopened: one not yet on screen reports
        # itself at +0+0, and would be remembered there.
        if getattr(self, "_restoring_aids", False):
            return
        pinned = {key: f"+{popup.winfo_x()}+{popup.winfo_y()}"
                  for key, popup in self._popups.items()
                  if popup.pinned and popup.winfo_exists()}
        try:
            with open(PINNED_AIDS_FILE, "w") as handle:
                json.dump(pinned, handle)
        except Exception:
            pass

    def _restore_pinned_aids(self):
        """Reopens the pop-ups left pinned last time, where they were."""
        try:
            with open(PINNED_AIDS_FILE) as handle:
                pinned = json.load(handle)
        except Exception:
            return
        self._restoring_aids = True
        try:
            for key, position in pinned.items():
                if key in dict(self.AIDS_LAMPS):
                    self._open_aid(key, position=position, pinned=True)
        finally:
            self._restoring_aids = False

    def _knob_signature(self, function):
        """What a function's knobs are -- kind, range, labels -- to know when to rebuild."""
        signature = []
        for name in self.sdr.dsp_knob_names(function):
            info = self.sdr.dsp_info(function, name) or {}
            signature.append((info.get("kind"), info.get("low"), info.get("high"),
                              tuple(info.get("short") or ())))
        return tuple(signature)

    def _rebuild_dsp_knobs(self, function):
        """
        A function's knobs, built from what the channel offers -- a CHOICE
        for a choice, a RANGE labelled with its ends, a FLYWHEEL for a stored
        value that is not what is read. Rebuilt only when that changes: on
        connecting to another demodulator, or when the SSB demodulator's NR
        scheme brings a different middle setting.
        """
        signature = self._knob_signature(function)
        if signature == self._knob_layout.get(function):
            return
        self._knob_layout[function] = signature
        for knob in self.dsp_knobs[function]:
            knob.destroy()
        knobs = []
        box = self._knob_boxes[function]
        for index, name in enumerate(self.sdr.dsp_knob_names(function)):
            info = self.sdr.dsp_info(function, name) or {}
            caption, kind = info.get("caption", ""), info.get("kind")
            if kind == "choice":
                short = list(info.get("short") or info.get("labels") or ())
                knob = SmallKnob(box, caption, labels=short,
                                 widest_label=max(short, key=len) if short else "M",
                                 on_set=lambda value, f=function, i=index:
                                 self._dsp_set(f, i, value))
            elif kind == "range":
                low, high = info["low"], info["high"]
                knob = SmallKnob(box, caption, span=(low, high),
                                 widest_label=max(str(low), str(high), key=len),
                                 on_set=lambda value, f=function, i=index:
                                 self._dsp_set(f, i, value))
            else:
                knob = SmallKnob(box, caption,
                                 on_step=lambda clicks, f=function, i=index:
                                 self._dsp_step(f, i, clicks))
            knob.pack(side="left")
            knobs.append(knob)
        self.dsp_knobs[function] = knobs

    def _draw_dsp_knobs(self, from_sdr=False):
        """
        Every function's knobs: rebuilt if what they set has changed, then
        captions, values, live or greyed. `from_sdr` takes the values afresh
        from the SDR -- on connecting, or when changed there -- rather than
        from what the knobs last showed.
        """
        if from_sdr:
            for key in [k for k in self._knob_values if isinstance(k, tuple)]:
                del self._knob_values[key]
        for function in self.dsp_knobs:
            self._rebuild_dsp_knobs(function)
            self._draw_function_knobs(function, self.dsp_knobs[function])

    def _draw_function_knobs(self, function, knobs):
        """One function's knobs: caption, pointer and value, live where settable."""
        for knob, name in zip(knobs, self.sdr.dsp_knob_names(function)):
            info = self.sdr.dsp_info(function, name) or {}
            knob.set_caption(info.get("caption", ""))
            if self.sdr.has_dsp_setting(function, name):
                value = self._knob_values.setdefault(
                    (function, name), self.sdr.dsp_setting(function, name))
                if knob.kind == "range":
                    knob.set_span(*self.sdr.dsp_range(function, name))
                if knob.is_range:
                    knob.set_position(value)
                # Shown either way; turnable only where the SDR takes it --
                # the SSB demodulator's NR scheme is SDRangel's to set.
                knob.set_live(self.sdr.dsp_adjustable(function, name)
                              and not self.model.locked)    # FIX: _show_lock
                knob.show(self.sdr.dsp_setting_text(function, name, value))
            else:
                knob.set_live(False)
                knob.show("")

    def _rf_gain_set(self, value):
        """
        The RF gain knob moved -- a RANGE knob in whole dB (over rigctl, whole
        percent of the SDR's range), so its pointer shows the gain. The hardware takes gain only in its own steps, so the
        SDR link reads the move as a direction and says which step it reaches
        (SDR_Link.rf_gain_toward); the pointer is put there. Shown at once and
        sent when the knob settles.
        """
        if self.sdr.rf_gain_blocked() or self.model.locked:
            return
        shown = self._knob_values.get("rf_gain", self.sdr.rf_gain)
        target = self.sdr.rf_gain_toward(shown, value)
        if target is None:
            return
        self._knob_values["rf_gain"] = target
        self.rf_gain_knob.set_position(target)
        self.rf_gain_knob.show(self.sdr.rf_gain_text(target))
        self.sdr.set_rf_gain(target)

    def _set_rf_gain_note(self, text):
        """RF gain's note: shown beneath the knob with text, removed without."""
        self.rf_gain_note.configure(text=text)
        if text:
            self.rf_gain_note.pack()
        else:
            self.rf_gain_note.pack_forget()

    def _show_rf_gain(self):
        """The RF gain knob: live, or greyed with the SDR link's reason beneath."""
        if self.sdr.has_rf_gain:
            # The span in whole dB, to the top step rounded up -- 0 to 50
            # for a top step of 49.6. Over rigctl, 0 to 100 %.
            bottom, top = self.sdr.rf_gain_range()
            self.rf_gain_knob.set_span(int(bottom), int(-(-top // 1)))
            if self.sdr.rf_gain is not None:
                self._knob_values["rf_gain"] = self.sdr.rf_gain
                self.rf_gain_knob.set_position(self.sdr.rf_gain)
                self.rf_gain_knob.show(self.sdr.rf_gain_text(self.sdr.rf_gain))
        else:
            self._knob_values.pop("rf_gain", None)
            self.rf_gain_knob.show("")
        reason = self.sdr.rf_gain_blocked()
        self.rf_gain_knob.set_live(reason is None and not self.model.locked)
        self._set_rf_gain_note(reason or "")

    # How much decoded text the strip keeps -- more than the widest window
    # shows -- and how much it shows if the line's width cannot be measured.
    DECODE_KEEP_CHARS = 1000
    DECODE_SHOW_CHARS = 110

    def _decoded_text(self, text):
        """Decoded CW arrived: added to the strip's line."""
        self._decode_text = (self._decode_text + text)[-self.DECODE_KEEP_CHARS:]
        self._draw_decoded()

    def _decode_tail(self, text):
        """
        The end of the line that fits the strip at its present width.
        FIX: measured, not counted (2026-11-05). With the theme's proportional
        font in place of Courier, a count from one letter's width left the
        line well short of the right-hand end; now the longest tail whose
        measured width fits is shown. The last DECODE_SHOW_CHARS if the line
        is not yet laid out.
        """
        try:
            font = tkfont.Font(font=self.decode_label._label.cget("font"))
            width = self.decode_label.winfo_width() - 12   # the label's own inset
        except Exception:
            font, width = None, 0
        if font is None or width <= 0 or font.measure("M") * 10 > width:
            return text[-self.DECODE_SHOW_CHARS:]
        if font.measure(text) <= width:
            return text
        lo, hi = 0, len(text)            # text[-lo:] fits; text[-hi:] does not
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if font.measure(text[-mid:]) <= width:
                lo = mid
            else:
                hi = mid
        return text[-lo:] if lo else ""

    def _draw_decoded(self, _event=None):
        """
        FIX: the line starts at the LEFT and fills rightwards, like a teleprinter;
        once it reaches the right-hand end, the oldest text leaves on the left,
        so it scrolls left -- was right-aligned from the first character.
        """
        text = " ".join(self._decode_text.split())
        if self._decode_text[-1:].isspace() and text:
            text += " "                  # a word just ended: keep its gap
        self.decode_label.configure(text=self._decode_tail(text) or " ")

    def _show_decode_strip(self):
        """The decoded-CW strip, on screen only while DEC is on."""
        strip = getattr(self, "decode_strip", None)
        if strip is None:
            return
        on = bool(self.sdr.dsp_on("decode"))
        if on == self._decode_shown:
            return
        self._decode_shown = on
        if on:
            self._decode_text = ""
            self.decode_label.configure(text=" ")
            strip.grid(row=3, column=0, sticky="ew", padx=6, pady=(4, 2))
        else:
            strip.grid_remove()

    def _update_s_meter(self):
        """
        Redraws the S-meter alone -- called for each new signal reading, and
        from refresh().

        FROM WHICHEVER RECEIVER YOU ARE LISTENING THROUGH. Through the SDR,
        its own signal reading where it has one (Gqrx); none for SDR++,
        which cannot report one -- an empty meter rather than a guess.
        Through the rig, the rig's own reading, which arrives once its
        S-meter reports are wired. Silent while transmitting: the meter's
        other half, power and SWR, is the one that matters then.
        """
        # The reading in words too, drawn by the meter on its caption line --
        # the bar says roughly, this exactly. Only where there is a real
        # figure: empty removes it.
        text = ""
        if self.model.transmitting:
            value = 0.0
        elif self._listen_source == "SDR":
            value = self.sdr.s_units() or 0.0
            text = self.sdr.signal_text()
        else:
            value = self.model.s_value
        self.s_meter.set(s_value=value, sig_text=text)

    def _volume_set(self, value):
        """
        The volume knob moved: shown at once, sent when it settles (see
        SDR_Link.set_volume). The level before is kept a moment, so a
        double-click -- whose first click steps the knob -- can put it back.
        """
        if self.model.locked:               # FIX: see _show_lock
            self._volume_shown = None
            self._show_volume()             # the pointer back where it was
            return
        self._volume_before = (time.monotonic(), self._volume_level)
        self._volume_level = value
        self.sdr.set_volume(value)
        self._show_volume()

    def _volume_double(self):
        """
        Double-click on the volume knob: mute, or unmute. Its first click has
        already stepped the knob down one; that step is undone.
        """
        if self.model.locked:               # FIX: see _show_lock
            return
        before = self._volume_before
        if before and time.monotonic() - before[0] < 0.8:
            self._volume_level = before[1]
            self.sdr.set_volume(self._volume_level)
        self._volume_before = None
        self._mute_pressed()
        self._show_volume()

    def _show_volume(self):
        """The volume knob: its level, or "muted". Repainted only on a change."""
        knob = getattr(self, "volume_knob", None)
        if knob is None:
            return
        muted = bool(self.sdr.muted)
        shown = (int(round(self._volume_level)), muted)
        if shown == self._volume_shown:
            return
        self._volume_shown = shown
        knob.set_position(shown[0])
        knob.show("muted" if muted else f"{shown[0]}")

    def _sdr_audio_changed(self):
        """
        The SDR's audio level or mute changed -- in the SDR itself, or by
        connecting. The slider moves to match; set() on a slider does not
        fire its command, so this cannot loop back to the SDR.
        """
        self._volume_before = None
        self._volume_shown = None
        self._volume_level = self.sdr.get_volume()
        self._show_rf_gain()
        self._draw_dsp_knobs(from_sdr=True)
        self.refresh()

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

    # FIX (2026-11-10): "KEEP ON TOP" IS A PREFERENCE (Mark), a switch in
    # Setup's Station group, saved and ON by default -- its button on Operate
    # is now Help. Why it exists at all: a short window over a large one
    # disappears behind it the moment you click the SDR's waterfall.
    PREFERENCES_KEY = "Preferences"

    def _keep_on_top_saved(self):
        try:
            return bool(gv.config.config_data.get(self.PREFERENCES_KEY, {})
                        .get("keep_on_top", True))
        except AttributeError:
            return True

    # FIX (2026-11-10): THE SDR S-METER'S SCALE, in percent, 100 as it was --
    # Setup > SDR settings. Saved with the preferences. See SDR_Link.s_units.
    S_METER_SCALE_RANGE = (0, 200)

    def _s_meter_scale_saved(self):
        try:
            value = int(gv.config.config_data.get(self.PREFERENCES_KEY, {})
                        .get("s_meter_scale_pct", 100))
        except (AttributeError, TypeError, ValueError):
            return 100
        low, high = self.S_METER_SCALE_RANGE
        return max(low, min(high, value))

    def _set_s_meter_scale(self, percent, save=True):
        """Applies the S-meter scale to the SDR's readings; saved unless only applying."""
        low, high = self.S_METER_SCALE_RANGE
        percent = max(low, min(high, int(percent)))
        self.sdr.s_meter_scale = percent / 100.0
        if not save:
            return
        try:
            gv.config.config_data.setdefault(self.PREFERENCES_KEY, {})["s_meter_scale_pct"] = percent
            gv.config.saveConfig()
        except AttributeError:
            pass

    # FIX (2026-11-10): APPEARANCE -- Setup's Station group, saved, "Follow
    # system" by default (Mark). The library's widgets carry light and dark
    # colours and CustomTkinter switches them; "Follow system" is its
    # "system", which follows the OS's own setting as it changes.
    APPEARANCES = {"Dark": "dark", "Light": "light", "Follow system": "system"}
    APPEARANCE_DEFAULT = "Follow system"

    def _appearance_saved(self):
        try:
            choice = (gv.config.config_data.get(self.PREFERENCES_KEY, {})
                      .get("appearance", self.APPEARANCE_DEFAULT))
        except AttributeError:
            return self.APPEARANCE_DEFAULT
        return choice if choice in self.APPEARANCES else self.APPEARANCE_DEFAULT

    def _set_appearance(self, choice, save=True):
        """Dark, Light or Follow system; saved unless only applying it."""
        if choice not in self.APPEARANCES:
            choice = self.APPEARANCE_DEFAULT
        try:
            ctk.set_appearance_mode(self.APPEARANCES[choice])
        except Exception as err:
            print(f"[setup] appearance {choice!r} not applied: {err}")
        if not save:
            return
        try:
            gv.config.config_data.setdefault(self.PREFERENCES_KEY, {})["appearance"] = choice
            gv.config.saveConfig()
        except AttributeError:
            pass

    def _set_keep_on_top(self, wanted, save=True):
        """On top of other windows, or not; saved unless only applying it."""
        wanted = bool(wanted)
        try:
            self.attributes("-topmost", wanted)
        except Exception:
            pass
        if not save:
            return
        try:
            gv.config.config_data.setdefault(self.PREFERENCES_KEY, {})["keep_on_top"] = wanted
            gv.config.saveConfig()
        except AttributeError:
            pass

    # FIX (2026-11-10): HELP, a page shipped beside the program and opened in
    # the browser -- no internet needed (Mark). help/index.html.
    HELP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "help", "index.html")

    def _open_help(self, section=""):
        if not os.path.exists(self.HELP_FILE):
            print(f"[help] not found: {self.HELP_FILE}")
            return
        url = "file://" + os.path.abspath(self.HELP_FILE).replace(os.sep, "/")
        if not url.startswith("file:///"):
            url = url.replace("file://", "file:///", 1)    # Windows: C:/...
        # FIX (2026-11-10): THE BROWSER CAN COME IN FRONT (Mark: help opened
        # behind the app, and with Keep on top nothing could bring it forward).
        # Keep on top is let go while you read, and put back the next time you
        # click into the app -- the preference itself is not changed.
        self._set_keep_on_top(False, save=False)
        self._help_open = True
        self._help_opened_at = time.monotonic()
        if not getattr(self, "_help_focus_bound", False):
            self.bind("<FocusIn>", self._back_from_help, add="+")
            self._help_focus_bound = True
        webbrowser.open(url + (f"#{section}" if section else ""))

    HELP_REFOCUS_S = 1.5

    def _back_from_help(self, _event=None):
        """Back in the app after reading help: Keep on top as you set it."""
        # Focus moving about inside the app while the browser is still
        # starting is not coming back: only after HELP_REFOCUS_S.
        if (getattr(self, "_help_open", False)
                and time.monotonic() - getattr(self, "_help_opened_at", 0) > self.HELP_REFOCUS_S):
            self._help_open = False
            self._set_keep_on_top(self._keep_on_top_saved(), save=False)

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
        # FIX: NO FONTS ON sCTk WIDGETS. The theme's tiers -- Primary,
        # Secondary, Tertiary -- set them; a size given here overrode the
        # theme and drifted from every other window. The decoded-CW strip's
        # Courier went too (2026-11-05) -- its scrolling measures whatever
        # font the label has (see _decode_tail). Two special cases stay, both
        # drawn sizes rather than label tiers: the frequency display's
        # FREQ_FONT_SIZE and the dials' RANGE_KNOB_LABEL_FONT tick labels.
        page.grid_columnconfigure(0, weight=1)
        # Row 5 is empty and takes every spare pixel, which holds the real
        # content at the TOP. Without it the rows share the extra height and
        # the whole panel drifts to the middle as the window grows.
        page.grid_rowconfigure(5, weight=1)

        # The two VFOs -----------------------------------------------------
        vfos = sCTkFrame(page, fg_color="transparent", border_width=0)
        vfos.grid(row=0, column=0, sticky="ew", padx=6, pady=(2, 2))
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

        # Role controls ----------------------------------------------------
        #
        # RECEIVE ON THE LEFT, TRANSMIT ON THE RIGHT. The receive group --
        # filter, the listening aids' lamps, RF gain -- then band and mode,
        # packed together towards the RX panel; the transmit group -- Split,
        # A<->B, A->B, and the offsets -- pinned under the TX panel. The
        # spare width goes between them, so band and mode sit close to what
        # they are mostly changed alongside.
        role_row = sCTkFrame(page, fg_color="transparent", border_width=0)
        role_row.grid(row=2, column=0, sticky="ew", padx=6, pady=(2, 0))

        # DECODED CW, along the bottom below the filter and bandwidth, while
        # DEC is on -- and gone while it is off, so it costs no height the
        # rest of the time. One line, filling from the left and then scrolling left;
        # the decoder sends it in chunks about every three seconds. See
        # SDR_Link._set_decoding.
        # FIX (2026-11-11): 2 / 8, not 1 / 6 -- see the settings table.
        self.decode_strip = sCTkFrame(page, border_width=2, corner_radius=8)
        sCTkLabelTertiary(self.decode_strip, text="DEC").pack(side="left", padx=(8, 6), pady=3)
        self.decode_label = sCTkLabelPrimary(self.decode_strip, text=" ",
                                             anchor="w")
        self.decode_label.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=3)
        # A wider or narrower window holds more or less of the line.
        self.decode_strip.bind("<Configure>", self._draw_decoded, add="+")
        self._decode_text = ""
        self._decode_shown = False
        # Left to right: the lamps, the filter beneath; band over mode, centred
        # between the lamps and the knobs; RF gain and volume, with spare
        # width either side of them; the transmit group, pinned right under
        # the TX panel. Columns 1 and 3 share the spare width equally.
        role_row.grid_columnconfigure(0, weight=0)
        role_row.grid_columnconfigure(1, weight=1)
        role_row.grid_columnconfigure(2, weight=0)
        role_row.grid_columnconfigure(3, weight=1)
        role_row.grid_columnconfigure(4, weight=0)

        # Receive controls, under the receive frequency --------------------
        rx_column = sCTkFrame(role_row, fg_color="transparent", border_width=0)
        rx_column.grid(row=0, column=0, sticky="nw")

        # THE LISTENING AIDS -- AGC, NR, Notch, SQL, NB, CW -- a row of LAMPS.
        #
        # What every SDR shares is that a function exists and is on or off,
        # and the lamp says that the same way for all of them: PRESSED while
        # on -- the button's own held pressed state, coloured by its theme's
        # pressed_map -- plain while off, greyed where the SDR has none.
        # CLICKING THE LAMP SWITCHES IT, the thing done while listening.
        #
        # What differs between SDRs -- the controls behind a function, in
        # that SDR's own terms -- is in a POP-UP, opened by the small arrow
        # beside the lamp: the WDSP receiver's AGC is mode, top, slope and
        # hang, the SSB demodulator's time, threshold and gate; Gqrx's
        # squelch a dBFS threshold with A and R. Built from the transport's
        # description of the channel (rest_sdr.CHANNEL_DSP), so nothing here
        # maps one SDR's controls onto another's. See AidPopup.
        aids = sCTkFrame(rx_column, fg_color="transparent", border_width=0)
        aids.grid(row=0, column=0, sticky="nw", pady=(2, 0))
        self.aids_lamps, self._lamp_arrows = {}, {}
        for column, (key, text) in enumerate(self.AIDS_LAMPS):
            cell = sCTkFrame(aids, fg_color="transparent", border_width=0)
            # Two rows of four: AGC NR Notch SQL, then NB CW DEC.
            cell.grid(row=column // 4, column=column % 4, padx=2, pady=2, sticky="w")
            lamp = sCTkButtonSecondary(cell, text=text, width=52, height=26,
                                       command=lambda k=key: self._lamp_clicked(k))
            lamp.pack(side="left")
            arrow = sCTkButtonTertiary(cell, text="\u25be", width=16, height=26,
                                       command=lambda k=key: self._open_aid(k))
            arrow.pack(side="left", padx=(1, 0))
            self.aids_lamps[key], self._lamp_arrows[key] = lamp, arrow
        self._lamp_states, self._lamp_live = {}, {}

        # THE FILTER, under the lamps on ONE line: "Filter", wide, narrow,
        # reset, then its width. A clear gap above it, so it does not read
        # as more of the lamps -- it is the passband, not a listening aid.
        # Kept, so they can be greyed out when the SDR takes no filter width
        # -- see _show_sdr_status.
        self.filter_buttons = []
        filter_row = sCTkFrame(rx_column, fg_color="transparent", border_width=0)
        filter_row.grid(row=1, column=0, sticky="w", pady=(14, 0))
        sCTkLabelTertiary(filter_row, text="Filter").pack(side="left", padx=(2, 6))
        for text, action in (("wide", lambda: self._filter(+1)),
                             ("narrow", lambda: self._filter(-1)),
                             ("reset", self._filter_reset)):
            btn = sCTkButtonSecondary(filter_row, text=text, width=56, height=24, command=action)
            btn.pack(side="left", padx=1)
            self.filter_buttons.append(btn)
        self.filter_label = sCTkLabelPrimary(filter_row, text="2400 Hz")
        self.filter_label.pack(side="left", padx=(6, 0))

        # What each small knob last showed -- see _dsp_step, _dsp_set,
        # _rf_gain_set.
        self._knob_values = {}
        # The controls in whichever pop-ups are open, by function -- filled
        # and emptied by AidPopup. Everything that updates a control looks
        # here, and finds nothing for a function whose pop-up is closed.
        self.dsp_switches, self.dsp_knobs = {}, {}
        self._knob_boxes, self._dsp_notes, self._knob_layout = {}, {}, {}
        self._switch_states = {}
        self._aid_actions = {}          # a function's own buttons -- see dsp_actions
        self._popups = {}

        # RF GAIN, beside the lamps: the SDR hardware's front-end gain, where
        # it has one. On Operate rather than Receive because it is ridden
        # while listening -- turned down to drop the noise under a weak CW
        # signal -- so a large knob, always on show. Greyed, with a note
        # beneath saying why, while the hardware's own AGC is setting it.
        # The two knobs share a frame in the middle column, which takes the
        # spare width -- so they sit centred between band and mode and the
        # transmit group.
        knobs = sCTkFrame(role_row, fg_color="transparent", border_width=0)
        knobs.grid(row=0, column=2, sticky="n")
        rf_area = sCTkFrame(knobs, fg_color="transparent", border_width=0)
        rf_area.grid(row=0, column=0, sticky="n", padx=(0, 8))
        self.rf_gain_knob = SmallKnob(rf_area, "RF gain", span=(0, 50),
                                      on_set=self._rf_gain_set,
                                      diameter=RF_GAIN_KNOB_DIAMETER,
                                      # FIX: "100", for a rigctl SDR's 0-100 % -- the
                                      # same size as the volume knob beside it.
                                      column=RF_GAIN_KNOB_COLUMN, widest_label="100")
        self.rf_gain_knob.pack()
        # Packed only while it has something to say -- see _set_rf_gain_note.
        # An empty label still takes a line's height beneath the knob.
        self.rf_gain_note = sCTkLabelTertiary(rf_area, text="",
                                              wraplength=110, justify="center")

        # VOLUME, beside RF gain and the same size: the two knobs ridden
        # while listening. A RANGE knob, 0-100 -- the SDR's level spread
        # evenly over its range (see SDR_Link.get_volume). DOUBLE-CLICK
        # MUTES, and again unmutes; while muted the value beneath says so.
        # It acts on the SDR, so it is greyed while listening through the
        # rig, whose level is its front-panel knob.
        volume_area = sCTkFrame(knobs, fg_color="transparent", border_width=0)
        volume_area.grid(row=0, column=1, sticky="n")
        self.volume_knob = SmallKnob(volume_area, "Volume", span=(0, 100),
                                     on_set=self._volume_set,
                                     on_double=self._volume_double,
                                     diameter=RF_GAIN_KNOB_DIAMETER,
                                     column=RF_GAIN_KNOB_COLUMN, widest_label="100")
        self.volume_knob.pack()
        # The level before the latest step -- see _volume_double.
        self._volume_before = None
        self._volume_shown = None
        # The knob's level. NOT asked of the SDR on every refresh: for the
        # computer's own volume that runs an external program. Taken from
        # the SDR when it reports a change -- see _sdr_audio_changed.
        self._volume_level = 50

        # Band and mode, beside the receive group --------------------------
        # Band ABOVE mode, between the lamps and the knobs. They act on both frequencies, but are changed alongside
        # receiving.
        centre = sCTkFrame(role_row, fg_color="transparent", border_width=0)
        centre.grid(row=0, column=1, padx=12, sticky="n")   # centred in its cell

        # Band is a short ordered list you step through, which is what a
        # spinbox is. It also shows where you are without being read.
        self.band_picker = sCTkSpinbox(
            centre, values=[b[0] for b in self.model.BANDS], wrap=False, width=110,
            command=self._on_band)
        self.band_picker.pack(pady=(2, 8))
        # Out of band, how many bands lie below the frequency -- see
        # _aim_band_arrows. None while in a band.
        self._off_band_below = None

        # Mode is DIRECT selection, not a rotary: you jump between modes
        # rather than sweeping through them.
        self.mode_picker = sCTkSegmentedButton(
            centre, values=MODES, command=self._on_mode)
        self.mode_picker.pack()

        # BANDWIDTH, under the modes: how wide a band the SDR samples -- what
        # its spectrum and waterfall show (SDRangel: the device's
        # decimation). A slider over the widths the device offers, narrowest
        # at the left; the width itself beside it. Greyed where the SDR has
        # no such setting. After it moves, the view is placed on the band
        # again -- see SDR_Link.set_bandwidth.
        width_row = sCTkFrame(centre, fg_color="transparent", border_width=0)
        width_row.pack(pady=(6, 0))
        # FIX: "Bandwidth" read as the receive filter's width. This sets how
        # wide a band the SDR samples -- what its spectrum and waterfall show.
        # Two lines, so the row keeps its width.
        sCTkLabelTertiary(width_row, text="Spectrum\nSpan", justify="center",
                          ).pack(side="left", padx=(0, 6))
        self.bandwidth_slider = sCTkSlider(
            width_row, from_=0, to=1, number_of_steps=1, width=110,
            command=self._bandwidth_moved)
        self.bandwidth_slider.pack(side="left")
        self.bandwidth_label = sCTkLabelPrimary(width_row, text=" ", width=64)
        self.bandwidth_label.pack(side="left", padx=(6, 0))
        # What the slider was last set to show: (choices, width, live).
        self._bandwidth_shown = None


        # Transmit controls, under the transmit frequency ------------------
        #
        # Row 1: Split, A<->B, A->B -- what sets up the transmit VFO. Row 2:
        # the offsets, which place it. Simplex is gone: it did what A->B
        # does, TX back onto RX.
        #
        # The offsets are DIMMED out of split, not hidden: hiding them moved
        # everything around them each time split toggled. They exist because
        # a pileup is the one time the dial is too slow -- the DX says "up 5"
        # and fifty clicks later someone else has him. The note beneath says
        # where TX is; it sits under the buttons so its changing width never
        # moves them.
        offset_column = sCTkFrame(role_row, fg_color="transparent",
                                  border_width=0)
        offset_column.grid(row=0, column=4, sticky="ne", padx=(0, 16), pady=(2, 0))

        self.offset_row = sCTkFrame(offset_column, fg_color="transparent",
                                    border_width=0)
        self.offset_row.pack(anchor="e")
        self._offset_buttons = []

        def tx_button(text, command, column, width=60):
            btn = sCTkButtonSecondary(
                self.offset_row, text=text, width=width, height=26, command=command)
            btn.grid(row=0, column=column, padx=2, pady=2, sticky="ew")
            return btn

        self._toggles["split"] = tx_button("Split", lambda: self._toggle("split"), 0)
        # FIX: kept, so the lock can grey them -- see _show_lock.
        # FIX (2026-11-08): THREE, WITH THE USUAL NAMES (Mark: "our definition
        # is the wrong one"). A/B SELECTS the other VFO -- what "A⇄B" did
        # here. A⇄B EXCHANGES their contents, as Brown's A<->B and most rigs'
        # do. A→B copies. The firmware has none of the last two; the link
        # builds them from the borrow -- see exchange_vfos.
        self._vfo_buttons = [tx_button("A/B", self._swap, 1),
                             tx_button("A \u21c4 B", self._exchange, 2),
                             tx_button("A\u2192B", self._copy_AtoB, 3)]
        # Log QSO at the end of the row: what you do when a contact ends.
        log = sCTkButtonPrimary(self.offset_row, text="Log QSO", height=26, command=self._log_qso)
        log.grid(row=0, column=4, columnspan=2, padx=(10, 2), pady=2, sticky="ew")
        # FIX (2026-11-10): greyed while logging is off in Setup (Mark).
        self.log_qso_button = log
        HoverNote(log, "Logs this contact to the logbook set in Setup > Logbook. "
                       "Greyed while logging is off there.")

        for column, (label, khz) in enumerate(SPLIT_OFFSETS):
            btn = sCTkButtonSecondary(
                self.offset_row, text=label, width=48, height=26,
                command=lambda k=khz: self._split_offset(k))
            btn.grid(row=1, column=column, padx=2, pady=2, sticky="ew")
            self._offset_buttons.append(btn)

        self.offset_note = sCTkLabelTertiary(offset_column, text="")
        self.offset_note.pack(anchor="e", pady=(2, 0))

        # STATUS, under the transmit group. It had a row of its own under
        # everything, which the window could not shrink away; everything else
        # in that row has moved into the panels and the groups above.
        actions = sCTkFrame(offset_column, fg_color="transparent", border_width=0)
        actions.pack(anchor="e", pady=(4, 0))

        # CONNECTION STATUS and the on-top toggle, at the right end of this
        # row. They had a row of their own at the bottom of the window, which
        # cost height better left to the SDR's window; the rest of that row
        # only repeated what is shown elsewhere.
        # TERTIARY, which is what it looks like: a quiet status at the end of
        # a row, not an action to reach for. It was a primary only because
        # primary was once the only tier with an alarm state; all three have
        # one now, so it is back where it belongs -- and tertiary's alarm
        # colours its border and text without filling, which suits a status.
        self.sdr_status = sCTkButtonTertiary(
            actions, text="sdr — reconnect", width=140, height=22,
            command=self._reconnect_sdr)
        self.sdr_status.pack(side="right")
        # Only that the serial port opened -- if it had not, the application
        # would have stopped. The rig's silence cannot say more: it reports
        # only when something changes. Real status comes with the connection
        # dialog.
        sCTkLabelTertiary(actions, text="rig ok").pack(side="right", padx=8)
        # FIX (2026-11-10): HELP where "on top" was -- that is now a
        # preference, Keep on top in Setup's Station group.
        self.help_button = sCTkButtonTertiary(
            actions, text="Help", width=96, height=22,
            command=self._open_help)
        self.help_button.pack(side="right", padx=8)
        self._set_keep_on_top(self._keep_on_top_saved(), save=False)
        self._set_s_meter_scale(self._s_meter_scale_saved(), save=False)   # FIX (2026-11-10)

        # Pop-ups left pinned last time, back where they were.
        self.after(800, self._restore_pinned_aids)

    def _build_rx(self, page):
        # FIX: no fonts on sCTk widgets -- the theme's tiers set them (see
        # _build_operate). The heading and "Listen through" were 15 bold;
        # their tier now carries the emphasis.
        wrap = sCTkFrame(page, fg_color="transparent", border_width=0)
        wrap.pack(fill="both", expand=True, padx=14, pady=12)

        sCTkLabelPrimary(wrap, text="Receive").pack(anchor="w")
        sCTkLabelTertiary(
            wrap,
            text="Everything about how you are listening. The choice below "
                 "decides where the audio and the signal reading come from, "
                 "and which of the controls under it can do anything: ATT and "
                 "IFS belong to the rig's own front end, so they work only "
                 "while you are listening through the rig.",
            wraplength=640, justify="left").pack(anchor="w", pady=(2, 12))

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
        sCTkLabelSecondary(row, text="Listen through").pack(side="left", padx=(0, 14))
        # dynamic_resizing=False, or `width` is IGNORED: by default each
        # segment shrinks to its own text, which is what made the first
        # enlargement look no different. Off, the width is shared equally,
        # so each segment is 140 wide around a three-letter word and reads
        # as a button rather than a label with a border.
        self.receiver_picker = sCTkSegmentedButton(
            row, values=["SDR", "Rig"],
            command=lambda source: self._set_listen_source(source, by_operator=True),
            width=280, height=40,
            dynamic_resizing=False)
        self.receiver_picker.pack(side="left")
        self.receiver_picker.set(self._listen_source)

        sCTkLabelTertiary(
            wrap,
            text="Decides where the audio and the signal meter come from.",
        ).pack(anchor="w", pady=(4, 14))

        # Volume moved to Operate, beside Mute. What is said here is how the
        # choice above changes the audio.
        # What the volume and mute act on depends on the SDR -- its own audio
        # for Gqrx, the whole computer for SDR++ -- so the note is filled in
        # on connecting. See _show_sdr_status.
        self.audio_note = sCTkLabelTertiary(
            wrap, text="", wraplength=640, justify="left")
        self.audio_note.pack(anchor="w", pady=(4, 8))

        # FIX (2026-11-10): ATT AND IFS WORK (Mark) -- the rig's own front end,
        # so live only while listening through the rig, with a rig to send to
        # and not locked. A switch and a slider each; the slider is sent once
        # it settles, the switch at once. Both show what the rig reports.
        self._front_end = {}
        for key, label, lo, hi, step in (
                ("att", "ATT", 0, ubitx_link.ATT_MAX, ubitx_link.ATT_STEP),
                ("ifs", "IFS", ubitx_link.IFS_MIN, ubitx_link.IFS_MAX, ubitx_link.IFS_STEP)):
            line = sCTkFrame(wrap, fg_color="transparent", border_width=0)
            line.pack(anchor="w", pady=3)
            sw = sCTkSwitch(line, text=label, width=70,
                            command=lambda _v=None, k=key: self._front_end_switched(k))
            sw.pack(side="left")
            slider = sCTkSlider(line, from_=lo, to=hi,
                                number_of_steps=(hi - lo) // step, width=260,
                                command=lambda v, k=key: self._front_end_moved(k, v))
            slider.pack(side="left", padx=(8, 0))
            value = sCTkLabelSecondary(line, text=" ", width=80)
            value.pack(side="left", padx=(8, 0))
            self._front_end[key] = {"switch": sw, "slider": slider, "value": value,
                                    "held_until": 0.0, "after": None}
        self.front_end_note = sCTkLabelTertiary(wrap, text=" ", wraplength=640,
                                                justify="left")
        self.front_end_note.pack(anchor="w", pady=(4, 0))
        self._front_end_shown = None

        # AGC is on Operate, beside NR and Notch -- one control, not two.

    def _build_channels(self, page):
        """
        One list, one set selector, and every action working on what is in
        front of you.

        The rig's twenty memory slots and the application's channel sets are shown as
        sets of one kind. A channel is a channel wherever it is kept, and
        tuning to one works the same way: the rig is told, and the SDR follows.

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
        # FIX: no fonts on sCTk widgets -- the theme's tiers set them (see
        # _build_operate).
        sCTkLabelTertiary(now_row, text="now").pack(side="left", padx=(0, 8))
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
        self.set_note = sCTkLabelTertiary(now_row, text="")
        self.set_note.pack(side="left", padx=(20, 0))

        # A MOVING BAR while the rig is read or written. The count in the note
        # is easy to miss -- a read-back starting on its own after a write
        # went unnoticed -- and a bar in motion is not. Shown only while busy.
        self.channel_progress = sCTkProgressBar(now_row, width=180, height=10)
        self.channel_progress.set(0)
        self._progress_shown = False

        head = sCTkFrame(page, fg_color="transparent", border_width=0)
        head.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 4))

        sCTkLabelTertiary(head, text="set").pack(side="left", padx=(0, 6))
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
            command=lambda: self.connection.read_channels())
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
        # FIX: the tab showing, so the channel table is filled only when it
        # can be seen -- see _refresh_channels. Operate is where the window
        # opens; _on_tab keeps it current.
        self._current_tab = "Operate"

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
        # FIX (2026-11-06): SKIP -- on to the next channel, while scanning.
        self.skip_button = sCTkButtonSecondary(actions, text="⏭ Skip", width=70,
                                               command=self._skip_channel)
        self.skip_button.pack(side="left", padx=(0, 8))
        self.dwell_entry = sCTkEntryPrimary(actions, width=48)
        self.dwell_entry.pack(side="left")
        self.dwell_entry.insert(0, str(self.channel_sets.dwell_seconds))
        self.dwell_entry.bind("<Return>", lambda e: self._read_dwell())
        self.dwell_entry.bind("<FocusOut>", lambda e: self._read_dwell())
        sCTkLabelTertiary(actions, text="seconds on each").pack(side="left", padx=4)
        # FIX (2026-11-06): HOLD ON A SIGNAL -- or scan by time alone, the
        # box unticked. The level from whichever receiver is heard; with
        # none to read (SDR++), the box is greyed and the scan goes by time.
        self._scan_on_signal = tk.BooleanVar(value=False)
        self.scan_signal_box = sCTkCheckBox(actions, text="hold on S", width=20,
                                            variable=self._scan_on_signal)
        self.scan_signal_box.pack(side="left", padx=(12, 2))
        self.scan_threshold_entry = sCTkEntryPrimary(actions, width=32)
        self.scan_threshold_entry.pack(side="left")
        self.scan_threshold_entry.insert(0, str(self.channel_sets.hold_level))
        self.scan_threshold_entry.bind("<Return>", lambda e: self._read_scan_threshold())
        self.scan_threshold_entry.bind("<FocusOut>", lambda e: self._read_scan_threshold())
        self.scan_signal_note = sCTkLabelTertiary(actions, text="")
        self.scan_signal_note.pack(side="left", padx=4)
        self._scan_set_name = None


        # slot -> {"freq", "mode", "label", "show_label"}: edits not yet
        # written. Overlaid on what the rig reported when the list is drawn.
        self._radio_draft = {}
        self._draft_version = 0

    # -- the sets ---------------------------------------------------------
    def _set_names(self):
        """The rig's memories first, then the channel sets by name."""
        return [RADIO_SET] + self.channel_sets.names()

    def _set_entries(self, chosen_set):
        """
        The channels in a set, in one shape whichever set it is:
        {"number", "label", "freq", "mode", "note"}.

        The rig's memories come from the model -- the rig reported them.
        The channel sets come from the configuration, which is where they are
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

        # FIX: THE TABLE ONLY WHILE IT CAN BE SEEN (2026-11-06). Filling it
        # took 4.2 s at startup -- all of it inside the window's constructor,
        # before the main loop, so the rig's start-up values sat in the
        # serial buffer for ~7 s though the rig had sent them at ~2 s
        # (UBITX_RIG_TIMING). Hidden, it is left as it is; opening the
        # Channels tab fills it, and later changes reach it on the next
        # refresh -- only the rows that changed, as below.
        if getattr(self, "_current_tab", "Channels") != "Channels":
            return

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
            # FIX: a row chosen while the table was hidden -- a scan that
            # reached a channel, say -- shown now it is filled.
            if self._selected_channel is not None and self._selected_channel < len(rows):
                self.channel_table.select_row(self._selected_channel)
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
        self._select_table_row(index)
        self._update_channel_buttons()

    def _select_table_row(self, index):
        """
        FIX: selects a row in the channel table -- only once the table has
        been filled. Until then the choice is kept in _selected_channel and
        shown when it is (see _refresh_channels): a scan running from Operate
        reaches channels before the table was ever opened.
        """
        if self._shown_set is not None and index is not None:
            self.channel_table.select_row(index)

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
            self._select_table_row(self._selected_channel)
            self.refresh()
            return
        if not self._can_edit_radio():
            return
        self._change_draft(self._selected_channel, freq=0, mode="DFT",
                           label="", show_label=False)

    def _add_vfo(self):
        """
        The receive frequency and mode, as a new channel at the end of a set.

        Carries the filter width in use, which the channel sets have always
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
        self._select_table_row(self._selected_channel)

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
        # FIX: only while the Channels tab is showing (2026-11-06). The
        # option menu's configure() redraws its border through
        # update_idletasks(), which forces Tk to lay out THE WHOLE WINDOW --
        # at startup the first such layout, 2.2 s of it (cProfile), inside
        # the constructor and ahead of the rig's reader. Opening the tab
        # comes back here and sets it.
        if (menu_kind != self._menu_kind_shown
                and getattr(self, "_current_tab", "Channels") == "Channels"):
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
        # FIX (2026-11-06): Skip only while a scan runs.
        self.skip_button.state("normal" if self.scanner.running else "disabled")
        if self.scanner.running:
            self.scan_button.configure(text="■ Stop")
            self.scan_button.state("normal")
        else:
            self.scan_button.configure(text="▶ Scan")
            scannable = any(e["freq"] for e in self._set_entries(self.set_picker.get()))
            if not in_set and self.model.channels_state != "read":
                scannable = False
            self.scan_button.state("normal" if scannable else "disabled")

        # FIX (2026-11-06): holding on a signal needs one to read, and is
        # chosen before a scan starts, not during it.
        available = self._signal_available()
        live = available and not self.scanner.running
        self.scan_signal_box.configure(state="normal" if live else "disabled")
        self.scan_threshold_entry.configure(state="normal" if live else "disabled")
        note = "" if available else "(no signal reading -- by time)"
        if self.scan_signal_note.cget("text") != note:
            self.scan_signal_note.configure(text=note or " ")  # FIX (2026-11-08): "" is ignored by sCTk labels -- a space clears

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
        # FIX: only while the table can be seen, as its rows (2026-11-06):
        # configuring the table's editable columns re-draws it, which cost
        # 2.2 s at startup on a table nobody was looking at. Opening the
        # Channels tab comes back here with the tab current, and applies it.
        if (editable != self._shown_editable
                and getattr(self, "_current_tab", "Channels") == "Channels"):
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
        if self.model.locked:               # FIX: see _show_lock
            self._notify(self.LOCKED_NOTE)
            return
        self._read_dwell()
        name = self.set_picker.get()
        self._scan_set_name = name
        threshold = None
        if self._scan_on_signal.get() and self._signal_available():
            threshold = self._read_scan_threshold()
        # The channels are FETCHED at every step, not copied now, so an edit
        # made during the scan is honoured on the next pass.
        self.scanner.start(lambda: self._set_entries(name),
                           start_index=self._selected_channel or 0,
                           dwell_seconds=self.channel_sets.dwell_seconds,
                           signal=self._signal_level, threshold=threshold)
        self.refresh()

    def _signal_level(self):
        """
        FIX (2026-11-06): the signal in S-units from the receiver being heard
        -- the SDR's reading through the SDR (None where it has none, as
        SDR++), the radio S-meter sensor through the rig. The rig sends its
        meter only when the step changes, and never a first S0, so a rig not
        yet heard from reads S0.
        """
        if self._listen_source == "SDR":
            return self.sdr.s_units()
        return self.model.s_value

    def _signal_available(self):
        """Is there a signal level to hold on? See _signal_level."""
        if self._listen_source == "SDR":
            return "signal" in self.sdr.capabilities
        return self.rig_state == "connected"

    def _read_scan_threshold(self):
        """
        The S-level to hold on, from its box: a whole S-unit, 1 to 9.
        FIX (2026-11-06): saved with the sets, like the dwell -- it went back
        to S5 at every start.
        """
        level = self.channel_sets.set_hold_level(
            self.scan_threshold_entry.get().strip().lstrip("Ss"))
        self.scan_threshold_entry.delete(0, "end")
        self.scan_threshold_entry.insert(0, str(level))
        return level

    def _skip_channel(self):
        """FIX (2026-11-06): the scan moves on to the next channel now."""
        if self.scanner.running:
            self.scanner.skip()

    def _scan_held(self, index, level):
        """FIX (2026-11-06): a signal is holding the scan -- or has let it go."""
        if level is not None:
            self._notify(f"scan holding -- signal S{level:.0f}", seconds=3600)
        else:
            self._notify("scan moving on -- the signal dropped")

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
        self._select_table_row(index)
        self.refresh()

    def _scan_stopped(self, reason):
        """The scan ended -- by request, or because the operator took over."""
        self._notify(f"scan {reason}")
        self.refresh()

    def _tune_to_channel(self, index):
        """
        Puts the receiver on a channel, through the rig.

        A COMMAND like any other control: the rig is told, the model changes
        when it confirms, and the SDR follows the model. Nothing here writes a
        frequency directly.

        The mode is changed only when the channel has one the rig can use;
        DFT tunes to the band's usual sideband. A set may hold modes the rig
        does not have.

        Tuning by hand ends a scan: the operator has chosen a channel.
        """
        if self.model.locked:               # FIX: see _show_lock
            self._notify(self.LOCKED_NOTE)
            return
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
        self._current_tab = name
        if name == "Channels" and self.model.channels_state == "unread":
            self.connection.read_channels()
        # FIX: the table is filled now it can be seen -- see _refresh_channels.
        if name == "Channels":
            self._refresh_channels()

    def _build_cw(self, page):
        wrap = sCTkFrame(page, fg_color="transparent", border_width=0)
        wrap.pack(fill="both", expand=True, padx=14, pady=12)
        # FIX: no fonts on sCTk widgets -- the theme's tiers set them (see
        # _build_operate).
        sCTkLabelPrimary(wrap, text="CW").pack(anchor="w")
        sCTkLabelTertiary(
            wrap,
            text="Keyer settings live here rather than in a dialog: you adjust "
                 "speed and tone while operating, sometimes mid-QSO.",
            wraplength=640, justify="left").pack(anchor="w", pady=(2, 12))

        # FIX (2026-11-06): THE RIG'S VALUES, read from its EEPROM at connect
        # (vt_, vs_, ve_, vy_, ck_) -- the fields were typed-in placeholders
        # and the keyer button was not even kept. "--" until the rig has
        # reported. EDITABLE: Return (or leaving the field) sends a number,
        # choosing a key sends it -- see _cw_entered and _cw_keyer_chosen.
        self._cw_fields = {}
        for key, label in (("cw_tone", "Tone (Hz)"), ("cw_wpm", "Speed (wpm)"),
                           ("cw_delay_tx_ms", "Delay to TX (ms)"),
                           ("cw_delay_rx_ms", "Delay to RX (ms)")):
            line = sCTkFrame(wrap, fg_color="transparent", border_width=0)
            line.pack(anchor="w", pady=3)
            sCTkLabelSecondary(line, text=label, width=130).pack(side="left")
            entry = sCTkEntryPrimary(line, width=80)
            entry.pack(side="left")
            entry.bind("<Return>", lambda _e, k=key: self._cw_entered(k))
            entry.bind("<FocusOut>", lambda _e, k=key: self._cw_entered(k))
            low, high = uBITX_Link.CW_LIMITS[key]
            sCTkLabelTertiary(line, text=f"{low}-{high}").pack(side="left", padx=(8, 0))
            self._cw_fields[key] = entry

        line = sCTkFrame(wrap, fg_color="transparent", border_width=0)
        line.pack(anchor="w", pady=3)
        sCTkLabelSecondary(line, text="Keyer", width=130).pack(side="left")
        self._cw_keyer = sCTkSegmentedButton(line, values=list(self.CW_KEYERS.values()),
                                             command=self._cw_keyer_chosen)
        self._cw_keyer.pack(side="left")

        # What the edits have done: saved and waiting for a restart, or not
        # confirmed. Tone and the delays are read by the rig only as it boots,
        # so the restart is OFFERED here, never done on its own -- it takes
        # the rig off the air for a few seconds.
        line = sCTkFrame(wrap, fg_color="transparent", border_width=0)
        line.pack(anchor="w", pady=(10, 0))
        self._cw_note = sCTkLabelTertiary(line, text="", wraplength=520, justify="left")
        self._cw_note.pack(side="left")
        self._cw_restart = sCTkButtonSecondary(line, text="Restart rig",
                                               command=self._cw_restart_rig)
        self._cw_shown = None
        self._show_cw()

        # FIX: the "Practice mode" switch is gone -- TX off on Operate does
        # that job, and two controls for one rig setting can disagree.
        # FIX: the "Decoder" button and "awaiting a backend that decodes" are
        # gone: decoding is DEC on Operate, through the SDR.

    # The rig's key types, as the keyer button names them.
    CW_KEYERS = {"STRAIGHT": "Straight", "IAMBICA": "Iambic A", "IAMBICB": "Iambic B"}

    # FIX (2026-11-10): ATT and IFS on the RX tab -------------------------
    FRONT_END_HOLD_S = 1.5          # the rig reports the old value until then
    FRONT_END_SETTLE_MS = 200       # a dragged slider is sent once it rests

    def _front_end_live(self):
        """ATT and IFS can be used: a rig, not locked, listening through it."""
        return (self._ready and self.rig_state == "connected"
                and not self.model.locked and self._listen_source == "Rig")

    @staticmethod
    def _front_end_text(key, value):
        if key == "att":
            return "off" if not value else f"{value}"
        return f"{value:+d} Hz"

    def _front_end_switched(self, key):
        """The ATT or IFS switch: on at the slider's value, or off."""
        part = self._front_end[key]
        if not self._front_end_live():
            self._front_end_shown = None            # put back what the rig has
            self._show_front_end()
            return
        on = bool(part["switch"].get())
        value = int(round(part["slider"].get()))
        part["held_until"] = time.monotonic() + self.FRONT_END_HOLD_S
        if key == "att":
            if on and value == 0:
                value = self._att_last or 50        # 0 is off: a level to go on at
                part["slider"].set(value)
            self.connection.set_att(value if on else 0)
        else:
            self.connection.set_ifs(on, value)
        part["value"].configure(text=self._front_end_text(key, value if on or key == "ifs" else 0))

    def _front_end_moved(self, key, value):
        """A slider moved: shown at once, sent once it rests."""
        part = self._front_end[key]
        if not self._front_end_live():
            return
        value = int(round(value))
        part["held_until"] = time.monotonic() + self.FRONT_END_HOLD_S
        part["value"].configure(text=self._front_end_text(key, value))
        if part["after"] is not None:
            try:
                self.after_cancel(part["after"])
            except Exception:
                pass
        part["after"] = self.after(self.FRONT_END_SETTLE_MS,
                                   lambda: self._front_end_send(key))

    def _front_end_send(self, key):
        part = self._front_end[key]
        part["after"] = None
        if not self._front_end_live():
            return
        value = int(round(part["slider"].get()))
        part["held_until"] = time.monotonic() + self.FRONT_END_HOLD_S
        if key == "att":
            # Moving the slider is choosing a level: ATT on at it (0 = off).
            self.connection.set_att(value)
        else:
            # The shift is set; IFS stays as switched -- moving it while off
            # turns it on, as moving the ATT slider does.
            self.connection.set_ifs(True, value)

    def _show_front_end(self):
        """ATT and IFS as the rig reports them, live or greyed. Only on a change."""
        parts = getattr(self, "_front_end", None)
        if not parts:
            return
        m = self.model
        live = self._front_end_live()
        if m.att_level:
            self._att_last = m.att_level
        shown = (m.att_level, m.ifs_on, m.ifs_hz, live)
        now = time.monotonic()
        if shown == self._front_end_shown or any(
                now < p["held_until"] for p in parts.values()):
            return
        self._front_end_shown = shown
        for key, on, value in (("att", bool(m.att_level), m.att_level or self._att_last or 0),
                               ("ifs", bool(m.ifs_on), m.ifs_hz)):
            part = parts[key]
            part["switch"].configure(state="normal")
            part["switch"].select() if on else part["switch"].deselect()
            part["slider"].configure(state="normal")
            part["slider"].set(value)
            for w in (part["switch"], part["slider"]):
                w.configure(state="normal" if live else "disabled")
            part["value"].configure(text=self._front_end_text(key, value if on else 0)
                                    if key == "att" else
                                    (self._front_end_text(key, value) if on else "off"))
        if live:
            note = ("ATT shifts the rig's first IF away from the signal -- higher is "
                    "quieter. IFS moves the passband.")
        elif self._listen_source != "Rig":
            note = "Listening through the SDR: ATT and IFS act on the rig's own receiver only."
        elif m.locked:
            note = "The rig is locked."
        else:
            note = "No rig connected."
        self.front_end_note.configure(text=note)

    def _show_cw(self):
        """
        FIX (2026-11-06): the CW tab shows what the rig reported -- tone,
        speed, the two delays and the key type. Repainted only when one of
        them changes. A value not reported shows "--", and no key is chosen,
        rather than a default that looks like the rig's.
        """
        if not hasattr(self, "_cw_fields"):
            return                                  # the tab not built yet
        values = self._cw_values()
        m = self.model
        # Editable only with a rig to send to, and not while it is locked.
        live = self._ready and self.rig_state == "connected" and not m.locked
        shown = (values, m.cw_key_type, tuple(sorted(m.cw_pending.items())),
                 m.cw_write_failed, live)
        if shown == self._cw_shown:
            return
        self._cw_shown = shown
        for key, entry in self._cw_fields.items():
            # A field waiting on a restart shows the value saved, since that
            # is what the operator set and what the rig will use.
            value = m.cw_pending.get(key, values[key])
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.insert(0, "--" if value is None else str(value))
            entry.configure(state="normal" if live else "readonly")
        self._cw_keyer.set(self.CW_KEYERS.get(m.cw_key_type, ""))
        self._cw_keyer.configure(state="normal" if live else "disabled")

        names = {"cw_tone": "tone", "cw_delay_tx_ms": "delay to TX",
                 "cw_delay_rx_ms": "delay to RX", "cw_wpm": "speed",
                 "cw_key_type": "keyer", "master_cal": "master calibration",
                 "ssb_bfo": "SSB BFO", "cw_bfo": "CW BFO"}
        notes = []
        if m.cw_pending:
            which = " and ".join(names[k] for k in sorted(m.cw_pending))
            notes.append(f"New {which} saved in the rig -- it uses them after "
                         f"a restart, which takes it off the air for a few seconds.")
        if m.cw_write_failed:
            notes.append(f"The rig did not confirm the new {names[m.cw_write_failed]}"
                         f" -- it may not be saved.")
        if m.locked:
            notes.append(self.LOCKED_NOTE)
        self._cw_note.configure(text="  ".join(notes) or " ")  # FIX (2026-11-08): "" is ignored by sCTk labels -- a space clears
        if m.cw_pending and live:
            self._cw_restart.pack(side="left", padx=(10, 0))
        else:
            self._cw_restart.pack_forget()

    def _cw_values(self):
        """The rig's keyer numbers as reported, None where not yet."""
        m = self.model
        return {"cw_tone": m.cw_tone if m.cw_tone_reported else None,
                "cw_wpm": m.cw_wpm, "cw_delay_tx_ms": m.cw_delay_tx_ms,
                "cw_delay_rx_ms": m.cw_delay_rx_ms}

    def _cw_entered(self, key):
        """
        FIX (2026-11-06): a number typed on the CW tab goes to the rig. One
        not a number, or out of range, is refused and the field put back.
        Unchanged, nothing is sent -- leaving the field calls this too.
        """
        if not self._cw_shown or not self._cw_shown[-1]:
            return                                # not live: see _show_cw
        entry = self._cw_fields[key]
        text = entry.get().strip()
        current = self.model.cw_pending.get(key, self._cw_values()[key])
        low, high = uBITX_Link.CW_LIMITS[key]
        try:
            value = int(text)
        except ValueError:
            value = None
        if value is not None and value == current:
            return
        if value is None or not low <= value <= high:
            if text not in ("", "--"):
                self._cw_note.configure(text=f"{text!r} is not between {low} and {high}.")
            self._cw_shown = None                        # put the field back
            self._show_cw()
            return
        self.connection.set_cw(key, value)

    def _cw_keyer_chosen(self, label):
        """FIX (2026-11-06): choosing a key sends it; the rig's word sets the button."""
        word = next((w for w, name in self.CW_KEYERS.items() if name == label), None)
        if not self._cw_shown or not self._cw_shown[-1] or word is None:
            self._cw_shown = None
            self._show_cw()
            return
        if word != self.model.cw_key_type:
            self.connection.set_cw("cw_key_type", word)
        # Shown as the rig has it until the write is acknowledged.
        self._cw_shown = None
        self._show_cw()

    def _cw_restart_rig(self):
        """
        FIX (2026-11-06): restarts the rig so it reads the saved tone and
        delays. Asked for by the operator, never done on its own. The rig
        reports everything as it boots, which clears the waiting values.
        """
        if self.model.locked or not self.model.cw_pending:
            return
        self.connection.restart_rig()   # FIX (2026-11-06): the preset again too

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
        # SCROLLS. The window is sized for Operate -- around 360 points tall
        # -- and these groups are taller than that once they hold real
        # controls. Scrolling means a group can grow, or the window shrink,
        # without anything being cut off out of sight.
        wrap = sCTkScrollableFrame(page, fg_color="transparent", border_width=0)
        wrap.pack(fill="both", expand=True, padx=10, pady=(2, 2))

        groups = (
            ("Station", (
                ("Callsign", "entry", self.model.callsign),
                ("Appearance", "appearance", list(self.APPEARANCES)),   # FIX (2026-11-10)
                ("Keep on top", "keep_on_top", None),     # FIX (2026-11-10)
            )),
        )

        # THREE ACROSS, not two: the window is wide and short -- sized for
        # Operate -- so width is what there is spare and height is what there
        # is not.
        columns = sCTkFrame(wrap, fg_color="transparent", border_width=0)
        columns.pack(fill="both", expand=True)
        columns.grid_columnconfigure((0, 1, 2), weight=1, uniform="setup")

        # Radio and SDR are real controls -- they are how the operator says
        # where the equipment is, and nothing else can say it. Station and
        # Logbook are still the settings they will become.
        # Station, Radio, SDR across the top; Logbook beneath.
        self._build_radio_settings(self._settings_box(columns, 0, 1, "Radio", 2))
        self._build_sdr_settings(self._settings_box(columns, 0, 2, "SDR", 4))
        # FIX: THE BOTTOM ROW IN HALVES, not thirds -- Logbook and Other
        # Settings each need about a column and a half: Logbook two fields to
        # a line, Other Settings three buttons. Two lines each, instead of the
        # four Logbook took in one column, which set the height of the whole
        # row and made Setup much taller than Operate.
        bottom = sCTkFrame(wrap, fg_color="transparent", border_width=0)
        bottom.pack(fill="both", expand=True)
        bottom.grid_columnconfigure((0, 1), weight=1, uniform="setup_bottom")
        self._build_logbook_settings(self._settings_box(bottom, 0, 0, "Logbook", 2))

        for index, (title, rows) in enumerate(groups):
            row, column = (0, 0) if index == 0 else (1, 0)
            box = self._settings_box(columns, row, column, title, len(rows))

            for label, kind, value in rows:
                line = sCTkFrame(box, fg_color="transparent", border_width=0)
                line.pack(fill="x", padx=10, pady=1)
                sCTkLabelTertiary(line, text=label, width=86, anchor="w").pack(side="left")

                if kind == "entry":
                    field = sCTkEntryPrimary(line, width=150, height=SETTINGS_CONTROL_HEIGHT)
                    field.pack(side="left")
                    field.insert(0, value)
                    if label == "Callsign":
                        # FIX (2026-11-06): THE RIG'S CALLSIGN, from its EEPROM
                        # (the sc report at connect) -- it was a placeholder
                        # filled with the model's seed. Return, or leaving
                        # the field, writes a changed one -- see _callsign_entered.
                        self.callsign_entry = field
                        field.delete(0, "end")
                        field.bind("<Return>", lambda e: self._callsign_entered())
                        field.bind("<FocusOut>", lambda e: self._callsign_entered())
                        self.callsign_note = sCTkLabelTertiary(line, text="")
                        self.callsign_note.pack(side="left", padx=4)
                        self._callsign_shown = None
                elif kind == "choice":
                    sCTkComboBox(line, values=value, width=150, height=SETTINGS_CONTROL_HEIGHT).pack(side="left")
                elif kind == "appearance":
                    # FIX (2026-11-10): was a placeholder choice, wired to nothing.
                    self.appearance_choice = sCTkComboBox(
                        line, values=value, width=150, height=SETTINGS_CONTROL_HEIGHT,
                        state="readonly",
                        command=lambda choice: self._set_appearance(choice))
                    self.appearance_choice.pack(side="left")
                    self.appearance_choice.set(self._appearance_saved())
                elif kind == "keep_on_top":
                    # FIX (2026-11-10): was the "on top" button on Operate.
                    self.keep_on_top_switch = sCTkSwitch(
                        line, text="",
                        command=lambda _v=None: self._set_keep_on_top(
                            self.keep_on_top_switch.get()))
                    self.keep_on_top_switch.pack(side="left")
                    if self._keep_on_top_saved():
                        self.keep_on_top_switch.select()
                    else:
                        self.keep_on_top_switch.deselect()
                elif kind == "switch":
                    sCTkSwitch(line, text="").pack(side="left")
                else:
                    sCTkButtonSecondary(line, text=value, width=200, height=SETTINGS_CONTROL_HEIGHT,
                                        anchor="w").pack(side="left")

            # Bottom padding comes from the LAST ROW'S pady, not a spacer.
            #
            # There used to be a spacer here -- an sCTkFrame with a height
            # and no width. It took CustomTkinter's default width of 200,
            # sat centred against the bottom edge, and "transparent" means
            # "paint in the parent's colour" -- so it painted a 200-pixel
            # strip of background straight across the group's border. Every
            # group had a gap in its bottom edge, the same span each time.
            line.pack_configure(pady=(1, 8))

        # THE WINDOWS OF THEIR OWN, as a group like the rest. They were a
        # loose row under everything, with a note trailing off the side --
        # which on a short window sat half off the bottom of the page.
        #
        # They keep their own windows because each writes values into the
        # radio that can stop it working, and that deserves a deliberate act
        # rather than a field on a page being scrolled past.
        # FIX: "Other Settings", the right half of the bottom row, three
        # buttons to a line -- two lines.
        box = self._settings_box(bottom, 0, 1, "Other Settings", 2)
        # FIX (2026-11-06): the two that were greyed placeholders, built.
        pairs = (("EEPROM settings…", self._rig_eeprom_settings),
                 ("Machine settings…", self._machine_settings),
                 ("Backup and restore…", self._eeprom_backup),
                 ("SDR settings…", self._sdr_advanced),
                 ("About…", self._about))
        line = None
        for index, (text, action) in enumerate(pairs):
            if index % 3 == 0:
                line = self._settings_line(box, "")
            button = sCTkButtonSecondary(line, text=text, width=150, anchor="w",
                                         height=SETTINGS_CONTROL_HEIGHT,
                                         command=action)
            button.pack(side="left", padx=(0, 8))
            if action is None:
                button.state("disabled")
        line.pack_configure(pady=(1, 8))

    @staticmethod
    def _settings_box(columns, row, column, title, rows=1, span=1):
        """
        One titled group on the Setup page.

        The panel is as tall as what is in it -- the library's labelled frame
        does that itself now, so nothing here sets a height. `rows` is left in
        the signature because every call passes it; it is ignored.

        "nsew", so the groups in a row all stand as tall as the tallest --
        the row is that height anyway, and a short group beside a tall one
        looked unfinished rather than deliberate. Each still ASKS for its own
        content's height, so the row is never taller than it needs to be.
        """
        box = sCTkFrameLabeledSecondary(columns, label_text=title, label_anchor="w")
        box.grid(row=row, column=column, columnspan=span, sticky="nsew", padx=4, pady=2)
        box.group_title = title
        return box

    @staticmethod
    def _group_note(box, text=""):
        """
        Says how a group is getting on, in its own title: "Radio — connected
        on /dev/cu.usbserial-A5069RR4".

        In the TITLE because the alternative is a row of its own in every
        group, for a line that is usually empty -- and the title line has the
        room.
        """
        box.configure(label_text=f"{box.group_title} — {text}" if text
                      else box.group_title)

    @staticmethod
    def _settings_line(box, label, label_width=76):
        """A labelled row inside a group; returns the frame to fill."""
        # A FIXED HEIGHT, so every row is the same pitch and the groups line
        # up across the page. Left to size themselves, a combobox row, an
        # entry row and a switch row each came out different, and the three
        # columns rippled against one another.
        line = sCTkFrame(box, fg_color="transparent", border_width=0,
                         height=SETTINGS_ROW_HEIGHT)
        line.pack(fill="x", padx=10, pady=1)
        line.pack_propagate(False)          # keep the height set above
        if label:
            # WIDE ENOUGH FOR THIS GROUP'S LONGEST LABEL, no more. One width
            # for the whole page meant "Port" sat in a 76-point column with
            # half of it empty, and the control beside it lost that room --
            # which is the room the port list needed to show which adapter
            # each port is.
            sCTkLabelTertiary(line, text=label, width=label_width, anchor="w").pack(side="left")
        return line

    # -- where the radio is -------------------------------------------------
    def _build_radio_settings(self, box):
        """
        Choosing the rig's port. NOTHING IS GUESSED: the ports are listed,
        the operator picks, and the choice is saved once it works.

        The same field takes a network rig -- "socket://192.168.1.50:8080" --
        because it is an editable list: pick a port, or type an address.
        """
        line = self._settings_line(box, "Port", 44)
        self.port_picker = sCTkComboBox(line, width=262, height=SETTINGS_CONTROL_HEIGHT, values=[""])
        self.port_picker.pack(side="left")
        # 86, not 72: at 72 the word itself was clipped, and the row ran
        # past the group's edge -- the label, the list and this button have
        # to fit a third of the window between them.
        sCTkButtonSecondary(line, text="Refresh", width=86, height=SETTINGS_CONTROL_HEIGHT,
                            command=self._refresh_ports).pack(side="left", padx=(4, 0))

        line = self._settings_line(box, "Speed", 44)
        self.baud_picker = sCTkComboBox(
            line, width=96, height=SETTINGS_CONTROL_HEIGHT,
            values=["9600", "19200", "38400", "57600", "115200"])
        self.baud_picker.pack(side="left")
        self.baud_picker.set(str(gv.config.get_rig_baud()))
        # Every port a Mac or PC reports, including the ones normally hidden:
        # the filtering can be wrong about somebody's station, and a filter
        # that cannot be overridden is worse than none.
        self.show_all_ports = sCTkCheckBox(line, text="show all",
                                           command=self._refresh_ports)
        self.show_all_ports.pack(side="left", padx=8)
        sCTkButtonPrimary(line, text="Connect", width=90, height=SETTINGS_CONTROL_HEIGHT,
                          command=self._connect_rig).pack(side="left", padx=4)

        self.radio_box = box
        line.pack_configure(pady=(1, 8))
        self._refresh_ports()
        self._show_rig_status()

    def _refresh_ports(self):
        """Lists the ports again -- an adapter may have been plugged in since."""
        show_all = bool(self.show_all_ports.get()) if hasattr(self, "show_all_ports") else False
        try:
            ports = list_rig_ports(show_all=show_all)
        except Exception as err:            # pyserial missing, or an odd system
            print(f"[rig] could not list the ports: {err}")
            ports = []
        # The LABEL is what the operator picks from -- "FTDI" against "CH340"
        # is the distinction they would use -- so the device it means is kept
        # beside it rather than parsed back out of the text.
        self._port_labels = {p.label: p.device for p in ports}
        values = list(self._port_labels) or ["no ports found"]
        self.port_picker.configure(values=values)

        # Show what is stored, whether or not it is plugged in now: it is
        # still what will be tried, and seeing it is how you know why.
        stored = gv.config.get_rig_port()
        for label, device in self._port_labels.items():
            if device == stored:
                self.port_picker.set(label)
                return
        self.port_picker.set(stored or values[0])

    def _connect_rig(self):
        """Opens the chosen port, and saves it if it works."""
        chosen = self.port_picker.get().strip()
        device = self._port_labels.get(chosen, chosen)
        kind, value, problem = parse_rig_port(device)
        if not kind:
            self.rig_note = problem
            self._show_rig_status()
            return

        # Whatever was running has to stop AND its port be closed -- see
        # _close_rig.
        self._close_rig()

        gv.config.set_rig_port(device)
        try:
            gv.config.set_rig_baud(int(self.baud_picker.get()))
        except ValueError:
            pass
        self._group_note(self.radio_box, f"opening {device}…")
        self.update_idletasks()
        self._open_rig()
        self._show_rig_status()
        self.refresh()

    # -- the logbook --------------------------------------------------------
    def _build_logbook_settings(self, box):
        """
        Where contacts are written, and in what.

        THE FORMAT DECIDES THE EXTENSION. A logbook named .adi holding CSV is
        a file no other program will read properly, so the two are never set
        apart: changing the format renames the file, and choosing a file
        corrects its extension.
        """
        line = self._settings_line(box, "Enabled", 58)
        # FIX: the switch in a cell as wide as the File button below it, so
        # Format lines up with Backup -- the two lines form two columns.
        cell = sCTkFrame(line, fg_color="transparent", border_width=0,
                         width=LOGBOOK_FIELD_WIDTH, height=SETTINGS_CONTROL_HEIGHT)
        cell.pack(side="left")
        cell.pack_propagate(False)
        self.logbook_switch = sCTkSwitch(cell, text="", command=self._save_logbook_switch)
        self.logbook_switch.pack(side="left")
        if str(gv.config.get_Logbook_Switch()).lower() == "true":
            self.logbook_switch.select()

        # FIX: two fields to a line -- Enabled and Format, then File and
        # Backup -- now the group is two columns wide (see _build_setup).
        sCTkLabelTertiary(line, text="Format", width=58, anchor="w").pack(side="left", padx=(24, 0))
        self.logbook_format = sCTkComboBox(
            line, width=110, height=SETTINGS_CONTROL_HEIGHT,
            values=[name for _, name in LOGBOOK_FORMATS],
            command=self._on_logbook_format)
        self.logbook_format.pack(side="left")
        current = str(gv.config.get_Logbook_Type()).lower()
        self.logbook_format.set(dict(LOGBOOK_FORMATS).get(current, "ADIF"))

        line = self._settings_line(box, "File", 58)
        self.logbook_file = sCTkButtonSecondary(
            line, text="", width=LOGBOOK_FIELD_WIDTH, anchor="w",
            height=SETTINGS_CONTROL_HEIGHT, command=self._choose_logbook_file)
        self.logbook_file.pack(side="left")

        sCTkLabelTertiary(line, text="Backup", width=58, anchor="w").pack(side="left", padx=(24, 0))
        self.logbook_backup = sCTkEntryPrimary(line, width=70,
                                               height=SETTINGS_CONTROL_HEIGHT)
        self.logbook_backup.pack(side="left")
        self.logbook_backup.insert(0, str(gv.config.get_Logbook_Backup_Interval()))
        self.logbook_backup.bind("<Return>", lambda e: self._save_logbook_backup())
        self.logbook_backup.bind("<FocusOut>", lambda e: self._save_logbook_backup())
        sCTkLabelTertiary(line, text="minutes").pack(side="left", padx=6)
        line.pack_configure(pady=(1, 8))
        self._show_logbook_file()

    def _logbook_path(self):
        """The logbook as the settings describe it: folder, name, format."""
        folder = os.path.expanduser(str(gv.config.get_Logbook_Location() or "~"))
        name = str(gv.config.get_Logbook_Name() or "uBITX_Logbook")
        return os.path.join(folder, f"{name}.{str(gv.config.get_Logbook_Type()).lower()}")

    def _show_logbook_file(self):
        """The path on the button, shortened from the left if it is long."""
        path = self._logbook_path().replace(os.path.expanduser("~"), "~")
        self.logbook_file.configure(text=path if len(path) <= 36 else "…" + path[-35:])

    def _save_logbook_switch(self):
        gv.config.set_Logbook_Switch("True" if self.logbook_switch.get() else "False")
        self._show_log_button()                 # FIX (2026-11-10)

    def _logging_on(self):
        """FIX (2026-11-10): the Logbook switch in Setup, as saved."""
        try:
            return str(gv.config.get_Logbook_Switch()).lower() == "true"
        except AttributeError:
            return False

    def _show_log_button(self):
        """FIX (2026-11-10): Log QSO live only while logging is on."""
        button = getattr(self, "log_qso_button", None)
        if button is not None:
            button.configure(state="normal" if self._logging_on() else "disabled")

    def _save_logbook_backup(self):
        try:
            gv.config.set_Logbook_Backup_Interval(int(self.logbook_backup.get()))
        except ValueError:
            self.logbook_backup.delete(0, "end")
            self.logbook_backup.insert(0, str(gv.config.get_Logbook_Backup_Interval()))

    def _on_logbook_format(self, shown):
        """A different format: the file takes the matching extension."""
        chosen = next((key for key, name in LOGBOOK_FORMATS if name == shown), "adi")
        gv.config.set_Logbook_Type(chosen)
        self._show_logbook_file()

    def _choose_logbook_file(self):
        """
        Chooses the logbook file.

        THE EXTENSION IS THE FORMAT'S, whatever is typed into the dialog: a
        file named .csv holding ADIF, or the other way about, is one no other
        program will read. The name and folder are the operator's; the
        extension is not.
        """
        from tkinter import filedialog

        kind = str(gv.config.get_Logbook_Type()).lower()
        shown = dict(LOGBOOK_FORMATS).get(kind, "ADIF")
        current = self._logbook_path()
        chosen = filedialog.asksaveasfilename(
            parent=self, title="Logbook file", defaultextension=f".{kind}",
            initialdir=os.path.dirname(current),
            initialfile=os.path.basename(current),
            filetypes=[(f"{shown} logbook", f"*.{kind}"), ("All files", "*.*")])
        if not chosen:
            return
        folder, filename = os.path.split(chosen)
        stem = os.path.splitext(filename)[0]
        gv.config.set_Logbook_Location(folder)
        gv.config.set_Logbook_Name(stem)
        self._show_logbook_file()

    # -- where the SDR is ---------------------------------------------------
    def _build_sdr_settings(self, box):
        """
        Which SDR program, and where. "-none-" means there is no SDR: nothing
        is tried, and the interface greys everything an SDR would serve.
        """
        # FIX: no fonts on sCTk widgets here or in _sdr_advanced -- the
        # theme's tiers set them (see _build_operate).
        line = self._settings_line(box, "Software", 62)
        self.sdr_picker = sCTkComboBox(line, width=150, height=SETTINGS_CONTROL_HEIGHT,
                                       command=self._on_sdr_software,
                                       values=[name for _, name in sdr_choices()])
        self.sdr_picker.pack(side="left")
        connect = sCTkButtonPrimary(line, text="Connect", width=90,
                                    height=SETTINGS_CONTROL_HEIGHT,
                                    command=self._connect_sdr)
        connect.pack(side="left", padx=8)
        self.sdr_connect_button = connect       # FIX (2026-11-10): see _show_sdr_fields
        current = gv.config.get_sdr_software()
        self.sdr_picker.set(dict(sdr_choices()).get(current, sdr_programs.NONE_CHOICE))

        # START IT IF IT IS NOT RUNNING. An SDR already running is the
        # operator's: attached to, and left running when this closes. One
        # started here is closed with this application -- see
        # SDR_Link.close_program().
        line = self._settings_line(box, "Start it", 62)
        self.sdr_autostart = sCTkCheckBox(line, text="if it is not running",
                                          command=self._save_autostart)
        self.sdr_autostart.pack(side="left")
        if str(gv.config.get_SDR_Autostart()) in ("1", "True", "true"):
            self.sdr_autostart.select()

        # FIX: SAYS WHEN THE PROGRAM'S USUAL LOCATION IS OVERRIDDEN by the
        # path in SDR settings -- otherwise a program that starts from an
        # unexpected place, or will not start, has no visible cause. On the
        # "Start it" line, at its top, LEFT-ALIGNED under Connect
        # (2026-11-05) -- beside Connect it was cut off, and centred it ran
        # into the checkbox's text. Placed, not packed, so it follows Connect
        # wherever the layout puts it.
        self.sdr_path_note = sCTkLabelTertiary(line, text="")

        def under_connect(_event=None, start_line=line):
            try:
                x = connect.winfo_rootx() - start_line.winfo_rootx()
                self.sdr_path_note.place(in_=start_line, x=x+8, y=0, anchor="nw")
            except Exception:
                pass

        connect.bind("<Configure>", under_connect, add="+")
        line.bind("<Configure>", under_connect, add="+")
        self._show_sdr_path()

        line = self._settings_line(box, "Address", 62)
        self.sdr_host_entry = sCTkEntryPrimary(line, width=150, height=SETTINGS_CONTROL_HEIGHT)
        self.sdr_host_entry.pack(side="left")
        self.sdr_host_entry.insert(0, gv.config.get_sdr_host())
        sCTkLabelTertiary(line, text="port").pack(side="left", padx=(8, 4))
        self.sdr_port_entry = sCTkEntryPrimary(line, width=70, height=SETTINGS_CONTROL_HEIGHT)
        self.sdr_port_entry.pack(side="left")
        self.sdr_port_entry.insert(0, str(gv.config.get_sdr_port()))

        # FIX: THE PORT DECODED CW ARRIVES ON, for a program that sends it
        # over UDP (SDRoxide, SDRoxide Brown). Set in the program too -- its
        # Settings > Servers -- and the two must agree. SAVED PER PROGRAM, in
        # your own sdr_programs.json, not as one setting for all: one global
        # value is what makes the SDR Path setting start the wrong program.
        # Empty puts the program's usual port back. Greyed, saying why, for a
        # program without such a decoder, and for SDRangel, which the
        # application sets up itself.
        line = self._settings_line(box, "CW port", 62)
        self.decoder_port_entry = sCTkEntryPrimary(line, width=70,
                                                   height=SETTINGS_CONTROL_HEIGHT)
        self.decoder_port_entry.pack(side="left")
        self.decoder_port_entry.bind("<Return>", lambda e: self._save_decoder_port())
        self.decoder_port_entry.bind("<FocusOut>", lambda e: self._save_decoder_port())
        self.decoder_port_note = sCTkLabelTertiary(line, text="", anchor="w")
        self.decoder_port_note.pack(side="left", padx=(8, 0))
        self._show_decoder_port()

        # EVERYTHING ELSE IS BEHIND "SDR settings…", in the Settings group
        # below: the filter widths now, and in time noise blanking, squelch
        # behaviour, whatever a backend turns out to offer. What stays here is
        # what a station is set up with once -- which program, and where.

        self.sdr_box = box
        line.pack_configure(pady=(1, 8))
        self._show_sdr_fields()

    def _show_sdr_fields(self):
        """
        FIX (2026-11-10): WITH NO SDR CHOSEN ("-none-", the default) Connect
        and the fields that only describe an SDR -- start it, address, port --
        are greyed until a program is chosen (Mark). The CW port says so
        itself (_show_decoder_port).
        """
        chosen = gv.config.get_sdr_software() not in ("", "none")
        state = "normal" if chosen else "disabled"
        for name in ("sdr_connect_button", "sdr_autostart",
                     "sdr_host_entry", "sdr_port_entry"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.configure(state=state)

    def _on_sdr_software(self, shown):
        """
        A different program chosen: its usual port is offered, unless the
        operator has already set one of their own.
        """
        key = next((k for k, name in sdr_choices() if name == shown), "none")
        # FIX: A DIFFERENT PROGRAM CLEARS THE CUSTOM LOCATION. It is one
        # setting for every program, so the path set for one was used to
        # start the next -- the wrong program, or none. Choosing the same
        # program again keeps it.
        if key != gv.config.get_sdr_software() and gv.config.get_sdr_path():
            print(f"[sdr] custom location {gv.config.get_sdr_path()!r} cleared: "
                  f"{shown} is looked for in its usual places")
            gv.config.set_sdr_path("")
            self._show_sdr_path()
        was = gv.config.get_sdr_software()
        gv.config.set_sdr_software(key)
        profile = profile_for(key)
        self._show_decoder_port()       # FIX: the new program's CW port
        self._show_sdr_fields()         # FIX (2026-11-10)
        if key == "none":
            # FIX (2026-11-10): -none- is applied at once, since Connect is
            # greyed with it: an SDR in use is let go, and you listen through
            # the rig -- there is nothing else to listen through.
            if was not in ("", "none"):
                self._connect_sdr()
            if self._listen_source != "Rig":
                self.receiver_picker.set("Rig")
                self._set_listen_source("Rig")
            return
        if not profile.default_port:
            return

        # OFFER THE NEW PROGRAM'S PORT unless the operator typed one of their
        # own. "Their own" means a port that is not any program's usual one:
        # comparing against the PREVIOUS program's default missed the case
        # that matters, choosing Gqrx while the setting still said None --
        # None has no port, so nothing matched and the field kept 4532.
        usual = {str(known.default_port) for known in sdr_programs.PROFILES.values()
                 if known.default_port}
        current = str(gv.config.get_sdr_port() or "")
        if current and current not in usual:
            return                      # theirs; leave it

        gv.config.set_sdr_port(profile.default_port)
        self.sdr_port_entry.delete(0, "end")
        self.sdr_port_entry.insert(0, str(profile.default_port))

    def _show_sdr_path(self):
        """'(custom path)' under Connect while SDR settings holds a path."""
        note = getattr(self, "sdr_path_note", None)
        if note is not None:
            note.configure(text="(custom path)" if gv.config.get_sdr_path() else "")

    def _decoder_port_kind(self, profile):
        """'udp' (editable), 'auto' (SDRangel sets it) or None (no decoder)."""
        if profile.protocol == "rest":
            return "auto"
        if profile.decoder_udp_port or sdr_programs.shipped_setting(
                profile.key, "decoder_udp_port"):
            return "udp"
        return None

    def _show_decoder_port(self):
        """The CW port field for the program chosen: its port, or greyed with why."""
        entry = getattr(self, "decoder_port_entry", None)
        if entry is None:
            return
        profile = profile_for(gv.config.get_sdr_software())
        kind = self._decoder_port_kind(profile)
        entry.configure(state="normal")
        entry.delete(0, "end")
        if kind == "udp":
            entry.insert(0, str(profile.decoder_udp_port or ""))
            note = f"UDP, as set in {profile.name}"
        else:
            entry.configure(state="disabled")
            if kind == "auto":
                note = f"{profile.name} is set up automatically"
            elif profile.key == "none":
                note = "no SDR chosen"
            else:
                note = f"{profile.name} has no CW decoder"
        self.decoder_port_note.configure(text=note or " ")  # FIX (2026-11-08): "" is ignored by sCTk labels -- a space clears

    def _save_decoder_port(self):
        """
        Saves the CW port for the program chosen -- into your own
        sdr_programs.json -- and listens on it at once if DEC is on.
        """
        profile = profile_for(gv.config.get_sdr_software())
        if self._decoder_port_kind(profile) != "udp":
            return
        text = self.decoder_port_entry.get().strip()
        usual = sdr_programs.shipped_setting(profile.key, "decoder_udp_port")
        if not text:
            value = None                        # back to the usual port
        elif not text.isdigit() or not 1 <= int(text) <= 65535:
            self.decoder_port_note.configure(text="a port is a number, 1 to 65535")
            return
        else:
            value = int(text)
            if usual is not None and value == int(usual):
                value = None                    # the usual one: no override needed
        now = profile.decoder_udp_port
        if (value or (int(usual) if usual else None)) == now:
            self._show_decoder_port()
            return
        fresh = sdr_programs.set_user_setting(profile.key, "decoder_udp_port", value)
        if fresh is None:
            self.decoder_port_note.configure(text="could not save -- see the console")
            return
        # The SDR link and its transport hold the profile they were made with.
        if self.sdr.profile.key == fresh.key:
            self.sdr.profile = fresh
            self.sdr.controller.profile = fresh
            if getattr(self.sdr, "_decoding", False):
                # Listening already: move to the new port now.
                self.sdr.controller.set_decoder(False)
                self.sdr.controller.set_decoder(True)
        print(f"[sdr] {fresh.name}'s decoded CW now expected on 127.0.0.1:"
              f"{fresh.decoder_udp_port}")
        self._show_decoder_port()

    def _sdr_advanced(self):
        """
        The SDR's finer settings, in a window of their own.

        The default filter widths to begin with. They are set once for a
        station and then left, so they do not earn a place on a page whose
        job is saying where the equipment is.
        """
        win = sCTkToplevel(self)
        win.title("SDR settings")
        self._over_app(win, 470, 540)   # FIX: taller, for the S-meter scale
        win.transient(self)

        body = sCTkFrame(win, fg_color="transparent", border_width=0)
        body.pack(fill="both", expand=True, padx=16, pady=14)
        sCTkLabelPrimary(body, text="Default filter widths").pack(anchor="w")
        sCTkLabelTertiary(
            body,
            text="What the SDR's filter returns to for each mode -- and what "
                 "a mode change sets, so an SSB filter is not carried into CW.",
            wraplength=380, justify="left").pack(anchor="w", pady=(2, 10))

        fields = {}
        for label, value in (("CW", gv.config.get_sdr_cw_filter_default_hz()),
                             ("SSB", gv.config.get_sdr_ssb_filter_default_hz())):
            line = sCTkFrame(body, fg_color="transparent", border_width=0)
            line.pack(anchor="w", pady=3)
            sCTkLabelTertiary(line, text=label, width=50, anchor="w").pack(side="left")
            field = sCTkEntryPrimary(line, width=90, height=SETTINGS_CONTROL_HEIGHT)
            field.pack(side="left")
            field.insert(0, str(value))
            sCTkLabelTertiary(line, text="Hz").pack(side="left", padx=6)
            fields[label] = field

        # FIX (2026-11-10): THE S-METER'S SCALE (Mark). The SDR's S-units
        # times this; the operator finds S9 with whatever source they trust.
        sCTkLabelPrimary(body, text="S-meter scale").pack(anchor="w", pady=(16, 0))
        sCTkLabelTertiary(
            body,
            text="The SDR's S-meter reading times this, 0 to 200 %. 100 % "
                 "leaves it as it is. Tune a signal you know is S9: if it "
                 "reads S7, set 9 / 7, about 129 %.",
            wraplength=400, justify="left").pack(anchor="w", pady=(2, 6))
        scale_row = sCTkFrame(body, fg_color="transparent", border_width=0)
        scale_row.pack(anchor="w")
        scale_field = sCTkEntryPrimary(scale_row, width=90, height=SETTINGS_CONTROL_HEIGHT)
        scale_field.pack(side="left")
        scale_field.insert(0, str(self._s_meter_scale_saved()))
        sCTkLabelTertiary(scale_row, text="%").pack(side="left", padx=6)

        # WHERE THE PROGRAM IS, for an install this does not know about. Empty
        # means the usual places for that program on this platform, which are
        # in sdr_programs.json along with everything else true of a program
        # rather than of this station.
        sCTkLabelPrimary(body, text="Where the program is").pack(anchor="w", pady=(16, 0))
        sCTkLabelTertiary(
            body,
            text="Only needed if starting it fails, or for rigctld, which "
                 "must be told which radio to use — give the whole command.",
            wraplength=400, justify="left").pack(anchor="w", pady=(2, 6))
        path_row = sCTkFrame(body, fg_color="transparent", border_width=0)
        path_row.pack(anchor="w", fill="x")
        path_field = sCTkEntryPrimary(path_row, width=280, height=SETTINGS_CONTROL_HEIGHT)
        path_field.pack(side="left")
        path_field.insert(0, gv.config.get_sdr_path())

        def browse():
            from tkinter import filedialog
            chosen = filedialog.askopenfilename(parent=win, title="The SDR program")
            if chosen:
                path_field.delete(0, "end")
                path_field.insert(0, chosen)

        sCTkButtonSecondary(path_row, text="Find…", width=70,
                            height=SETTINGS_CONTROL_HEIGHT,
                            command=browse).pack(side="left", padx=6)

        # WHERE TO ADD A PROGRAM. Nobody would find this file by looking, and
        # it is the whole point of having one: a program we have never heard
        # of can be driven by describing it.
        sCTkLabelTertiary(
            body,
            text=f"To add an SDR program, or change what is known about one, "
                 f"edit {shown_path(sdr_programs.USER_FILE)}; for its controls' "
                 f"ranges and labels, {shown_path(sdr_controls.USER_FILE)}. Each "
                 f"is merged over the one this application ships with.", wraplength=400,
            justify="left").pack(anchor="w", pady=(12, 0))

        def save():
            for name, setter in (("CW", gv.config.set_sdr_cw_filter_default_hz),
                                 ("SSB", gv.config.set_sdr_ssb_filter_default_hz)):
                try:
                    setter(int(fields[name].get()))
                except ValueError:
                    pass
            gv.config.set_sdr_path(path_field.get())
            try:
                self._set_s_meter_scale(float(scale_field.get()))   # FIX (2026-11-10)
            except ValueError:
                pass
            self._show_sdr_path()
            win.destroy()

        row = sCTkFrame(body, fg_color="transparent", border_width=0)
        row.pack(anchor="w", pady=(14, 0))
        # FIX: "Save", not "Keep" -- what the button does (2026-11-05).
        sCTkButtonPrimary(row, text="Save", width=80, command=save).pack(side="left", padx=(0, 6))
        sCTkButtonSecondary(row, text="Cancel", width=80,
                            command=win.destroy).pack(side="left")

    def _ask_to_close_their_sdr(self, name):
        """
        Asks whether to close a program the OPERATOR started.

        Their program, not ours -- so the answer is theirs. It is asked
        because an SDR dongle belongs to one program at a time: the one they
        opened holds it, and the one they have just chosen cannot start
        until it lets go.
        """
        return bool(sCTkMessagebox.askyesno(
            f"Close {name}?",
            f"{name} was already running when this started, and it is holding "
            f"the SDR device — so the program you have just chosen cannot "
            f"open it.\n\nClose {name}?",
            yes_text=f"Close {name}", no_text="Leave it", master=self))

    def _ask_to_force_sdr(self, name):
        """
        Asks whether to force a program that will not close.

        ONLY ASKED WHEN SWITCHING, and only after it has been asked to quit
        and refused: an SDR dongle belongs to one program at a time, so the
        old one holding on stops the new one from starting. Forcing can cost
        that program its settings -- Gqrx forgets which device it was using
        -- so the operator decides, and closing it themselves is the better
        answer if they can.
        """
        return bool(sCTkMessagebox.askyesno(
            f"{name} will not close",
            f"{name} has not closed and is still holding the SDR device, so "
            f"the program you have chosen cannot start.\n\n"
            f"Force it to close? Its own settings may not be saved — closing "
            f"it yourself is safer if you can.",
            yes_text="Force it", no_text="Leave it", master=self))

    def _save_autostart(self):
        """Whether to start the SDR program when this one starts."""
        gv.config.set_SDR_Autostart("1" if self.sdr_autostart.get() else "0")

    def _connect_sdr(self):
        """Saves what is on the page, and tries the SDR."""
        gv.config.set_sdr_host(self.sdr_host_entry.get())
        try:
            gv.config.set_sdr_port(int(self.sdr_port_entry.get()))
        except ValueError:
            pass
        # The link reads the address when it connects, but WHICH PROGRAM is
        # settled when it is built -- so it is told to read that again. The
        # link itself is not replaced: controls all over the window are bound
        # to its methods, and a new object would leave them talking to the old
        # one.
        # reload_profile deals with whatever is connected now -- closing a
        # program this application started, or merely disconnecting one that
        # was already running.
        self.sdr.reload_profile()
        if not gv.config.sdr_enabled():
            self._group_note(self.sdr_box, "none -- nothing is tried")
            self._show_sdr_status(False)
            return
        note = self.sdr.start_program()
        self._group_note(self.sdr_box, f"connecting to {self.sdr.profile.name}…"
                         + (f" ({note})" if note else ""))
        self.update_idletasks()
        if self.sdr.connect():
            self._group_note(self.sdr_box,
                             f"{self.sdr.profile.name}: "
                             f"{', '.join(sorted(self.sdr.capabilities)) or 'nothing'}")
        else:
            # It may only be slow to open its remote control -- keep trying
            # quietly rather than giving up at the first attempt.
            self._group_note(self.sdr_box,
                             f"waiting for {self.sdr.profile.name} at "
                             f"{gv.config.get_sdr_host()}:{gv.config.get_sdr_port()}…")
            self.sdr.connect_when_ready()

    # -- behaviour --------------------------------------------------------
    # FIX (2026-11-06): what a control says while the rig is locked.
    LOCKED_NOTE = "locked -- unlock to change"
    # The latched controls that stay live under lock: Lock itself, and TX off
    # -- practice mode is wanted most when nothing else may move.
    LIVE_WHEN_LOCKED = ("locked", "tx_inhibit")

    def _show_lock(self):
        """
        FIX (2026-11-06): THE RIG'S LOCK REACHES EVERY CONTROL HERE. It froze
        only the frequency dials; the band and mode, the VFO buttons, split,
        RIT, the filter, the listening aids and their knobs, volume, RF gain,
        the span and the receiver choice all went on working. Now they are
        greyed while locked, and their handlers refuse as well, for anything
        that slips past. Lock and TX off stay live. What changes IN THE SDR
        still shows here -- the SDR cannot be locked from here.
        Repainted only when the lock changes.
        """
        locked = bool(self.model.locked)
        if locked == getattr(self, "_lock_shown", None):
            return
        self._lock_shown = locked
        state = "disabled" if locked else "normal"
        self._show_filter_buttons()
        widgets = [btn for key, btn in self._toggles.items()
                    if key not in self.LIVE_WHEN_LOCKED]
        widgets += list(getattr(self, "_vfo_buttons", []))
        for name in ("band_picker", "mode_picker", "receiver_picker"):
            if getattr(self, name, None) is not None:
                widgets.append(getattr(self, name))
        for widget in widgets:
            try:
                widget.configure(state=state)
            except Exception:
                try:
                    widget.state(state)
                except Exception:
                    pass
        self.volume_knob.set_live(self._listen_source == "SDR" and not locked)
        self._offset_state = None           # the split offsets: see refresh
        self._lamp_live.clear()             # lamps, pop-up switches and notes
        self._switch_states.clear()
        self._bandwidth_shown = None
        self._show_rf_gain()
        self._draw_dsp_knobs()

    def _show_filter_buttons(self):
        """
        FIX (2026-11-06): wide, narrow and reset live only where the SDR has a
        filter AND the rig is not locked -- one place for both, so connecting
        (the SDR status button) no longer brought them back under lock.
        """
        live = "filter" in self.sdr.capabilities and not self.model.locked
        for btn in getattr(self, "filter_buttons", []):
            btn.state("normal" if live else "disabled")

    def _toggle(self, key):
        """
        Sends a command. Does NOT change the state -- the reply does that.
        """
        if self.model.locked and key not in self.LIVE_WHEN_LOCKED:
            return                          # FIX: see _show_lock
        # Through the CONNECTION, not the stub. Both were live and writing
        # to the same model, which is how a mode set by one and confirmed by
        # the other ends up arguing with itself.
        {"split": self.connection.Toggle_Split,
         # FIX (2026-11-08): the app keeps RIT itself in split -- see
         # uBITX_Link.toggle_rit_for_operator.
         "rit": self.connection.toggle_rit_for_operator,
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
            self.sdr.set_muted(not self.sdr.muted)
            self.refresh()
        else:
            self.connection.Toggle_Speaker()

    def _set_listen_source(self, source, by_operator=False):
        """
        Chooses which receiver you are listening through.

        LISTENING THROUGH THE SDR SILENCES THE RIG, and switching back restores
        it -- otherwise you hear both at once. On the uBITX that is the
        rig's own "SDR mode" (TS_CMD_SDR, which Toggle_Speaker sends): it
        routes the audio out for an SDR and quiets the speaker.

        The command is a TOGGLE, so it is sent only when the rig is not
        already where it needs to be, judged by model.muted.
        """
        if by_operator and self.model.locked:   # FIX: see _show_lock
            self.receiver_picker.set(self._listen_source)
            return
        self._listen_source = source
        if by_operator:
            self._listen_chosen = True
        rig_should_be_muted = (source == "SDR")
        # Only once built. Setting the picker's starting value must not
        # reach the rig: its state is not known yet, and a second toggle at
        # startup would cancel the first.
        if self._ready and self.model.muted != rig_should_be_muted:
            self.connection.Toggle_Speaker()
        self.volume_knob.set_live(source == "SDR" and not self.model.locked)
        # FIX (2026-11-06): THE SDR IS SILENCED WHILE LISTENING THROUGH THE
        # RIG, and given back as it was -- its own mute, or not -- when the
        # SDR is chosen again. Only the rig's speaker was switched before, so
        # in rig mode both were heard. Only an SDR with a mute of its own:
        # without one, muting means the COMPUTER's output, which is not ours
        # to silence for a choice of receiver.
        self._sdr_quiet_for_rig()
        self.refresh()

    def _sdr_quiet_for_rig(self):
        """
        Mutes the SDR in rig mode, remembering whether it was muted; in SDR
        mode puts that back. Safe to call again: each side acts once.
        """
        if not (self._ready and self.sdr.connected
                and MUTE in self.sdr.capabilities):
            return
        if self._listen_source == "Rig":
            if getattr(self, "_sdr_muted_before", None) is None:
                self._sdr_muted_before = bool(self.sdr.muted)
                if not self.sdr.muted:
                    self.sdr.set_muted(True)
        else:
            before = getattr(self, "_sdr_muted_before", None)
            self._sdr_muted_before = None
            if before is not None and bool(self.sdr.muted) != before:
                self.sdr.set_muted(before)

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

    def _swap(self):
        """
        Selects the other VFO -- the "A/B" button. (FIX 2026-11-08: it was
        labelled "A⇄B", which elsewhere means an exchange; see _exchange.)

        Swaps which VFO receives and which transmits.

        A TOGGLE, not an exchange of contents. The rig has no command to
        swap two VFOs' frequencies -- and it does not need one, because
        roles follow the active VFO: make the other one primary and receive
        and transmit trade places, which is the operational effect wanted.

        Doing it in the model instead was a lie the rig never heard. It
        looked right for a moment and then reverted, because the rig's own
        reports say where the frequencies actually are.
        """
        if self.model.locked:               # FIX: see _show_lock
            return
        self.connection.toggle_vfo()

    def _exchange(self):
        """
        FIX (2026-11-08): EXCHANGES A AND B -- frequency and mode -- leaving the
        same VFO active. A RIT goes with its contents. Not while transmitting.
        """
        m = self.model
        if m.locked or m.transmitting:
            return
        # FIX (2026-11-09): with RIT on too -- it goes with its VFO's
        # contents (Mark). See uBITX_Link.exchange_vfos.
        self.connection.exchange_vfos()

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
        if self.model.locked:               # FIX: see _show_lock
            return
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
        if self.model.locked:               # FIX: see _show_lock
            self.mode_picker.set(self.model.mode)
            return
        self.connection.set_mode_everywhere(value)

    # What the band picker shows out of every ham band.
    OFF_BAND = "\u2014"

    def _aim_band_arrows(self, hz):
        """
        Out of every band, aims the band picker's arrows from the frequency:
        up to the nearest band above it, down to the nearest below.

        The spinbox steps from the position of the last value it showed from
        its list, and "—" is not in the list -- so its arrows would step from
        the last band chosen, wherever the radio has gone since. Its position
        is set here to the band just below the frequency, which makes UP land
        on the band above; DOWN, which would then land one band too low, is
        corrected in _on_band. `_current_index` is the spinbox's own; it
        offers no other way to say where stepping starts.
        """
        bands = self.model.BANDS
        below = sum(1 for _, _, end in bands if hz and end < hz)
        self._off_band_below = below
        self.band_picker._current_index = below - 1

    def _on_band(self, *_):
        if self.model.locked:               # FIX: see _show_lock
            self.band_picker.set(self.model.band_name() or self.OFF_BAND)
            return
        label = self.band_picker.get()
        # From out of band, DOWN arrives one band too low -- see
        # _aim_band_arrows -- and is put on the band just below instead.
        below = getattr(self, "_off_band_below", None)
        names = [band[0] for band in self.model.BANDS]
        if below is not None and label in names and names.index(label) == below - 2:
            label = names[below - 1]
            self.band_picker.set(label)
        self._off_band_below = None
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
                # The SDR's view starts at the band's lower edge when the
                # rig gets there -- see SDR_Link.frame_band.
                self.sdr.frame_band(freq, endfreq)
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

    @staticmethod
    def _width_text(hz):
        return f"{hz / 1_000_000:g} MHz" if hz >= 1_000_000 else f"{hz / 1000:g} kHz"

    def _bandwidth_moved(self, value):
        """The bandwidth slider moved: the width shown at once, sent when it settles."""
        choices = self.sdr.bandwidth_choices()
        if not choices or self.model.locked:    # FIX: locked -- see _show_lock
            return
        width = choices[max(0, min(len(choices) - 1, int(round(value))))]
        self.bandwidth_label.configure(text=self._width_text(width))
        self._bandwidth_shown = (tuple(choices), width, True, False)
        # Held while it is sent: the SDR reports the old width until then,
        # and the slider would jump back mid-drag.
        self._bandwidth_held_until = time.monotonic() + 1.5
        self.sdr.set_bandwidth(width)

    def _show_bandwidth(self):
        """The bandwidth slider: the SDR's choices and width, or greyed. Only on a change."""
        slider = getattr(self, "bandwidth_slider", None)
        if slider is None or time.monotonic() < getattr(self, "_bandwidth_held_until", 0):
            return
        choices = tuple(self.sdr.bandwidth_choices())
        width = self.sdr.bandwidth if choices else None
        locked = bool(self.model.locked)
        shown = (choices, width, bool(choices), locked)
        if shown == self._bandwidth_shown:
            return
        self._bandwidth_shown = shown
        if choices:
            steps = max(1, len(choices) - 1)
            slider.configure(from_=0, to=steps, number_of_steps=steps,
                             state="disabled" if locked else "normal")
            nearest = min(range(len(choices)), key=lambda i: abs(choices[i] - (width or 0)))
            slider.set(nearest)
            self.bandwidth_label.configure(text=self._width_text(width or choices[nearest]))
        else:
            slider.configure(state="disabled")
            self.bandwidth_label.configure(text=" ")

    def _filter_reset(self):
        """Back to the configured default width for the current mode."""
        # The SDR's, not the rig's -- the uBITX has no filter command. The
        # defaults come from the configuration, so they match the Setup page.
        if not self.model.locked:           # FIX: see _show_lock
            self.sdr.reset_filter()

    # How far one press of "wide" or "narrow" moves the filter.
    #
    # CW: fine steps at and below FILTER_CW_FINE_HZ, where the filter is
    # closing in on one signal -- 300 at a time went from 500 straight to
    # 200. Above it the filter is opened to look around, and coarse steps
    # get there sooner. A coarse step down stops at FILTER_CW_FINE_HZ rather
    # than jumping past it, so narrowing always passes through it.
    # SSB: filters are thousands of hertz wide; one step size throughout.
    FILTER_CW_FINE_HZ = 500
    FILTER_STEP_CW_FINE_HZ = 100
    FILTER_STEP_CW_COARSE_HZ = 300
    FILTER_STEP_SSB_HZ = 300

    def _filter(self, direction):
        """One step wider (+1) or narrower (-1), sized for the mode and width."""
        if self.model.locked:               # FIX: see _show_lock
            return
        width = int(self.model.filter_hz or 0)
        mode = str(self.model.mode_of(self.model.rx_vfo)).upper()
        if not mode.startswith("CW"):
            target = width + direction * self.FILTER_STEP_SSB_HZ
        elif direction > 0:
            step = (self.FILTER_STEP_CW_FINE_HZ if width < self.FILTER_CW_FINE_HZ
                    else self.FILTER_STEP_CW_COARSE_HZ)
            target = min(width + step, max(width, self.FILTER_CW_FINE_HZ)) \
                if width < self.FILTER_CW_FINE_HZ else width + step
        elif width > self.FILTER_CW_FINE_HZ:
            target = max(width - self.FILTER_STEP_CW_COARSE_HZ, self.FILTER_CW_FINE_HZ)
        else:
            target = width - self.FILTER_STEP_CW_FINE_HZ
        self.sdr.set_filter(target)

    def _about(self):
        """
        Where the callsign and firmware version went.

        They were on the main screen's top line, sharing space with live
        state -- but neither changes, so neither earns a place you look at
        while operating. The file paths belong here too: you need them when
        something has gone wrong, not while working a pileup.
        """
        win = sCTkToplevel(self)
        win.title("About")
        self._over_app(win, 520, 300)
        win.transient(self)

        body = sCTkFrame(win, fg_color="transparent", border_width=0)
        body.pack(fill="both", expand=True, padx=18, pady=16)

        sCTkLabelPrimary(body, text="uBITX CEC Desktop").pack(anchor="w")
        sCTkLabelTertiary(body, text="a visual desktop for KD8CEC-powered uBITX radios").pack(anchor="w", pady=(0, 10))

        for label, value in (
            ("Version", "1.0  ·  June 2026"),
            ("Author", "Mark Hatch (AJ6CU)"),
            ("Email", "markjhatch@gmail.com"),
            ("Radio firmware", self.model.firmware),
            ("Configuration", shown_path(gv.config.configuration_file)),
            ("Logbook", "~/Downloads/ubitx_Logbook.adi"),
            ("Licence", "GPL v3"),
        ):
            line = sCTkFrame(body, fg_color="transparent", border_width=0)
            line.pack(anchor="w", pady=1)
            sCTkLabelTertiary(line, text=label, width=120, anchor="w").pack(side="left")
            sCTkLabelSecondary(line, text=value).pack(side="left")

        sCTkButtonSecondary(body, text="Close", width=80,
                            command=win.destroy).pack(anchor="w", pady=(14, 0))

    # FIX (2026-11-06): THE BACKUP TABLE'S ROWS, real ones. Each: a label,
    # the factory value's EEPROM name (or None -- the rig keeps no factory
    # copy), where the radio's value comes from, and the configuration
    # file's getter and setter. FACTORY VALUES ARE READ ONLY: nothing in the
    # app writes them (Mark).
    BACKUP_ROWS = (
        ("Master calibration", "factory_master_cal", ("eeprom", "master_cal"),
         "get_Master_Cal", "set_Master_Cal"),
        ("SSB BFO", "factory_ssb_bfo", ("eeprom", "ssb_bfo"), "get_SSB_BFO", "set_SSB_BFO"),
        ("CW BFO", None, ("eeprom", "cw_bfo"), "get_CW_BFO", "set_CW_BFO"),
        ("Key type", None, ("model", "cw_key_type"), "get_Keytype", "set_Keytype"),
        ("CW speed (wpm)", "factory_cw_wpm", ("model", "cw_wpm"), "get_CW_Speed", "set_CW_Speed"),
        ("Sidetone (Hz)", "factory_cw_sidetone", ("model", "cw_tone"), "get_CW_Tone", "set_CW_Tone"),
        ("Delay to TX (ms)", None, ("model", "cw_delay_tx_ms"),
         "get_CW_Delay_Before_TX", "set_CW_Delay_Before_TX"),
        ("Delay to RX (ms)", None, ("model", "cw_delay_rx_ms"),
         "get_CW_Delay_Returning_to_RX", "set_CW_Delay_Returning_to_RX"),
    )

    def _backup_values(self):
        """
        Each row's (factory, radio, config file) values, None where not known.
        Key types as the rig's words (STRAIGHT ...) whatever the file holds.
        """
        m = self.model
        rows = []
        for label, factory, (where, name), getter, _ in self.BACKUP_ROWS:
            f = m.eeprom_settings.get(factory) if factory else None
            if where == "eeprom":
                r = m.eeprom_settings.get(name)
            elif name == "cw_tone":
                r = m.cw_tone if m.cw_tone_reported else None
            else:
                r = getattr(m, name)
            try:
                c = getattr(gv.config, getter)()
            except Exception:                   # not in the file at all
                c = None
            rows.append((f, r, self._backup_normal(name, c)))
        return rows

    def _backup_normal(self, name, value):
        """A config file value in the radio's terms, so the two compare."""
        if value in (None, ""):
            return None
        if name == "cw_key_type":
            text = str(value).strip().upper().replace(" ", "")
            return {"0": "STRAIGHT", "1": "IAMBICA", "2": "IAMBICB"}.get(text, text)
        try:
            return int(str(value).strip())
        except ValueError:
            return str(value)

    def _backup_text(self, name, value):
        if value is None:
            return "—"
        if name == "cw_key_type":
            return self.CW_KEYERS.get(value, str(value))
        return str(value)

    def _eeprom_backup(self):
        """
        Compare and copy the radio's stored settings.

        Three places a value can live -- the factory default, what is in the
        radio now, and what is in the configuration file -- shown side by side
        so the differences are visible before anything is written.

        FIX (2026-11-06): REAL VALUES, both directions. The table was a
        mock-up of made-up numbers. The radio's calibration, BFOs and factory
        values are read from its EEPROM as the dialog opens (they fill in
        over a second or so); its CW values are the ones it reported at
        connect; the file's are the file's. COPY: the radio into the config
        file (a backup), or the config file into the radio (a restore --
        shown old -> new and confirmed first, the rig's word changing the
        radio column, a restart offered for what the rig reads only as it
        boots). The FACTORY column is never written (Mark).
        """
        win = sCTkToplevel(self)
        win.title("Radio settings — compare and copy")
        self._over_app(win, 700, 500)   # FIX (2026-11-11): taller, for the note's own line
        win.transient(self)

        body = sCTkFrame(win, fg_color="transparent", border_width=0)
        body.pack(fill="both", expand=True, padx=16, pady=14)

        # THE DIRECTION IS ABOVE THE COLUMNS, where the eye already is. The
        # two this table can do, as one choice -- not two drop-downs that
        # could name the factory column as a destination.
        # FIX (2026-11-06): Mark's wording.
        TO_FILE, TO_RADIO = "From the radio  →  Config file", "Config file  →  To the radio"
        # FIX (2026-11-06): THE FACTORY VALUES BACK INTO THE RADIO (Mark) --
        # read from the factory copy, written to the radio's own settings;
        # the factory copy itself is still never written. No factory -> file:
        # factory -> radio, then radio -> file, does that.
        FROM_FACTORY = "Factory  →  To the radio"
        direction = sCTkFrame(body, fg_color="transparent", border_width=0)
        direction.pack(anchor="w", pady=(0, 8))
        sCTkLabelTertiary(direction, text="copy").pack(side="left", padx=(0, 6))
        way = sCTkSegmentedButton(direction, values=[TO_FILE, TO_RADIO, FROM_FACTORY],
                                  command=lambda _v: repaint())
        way.set(TO_FILE)
        way.pack(side="left")
        # FIX (2026-11-11): on its own line, under the choice -- beside it the
        # row was wider than the 700-point window and the note was cut off
        # ("ifferences are mark", Mark).
        sCTkLabelTertiary(body, text="Differences are marked.").pack(anchor="w", pady=(0, 8))

        # FIX (2026-11-11): 2 / 8, not 1 / 6 -- at a 1-point border and
        # radius 6, CustomTkinter's drawn corners left a gap where each arc
        # meets the straight side (Mark); 2 / 8 closes it.
        table = sCTkFrame(body, border_width=2, corner_radius=8)
        table.pack(fill="both", expand=True)
        head = sCTkFrame(table, fg_color="transparent", border_width=0)
        head.pack(fill="x", padx=8, pady=(6, 2))
        for text, width in (("", 30), ("Setting", 150), ("Factory", 120),
                            ("In the radio", 130), ("Config file", 130)):
            sCTkLabelTertiary(head, text=text, width=width, anchor="w").pack(side="left")
        rows_frame = sCTkFrame(table, fg_color="transparent", border_width=0)
        # FIX (2026-11-11): padx -- packed edge to edge, the rows' own
        # background covered the table's 1-point border down both sides,
        # leaving only the rounded top and bottom (Mark).
        rows_frame.pack(fill="x", padx=4)

        # The ticks, kept across repaints -- rows are rebuilt as values arrive.
        ticks = [tk.BooleanVar(value=False) for _ in self.BACKUP_ROWS]
        state = {"shown": None}

        status_line = sCTkFrame(body, fg_color="transparent", border_width=0)
        status_line.pack(anchor="w", pady=(8, 0))
        status = sCTkLabelTertiary(status_line, text="", wraplength=560, justify="left")
        status.pack(side="left")
        restart = sCTkButtonSecondary(status_line, text="Restart rig",
                                      command=lambda: self.connection.restart_rig())

        def to_radio():
            return way.get() in (TO_RADIO, FROM_FACTORY)

        def source_of(f, r, c):
            """The column the chosen direction copies FROM."""
            return {TO_FILE: r, TO_RADIO: c, FROM_FACTORY: f}[way.get()]

        def radio_live():
            return self.rig_state == "connected" and not self.model.locked

        def repaint():
            state["shown"] = None
            paint()

        def paint():
            values = self._backup_values()
            m = self.model
            pending = sorted(set(m.settings_pending) | set(m.cw_pending))
            shown = (tuple(values), m.settings_state, tuple(m.settings_failed),
                     self.rig_state, m.locked, way.get(), tuple(pending),
                     m.cw_write_failed)
            if shown == state["shown"]:
                return
            state["shown"] = shown
            for child in rows_frame.winfo_children():
                child.destroy()
            for i, ((label, _, (_, name), _, _), (f, r, c)) in enumerate(
                    zip(self.BACKUP_ROWS, values)):
                line = sCTkFrame(rows_frame, fg_color="transparent", border_width=0)
                line.pack(fill="x", padx=8, pady=1)
                # A CHECKBOX, not a switch: picking rows is selection. Only
                # a row with a value to copy FROM can be ticked -- and copying
                # into the radio needs a radio to write to, unlocked.
                box = sCTkCheckBox(line, text="", width=30, variable=ticks[i])
                box.pack(side="left")
                source = source_of(f, r, c)
                if source is None or (to_radio() and not radio_live()):
                    ticks[i].set(False)
                    box.configure(state="disabled")
                sCTkLabelTertiary(line, text=label, width=150, anchor="w").pack(side="left")
                sCTkLabelTertiary(line, text=self._backup_text(name, f), width=120,
                                  anchor="w").pack(side="left")
                # A value that differs from the one beside it is the reason
                # for looking at this table: the TIER marks it, no font.
                differs = r is not None and c is not None and r != c
                cell = sCTkLabelSecondary if differs else sCTkLabelTertiary
                cell(line, text=self._backup_text(name, r), width=130,
                     anchor="w").pack(side="left")
                cell(line, text=self._backup_text(name, c), width=130,
                     anchor="w").pack(side="left")
            notes = []
            if self.rig_state != "connected":
                # FIX (2026-11-06): WHY, from the connection's own note --
                # "no radio" covered a port that would not open and a rig
                # that did not answer alike.
                notes.append(f"Radio not available ({self.rig_note}) -- only the "
                             f"file's values are shown.")
            elif m.settings_state == "reading":
                notes.append("Reading the radio's calibration and factory values…")
            elif m.settings_failed:
                notes.append("The radio did not answer for: " + ", ".join(m.settings_failed))
            if m.locked and to_radio():
                notes.append(self.LOCKED_NOTE)
            if pending:
                labels = [lbl for lbl, _, (_, name), _, _ in self.BACKUP_ROWS if name in pending]
                notes.append("Saved in the radio, used after a restart: " + ", ".join(labels) + ".")
            if m.cw_write_failed:
                notes.append("The radio did not confirm a write -- it may not be saved.")
            status.configure(text="  ".join(notes) or " ")  # FIX (2026-11-08): "" is ignored
            if pending and radio_live():
                restart.pack(side="left", padx=(10, 0))
            else:
                restart.pack_forget()

        def watch():
            if not win.winfo_exists():
                return
            paint()
            win.after(250, watch)

        def select_all():
            on = every.get()
            for i, (f, r, c) in enumerate(self._backup_values()):
                source = source_of(f, r, c)
                ticks[i].set(on and source is not None
                             and (not to_radio() or radio_live()))

        def copy():
            """The ticked rows, in the direction chosen."""
            if to_radio():
                restore()
                return
            # The radio's values into the configuration file.
            values = self._backup_values()
            copied = []
            for i, ((label, _, (_, name), _, setter), (f, r, c)) in enumerate(
                    zip(self.BACKUP_ROWS, values)):
                if ticks[i].get() and r is not None:
                    getattr(gv.config, setter)(r)
                    copied.append(label)
                    ticks[i].set(False)
            state["shown"] = None
            paint()
            status.configure(text=("Copied to the config file: " + ", ".join(copied))
                             if copied else "Nothing ticked.")

        def restore():
            """
            The ticked rows' config file -- or factory -- values into the
            radio, whichever direction is chosen -- after
            showing old -> new and asking: these can put the rig off
            frequency or silence it. Rows already the same are left out.
            Sent through the link's writers, which refuse a value out of
            range; the radio column changes when the rig acknowledges.
            """
            if not radio_live():
                return
            changes = []
            for i, ((label, _, (_, name), _, _), (f, r, c)) in enumerate(
                    zip(self.BACKUP_ROWS, self._backup_values())):
                source = source_of(f, r, c)
                if ticks[i].get() and source is not None and source != r:
                    changes.append((label, name, r, source))
            if not changes:
                status.configure(text="Nothing to write: the ticked rows already match.")
                return
            lines = "\n".join(f"{label}:  {self._backup_text(name, r)}  →  "
                               f"{self._backup_text(name, c)}"
                               for label, name, r, c in changes)
            sure = sCTkMessagebox.askyesno(
                "Write to the radio",
                f"Write these to the radio's EEPROM?\n\n{lines}\n\n"
                "Calibration, BFOs, tone and delays take effect after a restart.",
                yes_text="Write", no_text="Cancel", master=win)
            if not sure:
                return
            refused = []
            for label, name, r, c in changes:
                try:
                    if name in uBITX_Link.STORED_LIMITS:
                        self.connection.set_stored(name, c)
                    else:
                        self.connection.set_cw(name, c)
                except (ValueError, KeyError):
                    refused.append(label)
            for t in ticks:
                t.set(False)
            repaint()
            if refused:
                status.configure(text="Not written (out of range, or a place the "
                                      "rig cannot be written): " + ", ".join(refused))

        footer = sCTkFrame(body, fg_color="transparent", border_width=0)
        footer.pack(anchor="w", pady=(10, 0))
        every = tk.BooleanVar(value=False)
        sCTkCheckBox(footer, text="Select all", variable=every,
                     command=select_all).pack(side="left", padx=(0, 16))
        sCTkButtonPrimary(footer, text="Copy selected", width=120,
                          command=copy).pack(side="left", padx=(0, 6))
        sCTkButtonSecondary(footer, text="Close", width=80,
                            command=win.destroy).pack(side="left")

        # Read the radio as the dialog opens: the values may have changed
        # since the last time, and the read costs a second at most.
        if self.rig_state == "connected":
            self.connection.read_settings()
        watch()

    # ------------------------------------------------------------------
    # FIX (2026-11-06): THE CALLSIGN, EEPROM SETTINGS AND MACHINE SETTINGS
    # ------------------------------------------------------------------
    def _show_callsign(self):
        """
        The Station group's callsign: the rig's, as it reported it -- or the
        one just written, waiting on a restart, with a note saying so.
        Not repainted while the operator is typing in it.
        """
        entry = getattr(self, "callsign_entry", None)
        if entry is None:
            return
        m = self.model
        pending = m.settings_pending.get("callsign")
        text = pending[0] if pending else self._rig_callsign()
        shown = (text, bool(pending), self.rig_state)
        if shown == self._callsign_shown:
            return
        try:
            if self.focus_get() is entry._entry:
                return
        except Exception:
            pass
        self._callsign_shown = shown
        entry.delete(0, "end")
        entry.insert(0, text)
        self.callsign_note.configure(text="(after a restart)" if pending else "" or " ")  # FIX (2026-11-08): "" is ignored by sCTk labels -- a space clears

    def _rig_callsign(self):
        """
        The callsign the rig reported (sc), or "" -- never the model's seed,
        which is only a placeholder until the rig has spoken.
        """
        if "sc" not in getattr(self.connection, "seen_reports", ()):
            return ""
        return self.model.callsign

    def _callsign_entered(self):
        """
        A callsign typed in the Station group goes to the rig's EEPROM, keeping
        its show-at-start-up choice (EEPROM settings). Refused, the field is
        put back and the note says why.
        """
        m = self.model
        text = self.callsign_entry.get().strip().upper()
        pending = m.settings_pending.get("callsign")
        current = pending[0] if pending else self._rig_callsign()
        self._callsign_shown = None
        if text == current.strip().upper():
            self._show_callsign()
            return
        if self.rig_state != "connected" or m.locked:
            self.callsign_note.configure(text="(no rig to write to)" if not m.locked
                                         else "(locked)")
            self.after(3000, self._show_callsign)
            return
        head = m.eeprom_settings.get("callsign_head")
        if head is None:
            # FIX (2026-11-06): THE SHOW-AT-START-UP FLAG IS KEPT. It lives in
            # the same byte as the length, so writing without knowing it
            # would quietly turn it off. Not read yet this session: read it
            # first, then write.
            self.callsign_note.configure(text="(reading the rig…)")
            if m.settings_state != "reading":
                self.connection.read_settings()
            self._callsign_waits = getattr(self, "_callsign_waits", 0) + 1
            if self._callsign_waits <= 40:            # 10 s
                self.after(250, lambda t=text: self._callsign_retry(t))
            else:
                self._callsign_waits = 0
                self.callsign_note.configure(text="(the rig did not answer -- not written)")
            return
        self._callsign_waits = 0
        show = bool(head[0] == uBITX_Link.CALLSIGN_KEY and head[1] & 0x80)
        try:
            self.connection.set_callsign(text, show)
        except ValueError:
            self.callsign_note.configure(text="(letters, digits and / only, 18 at most)")
            self.after(4000, self._show_callsign)
            return
        self.callsign_note.configure(text="(writing…)")

    def _callsign_retry(self, text):
        """The callsign write again, once the rig's flag has been read."""
        if self.callsign_entry.get().strip().upper() != text:
            self._callsign_waits = 0
            return                                   # typed over: start again
        self._callsign_entered()

    def _rig_eeprom_settings(self):
        """
        The rig's own settings that live in its EEPROM and have nowhere else
        in the app: whether it shows the callsign at start-up, and the
        S-METER -- whether it sends its reports at all (off, the meter stays
        empty listening through the rig) and the eight levels the radio
        S-meter sensor's reading
        is compared with, from KD8CEC's map (uBITX_Link.RIG_EEPROM).

        Read from the rig as the dialog opens; Apply lists old -> new and
        asks, then writes; the rig takes them as it boots, so a restart is
        offered. Nothing is written without Apply.
        """
        win = sCTkToplevel(self)
        win.title("EEPROM settings")
        self._over_app(win, 560, 520)
        win.transient(self)
        body = sCTkFrame(win, fg_color="transparent", border_width=0)
        body.pack(fill="both", expand=True, padx=16, pady=14)

        show_call = tk.BooleanVar(value=False)
        meter_on = tk.BooleanVar(value=False)
        sCTkLabelSecondary(body, text="Callsign").pack(anchor="w")
        call_line = sCTkFrame(body, fg_color="transparent", border_width=0)
        call_line.pack(anchor="w", pady=(2, 10))
        call_box = sCTkCheckBox(call_line, text="Show the callsign as the rig starts",
                                variable=show_call)
        call_box.pack(side="left")
        sCTkLabelTertiary(call_line, text="  (the callsign itself: Setup, Station)").pack(side="left")

        # FIX (2026-11-06): "radio S-meter sensor", not "A7" -- the operator's
        # name for it, not the Nano's pin (Mark).
        sCTkLabelSecondary(body, text="Radio S-meter sensor").pack(anchor="w")
        # FIX (2026-11-06): WHEN IT IS USED (Mark). Only listening through the
        # radio: through an SDR the meter shows the SDR's own reading, and the
        # rig sends no sensor reading in its SDR mode anyway. An SDR with no
        # reading (SDR++) leaves the meter empty -- it does not fall back to
        # this sensor.
        sCTkLabelTertiary(body, text="Used only when you listen through the radio "
                          f"(now: {'the SDR' if self._listen_source == 'SDR' else 'the radio'}). "
                          "Through an SDR the meter shows the SDR's own reading instead; "
                          "with an SDR that has none (SDR++), the meter stays empty.",
                          wraplength=520, justify="left").pack(anchor="w", pady=(0, 4))
        meter_box = sCTkCheckBox(body, text="Send S-meter reports -- needed for the meter "
                                 "and for scanning on a signal through the rig",
                                 variable=meter_on)
        meter_box.pack(anchor="w", pady=(2, 6))
        levels_line = sCTkFrame(body, fg_color="transparent", border_width=0)
        levels_line.pack(anchor="w")
        level_entries = []
        for i in range(8):
            cell = sCTkFrame(levels_line, fg_color="transparent", border_width=0)
            cell.pack(side="left", padx=(0, 6))
            sCTkLabelTertiary(cell, text=f"step {i + 1}").pack()
            e = sCTkEntryPrimary(cell, width=48)
            e.pack()
            level_entries.append(e)
        sCTkLabelTertiary(body, text="Each step is reached when the sensor's reading, 0-255, "
                          "passes its level -- so they rise from step 1 to step 8.",
                          wraplength=520, justify="left").pack(anchor="w", pady=(4, 0))
        # FIX (2026-11-06): THE WARNING, always in view (Mark): levels never
        # calibrated make the meter useless, all zeros worst of all.
        sCTkLabelSecondary(body, text="Levels of all 0 make every signal read about S9, and "
                           "scanning on a signal then stops everywhere. If you listen through "
                           "the radio's own S-meter sensor, calibrate these levels.",
                           wraplength=520, justify="left").pack(anchor="w", pady=(4, 0))

        status_line = sCTkFrame(body, fg_color="transparent", border_width=0)
        status_line.pack(anchor="w", pady=(12, 0))
        status = sCTkLabelTertiary(status_line, text="", wraplength=420, justify="left")
        status.pack(side="left")
        restart = sCTkButtonSecondary(status_line, text="Restart rig",
                                      command=lambda: self.connection.restart_rig())
        state = {"shown": None, "filled": False}

        def rig_values():
            e = self.model.eeprom_settings
            head, opt, levels = (e.get("callsign_head"), e.get("display_option1"),
                                 e.get("smeter_levels"))
            show = None if head is None else bool(head[0] == uBITX_Link.CALLSIGN_KEY
                                                  and head[1] & 0x80)
            on = None if opt is None else bool(opt[0] & uBITX_Link.SMETER_DISPLAY_BIT)
            return show, on, (list(levels) if levels else None), (opt[0] if opt else None)

        def paint():
            m = self.model
            show, on, levels, _ = rig_values()
            live = self.rig_state == "connected" and not m.locked
            shown = (show, on, tuple(levels or ()), m.settings_state, live,
                     tuple(sorted(m.settings_pending)), m.cw_write_failed)
            if shown == state["shown"]:
                return
            state["shown"] = shown
            # The fields are filled from the rig ONCE, when its values arrive --
            # not again, so what the operator is typing is not overwritten.
            if not state["filled"] and m.settings_state == "read":
                state["filled"] = True
                show_call.set(bool(show)); meter_on.set(bool(on))
                for e, v in zip(level_entries, levels or [""] * 8):
                    e.delete(0, "end"); e.insert(0, str(v))
            for w in [call_box, meter_box] + level_entries:
                w.configure(state="normal" if live and state["filled"] else "disabled")
            notes = []
            if self.rig_state != "connected":
                notes.append(f"Radio not available ({self.rig_note}).")
            elif m.settings_state == "reading":
                notes.append("Reading the rig…")
            elif m.locked:
                notes.append(self.LOCKED_NOTE)
            # FIX (2026-11-06): say so when the rig's own levels cannot work,
            # and how they fail.
            note = self._smeter_levels_problem(levels)
            if note:
                notes.append(note)
            mine = [k for k in ("callsign", "display_option1", "smeter_levels")
                    if k in m.settings_pending]
            if mine:
                notes.append("Saved in the rig -- it uses them after a restart.")
            if m.cw_write_failed:
                notes.append("The rig did not confirm a write -- it may not be saved.")
            status.configure(text="  ".join(notes) or " ")  # FIX (2026-11-08): "" is ignored
            if mine and live:
                restart.pack(side="left", padx=(10, 0))
            else:
                restart.pack_forget()

        def watch():
            if not win.winfo_exists():
                return
            paint()
            win.after(250, watch)

        def apply():
            m = self.model
            if self.rig_state != "connected" or m.locked or not state["filled"]:
                return
            show, on, levels, option = rig_values()
            # FIX (2026-11-06): THE LEVELS ARE CHECKED ONLY IF CHANGED. They
            # were checked every time, so a rig whose stored levels do not
            # rise (never set, or erased) refused EVERY Apply -- turning the
            # S-meter reports on, or the callsign flag, forced setting levels
            # first (Mark). Left as the rig has them, they are not written.
            new_levels, problem = self._smeter_levels_entered(
                [e.get().strip() for e in level_entries], levels)
            if problem:
                status.configure(text=problem)
                return
            changes = []
            if new_levels is not None:
                changes.append(("S-meter levels", " ".join(map(str, levels)),
                                " ".join(map(str, new_levels)),
                                lambda: self.connection.set_rig_bytes("smeter_levels", new_levels)))
            if on is not None and meter_on.get() != on:
                byte = (option | uBITX_Link.SMETER_DISPLAY_BIT) if meter_on.get() \
                    else (option & ~uBITX_Link.SMETER_DISPLAY_BIT)
                changes.append(("S-meter reports", "on" if on else "off",
                                "on" if meter_on.get() else "off",
                                lambda b=byte: self.connection.set_rig_bytes("display_option1", [b])))
            if show is not None and show_call.get() != show:
                call = self._rig_callsign()
                if not call:
                    status.configure(text="Set a callsign first (Setup, Station).")
                    return
                changes.append(("Show callsign at start", "yes" if show else "no",
                                "yes" if show_call.get() else "no",
                                lambda: self.connection.set_callsign(call, show_call.get())))
            if not changes:
                status.configure(text="Nothing changed.")
                return
            lines = "\n".join(f"{label}:  {old}  →  {new}" for label, old, new, _ in changes)
            if not sCTkMessagebox.askyesno(
                    "Write to the rig", f"Write these to the rig's EEPROM?\n\n{lines}\n\n"
                    "The rig uses them after a restart.",
                    yes_text="Write", no_text="Cancel", master=win):
                return
            for *_, write in changes:
                try:
                    write()
                except ValueError as err:
                    status.configure(text=f"Not written: {err}")
            state["shown"] = None

        footer = sCTkFrame(body, fg_color="transparent", border_width=0)
        footer.pack(anchor="w", pady=(14, 0))
        sCTkButtonPrimary(footer, text="Apply", width=90, command=apply).pack(side="left", padx=(0, 6))
        sCTkButtonSecondary(footer, text="Close", width=80, command=win.destroy).pack(side="left")
        if self.rig_state == "connected":
            self.connection.read_settings()
        watch()

    @staticmethod
    def _smeter_levels_problem(levels):
        """
        What is wrong with the rig's stored S-meter levels, in words -- or
        "" when they rise as they must. (The firmware takes the highest step
        whose level the sensor's reading is ABOVE.)
        """
        if not levels or all(b > a for a, b in zip(levels, levels[1:])):
            return ""
        if all(v == 0 for v in levels):
            return ("The rig's S-meter levels are all 0: every signal reads about S9. "
                    "Calibrate them before relying on the radio S-meter sensor.")
        if all(v == 255 for v in levels):
            return ("The rig's S-meter levels are all 255 (never set): the radio "
                    "S-meter will always read S0. Calibrate them.")
        return ("The rig's S-meter levels do not rise from step 1 to step 8, so the "
                "radio S-meter cannot show steps properly. Calibrate them.")

    @staticmethod
    def _smeter_levels_entered(texts, levels):
        """
        (levels to write, or None for no change; a reason they are refused,
        or None). See the FIX in _rig_eeprom_settings: only changed levels
        are checked, so the rest of the dialog works whatever the rig holds.
        """
        if levels is not None and texts == [str(v) for v in levels]:
            return None, None
        try:
            new = [int(t) for t in texts]
        except ValueError:
            return None, "Each level must be a whole number, 0-255."
        if any(not 0 <= v <= 255 for v in new):
            return None, "Each level must be 0-255."
        if any(b <= a for a, b in zip(new, new[1:])):
            return None, "The levels must rise from step 1 to step 8."
        return (None if new == levels else new), None

    # The headroom choices, in ms -- the original application's list.
    HEADROOM_CHOICES_MS = ("40", "50", "60", "70", "80", "90", "100", "110",
                           "150", "160", "170", "180", "190", "200")

    def _headroom_setting(self):
        """The command headroom from the settings, in seconds, kept in range."""
        try:
            value = float(gv.config.get_MCU_Command_Headroom())
        except (TypeError, ValueError, KeyError, AttributeError):
            value = MCU_COMMAND_HEADROOM
        return max(MCU_COMMAND_HEADROOM, min(MCU_COMMAND_HEADROOM_MAX, value))

    @staticmethod
    def _timing_setting():
        """The saved timings, {name: ms}; {} -- the defaults -- if none."""
        try:
            saved = gv.config.config_data.get(TIMING_KEY, {})
        except AttributeError:
            return {}
        return saved if isinstance(saved, dict) else {}

    def _machine_settings(self):
        """
        The settings about the link to the rig itself -- advanced use. The
        COMMAND HEADROOM: the least gap between two commands to the Nano, set
        here, used at once and saved. POWER/SWR: kept, greyed -- there is no
        sensor yet (a future Pico board).

        Of the original application's other machine settings, the update
        period and read wait belonged to its polling loop -- the reader now
        takes bytes as they come -- and DSP lives in SDR settings.
        """
        win = sCTkToplevel(self)
        win.title("Machine settings -- advanced use")
        self._over_app(win, 560, 640)
        win.transient(self)
        body = sCTkFrame(win, fg_color="transparent", border_width=0)
        body.pack(fill="both", expand=True, padx=16, pady=14)

        line = sCTkFrame(body, fg_color="transparent", border_width=0)
        line.pack(anchor="w")
        sCTkLabelSecondary(line, text="Command headroom (ms)", width=180, anchor="w").pack(side="left")
        headroom = sCTkComboBox(line, values=list(self.HEADROOM_CHOICES_MS), width=90, state="readonly")
        headroom.set(str(int(round(self._headroom_setting() * 1000))))
        headroom.pack(side="left")
        sCTkLabelTertiary(body, text="The least time between two commands to the rig. "
                          "Too short and a fast spin of the dial can overrun the Nano; "
                          "longer is safer and slower. 40 is the least.",
                          wraplength=480, justify="left").pack(anchor="w", pady=(4, 12))

        sCTkLabelSecondary(body, text="Power and SWR").pack(anchor="w")
        pwr = tk.BooleanVar(value=str(gv.config.get_PWR_SWR_Switch()) == "True")
        pwr_line = sCTkFrame(body, fg_color="transparent", border_width=0)
        pwr_line.pack(anchor="w", pady=(2, 0))
        sCTkCheckBox(pwr_line, text="Power/SWR meter", variable=pwr,
                     state="disabled").pack(side="left", padx=(0, 12))
        for label, getter in (("PWR factor", gv.config.get_PWR_Factor),
                              ("SWR factor", gv.config.get_SWR_Factor)):
            sCTkLabelTertiary(pwr_line, text=label).pack(side="left", padx=(0, 4))
            e = sCTkEntryPrimary(pwr_line, width=50)
            e.insert(0, str(getter()))
            e.configure(state="disabled")
            e.pack(side="left", padx=(0, 10))
        sCTkLabelTertiary(body, text="Needs a power/SWR sensor -- a future Pico board.",
                          ).pack(anchor="w", pady=(2, 12))

        # FIX (2026-11-06): ADVANCED TIMING -- the link's other timings that
        # depend on the Nano's speed (ubitx_link.TIMING_SETTINGS). The
        # defaults are the values tuned at the station; leave them unless a
        # slow or unusual Nano drops commands.
        sCTkLabelSecondary(body, text="Advanced timing").pack(anchor="w")
        sCTkLabelTertiary(body, text="For a slow or unusual Nano only -- the defaults were "
                          "tuned at the station. Out-of-range values are kept in range.",
                          wraplength=500, justify="left").pack(anchor="w", pady=(2, 4))
        in_use = ubitx_link.apply_timing(self._timing_setting())
        timing_entries = {}
        grid = sCTkFrame(body, fg_color="transparent", border_width=0)
        grid.pack(anchor="w")
        for row, (name, label, default, low, high) in enumerate(ubitx_link.TIMING_SETTINGS):
            sCTkLabelTertiary(grid, text=label, width=220, anchor="w").grid(row=row, column=0, sticky="w")
            e = sCTkEntryPrimary(grid, width=64)
            e.insert(0, str(in_use[name]))
            e.grid(row=row, column=1, sticky="w", pady=1)
            sCTkLabelTertiary(grid, text=f"{low}-{high}, default {default}").grid(
                row=row, column=2, sticky="w", padx=8)
            timing_entries[name] = e

        def reset_timing():
            for name, _, default, _, _ in ubitx_link.TIMING_SETTINGS:
                timing_entries[name].delete(0, "end")
                timing_entries[name].insert(0, str(default))

        status = sCTkLabelTertiary(body, text="")
        status.pack(anchor="w", pady=(8, 0))

        def apply():
            seconds = int(headroom.get()) / 1000
            gv.config.set_MCU_Command_Headroom(seconds)
            self.connection.command_headroom = self._headroom_setting()
            used = ubitx_link.apply_timing({n: e.get() for n, e in timing_entries.items()})
            for name, e in timing_entries.items():      # show what was kept
                e.delete(0, "end"); e.insert(0, str(used[name]))
            try:
                gv.config.config_data[TIMING_KEY] = used
                gv.config.saveConfig()
            except AttributeError:
                pass
            status.configure(text=f"Saved and in use -- headroom {int(seconds * 1000)} ms.")

        footer = sCTkFrame(body, fg_color="transparent", border_width=0)
        footer.pack(anchor="w", pady=(10, 0))
        sCTkButtonPrimary(footer, text="Apply", width=90, command=apply).pack(side="left", padx=(0, 6))
        sCTkButtonSecondary(footer, text="Reset timing", width=110,
                            command=reset_timing).pack(side="left", padx=(0, 6))
        sCTkButtonSecondary(footer, text="Close", width=80, command=win.destroy).pack(side="left")

    def _over_app(self, win, width, height):
        """
        FIX (2026-11-06): the app's dialogs -- Log QSO, About, SDR settings,
        the radio-settings compare -- opened at the top left of the screen,
        since only their size was given. Now centred over the app's window,
        kept on the screen it is on.
        """
        self.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + (self.winfo_height() - height) // 3
        x = max(0, min(x, self.winfo_screenwidth() - width))
        y = max(0, min(y, self.winfo_screenheight() - height))
        win.geometry(f"{width}x{height}+{x}+{y}")

    def _log_qso(self):
        """
        The log dialog: everything known is filled in, and the only field
        needing typing has the focus.

        FIX (2026-11-10): IT WRITES. The Log button only closed the dialog --
        nothing reached the logbook (Mark). Now the QSO goes to the file
        Setup > Logbook names (logbook.append_qso: ADIF or CSV, the old
        application's format, duplicates refused, backed up per the interval),
        and the dialog says what happened. Every field is editable -- a QSO is
        often logged a little after it ends -- and the time is UTC, as logs
        are kept. Only while logging is on: the button is greyed otherwise.
        """
        if not self._logging_on():
            return
        win = sCTkToplevel(self)
        win.title("Log QSO")
        self._over_app(win, 360, 400)
        win.transient(self)

        body = sCTkFrame(win, fg_color="transparent", border_width=0)
        body.pack(fill="both", expand=True, padx=16, pady=14)

        s = self.model
        now = datetime.now(timezone.utc)
        cw = str(s.mode).upper().startswith("CW")
        fields = (
            ("call", "Callsign", ""),
            ("freq", "Frequency (MHz)", f"{s.frequency(s.tx_vfo) / 1_000_000:.6f}"),
            ("band", "Band", logbook.adif_band(s.band_name(s.tx_vfo))),
            ("mode", "Mode", logbook.adif_mode(s.mode)),
            ("qso_date", "Date (UTC, YYYYMMDD)", now.strftime("%Y%m%d")),
            ("time_on", "Time (UTC, HHMM)", now.strftime("%H%M")),
            ("rst_sent", "RST sent", "599" if cw else "59"),
            ("rst_rcvd", "RST received", "599" if cw else "59"),
        )
        entries = {}
        for key, label, value in fields:
            line = sCTkFrame(body, fg_color="transparent", border_width=0)
            line.pack(fill="x", pady=2)
            sCTkLabelTertiary(line, text=label, width=150, anchor="w").pack(side="left")
            entry = sCTkEntryPrimary(line, width=150)
            entry.pack(side="left")
            entry.insert(0, value)
            entries[key] = entry
        entries["call"].focus_set()

        status = sCTkLabelTertiary(body, text=" ", wraplength=320, justify="left")
        status.pack(anchor="w", pady=(8, 0))

        def log(_event=None):
            qso = {key: entry.get().strip() for key, entry in entries.items()}
            path = self._logbook_path()
            try:
                minutes = float(gv.config.get_Logbook_Backup_Interval() or 0)
            except (AttributeError, TypeError, ValueError):
                minutes = 0
            ok, message = logbook.append_qso(path, qso, minutes)
            print(f"[log] {message} ({path})")
            if ok:
                win.destroy()
            else:
                status.configure(text=message)

        row = sCTkFrame(body, fg_color="transparent", border_width=0)
        row.pack(anchor="w", pady=(10, 0))
        sCTkButtonPrimary(row, text="Log", width=80, command=log).pack(side="left", padx=(0, 6))
        sCTkButtonSecondary(row, text="Cancel", width=80,
                            command=win.destroy).pack(side="left")

        win.bind("<Return>", log)
        win.bind("<Escape>", lambda e: win.destroy())

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

        self._rig_answered_late()

        # The two frequency panels re-read themselves.
        self.panel_rx.update_view(s)
        self.panel_tx.update_view(s)
        self._show_lock()
        self._show_log_button()  # FIX (2026-11-10): greyed while logging is off
        self._show_cw()          # FIX (2026-11-06): the keyer, as reported
        self._show_front_end()   # FIX (2026-11-10): ATT and IFS, as reported
        self._show_callsign()    # FIX (2026-11-06): the rig's callsign

        # Latched controls read as lit or unlit.
        # FIX: PRESSED, not recoloured. Setting fg_color was overwritten
        # whenever the theme repainted the button -- the lamps' lesson -- and
        # set_pressed is the library's own "on" look. Repainted only on a
        # change.
        for key, btn in self._toggles.items():
            on = bool(getattr(s, key))
            if on != self._toggle_shown.get(key):
                self._toggle_shown[key] = on
                btn.set_pressed(on)
        # TX off: the alarm colour while on, not pressed.
        inhibited = bool(s.tx_inhibit)
        if inhibited != self._toggle_shown.get("tx_inhibit"):
            self._toggle_shown["tx_inhibit"] = inhibited
            self.tx_off_button.set_alarm_state(inhibited)

        # The listening aids' lamps and switches. (Guarded inside: refresh
        # can run before the Operate tab is built.)
        self._show_lamps()
        self._show_volume()
        self._show_bandwidth()
        self._show_decode_strip()

        # The split offsets are live only in split. state() repaints, so it
        # is called only when the answer changes.
        # FIX: and not while locked -- see _show_lock.
        live = bool(s.split) and not s.locked
        if self._offset_state != live:
            self._offset_state = live
            for btn in self._offset_buttons:
                btn.state("normal" if live else "disabled")

        # FIX (2026-11-08): a passing message under the buttons -- see _exchange.
        message = getattr(self, "_offset_message", None)
        if message and time.monotonic() < message[1]:
            self.offset_note.configure(text=message[0])
        elif s.split:
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
        #
        # OUT OF EVERY BAND IT SHOWS "—", not the last band chosen, which
        # named a band the radio was not in. And its arrows are aimed from
        # where the radio IS -- see _aim_band_arrows.
        band_now = s.band_name()
        shown = band_now or self.OFF_BAND
        if self.band_picker.get() != shown:
            self.band_picker.set(shown)
        if band_now:
            self._off_band_below = None
        else:
            self._aim_band_arrows(s.role_frequency("rx"))

        # The mode button follows the model too. It only changed when clicked,
        # so a mode set anywhere else -- the SDR, or the rig's own buttons --
        # reached the model and never showed: the filter moved, the transmit
        # readout moved, and the button went on naming the old mode.
        #
        # Safe for the same reason as the band picker: a segmented button's
        # set() does not fire its command, so this cannot loop back into
        # _on_mode.
        if s.mode and self.mode_picker.get() != s.mode:
            self.mode_picker.set(s.mode)

        self.filter_label.configure(text=f"{s.filter_hz} Hz")
        self._refresh_channels()
        self.channel_now.configure(
            text=f"{s.role_text('rx')}   {s.mode}")

        # Meters. The receive side goes quiet on transmit and the transmit
        # side wakes up -- one instrument, two halves, neither ever dead.
        self._update_s_meter()
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
    radio = UbitxCecDesktop()

    # EVERY WAY OUT THAT CAN BE CAUGHT leads to close_down(), which is safe
    # to call twice. Leaving by one of them without closing down means the
    # rig's port stays open and an SDR this application started is left
    # running -- which is what happened when only the window's close button
    # did the work, and the operator quit from the menu instead.
    #
    #   the close button      -> _on_close
    #   quitting another way  -> the finally below, when the main loop ends
    #   an unhandled error    -> the same finally
    #   Ctrl-C, or an IDE's stop button (SIGINT, SIGTERM) -> _leave
    #   anything else that lets Python exit normally      -> atexit
    #
    # SIGKILL cannot be caught by anything, so a process killed outright
    # still leaves both behind. Nothing can be done about that from here.
    atexit.register(radio.close_down)

    def _leave(number, frame):
        print(f"[app] signal {number} -- closing down")
        radio.close_down()
        raise SystemExit(0)

    for _signal in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(_signal, _leave)
        except (ValueError, OSError):
            pass                        # not the main thread, or not supported

    try:
        radio.mainloop()
    finally:
        radio.close_down()