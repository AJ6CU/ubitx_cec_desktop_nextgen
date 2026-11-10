## TODO

Outstanding work on sCustomTkinter and the uBITX CEC Desktop interface, with
enough context that an item can be picked up cold.

Items are grouped by kind rather than priority. Where something was decided
and then deferred, the reasoning is recorded too -- several of these look
straightforward until you meet the thing that stopped them last time.

---

### Table of Contents
* [Library code](#library-code)
* [Documentation](#documentation)
* [Pygubu Designer](#pygubu-designer)
* [Naming](#naming)
* [Not yet examined](#not-yet-examined)
* [The uBITX interface](#the-ubitx-interface)
* [The application](#the-application)
* [Much later](#much-later)
* [Things worth not relearning](#things-worth-not-relearning)

---

<a name="library-code"></a>
### Library code

**The canvas widgets do not scale their fonts.** `sCTkSMeter`,
`sCTkSMeterBar` and `sCTkSelector` draw text on canvases and never call
`_apply_font_scaling`, so their labels stay the same size while everything
around them grows on a scaled display. `sCTkNotebook` and
`sCTkFrequencyDisplay` do it correctly and are worth copying.

A canvas text item takes a plain font tuple, which CustomTkinter's own font
scaling never sees -- so a widget that draws rather than packing labels has
to scale the font itself or it silently opts out.

**`_raw_theme_block()` on `ThemeableWidget`.** The dials, the S-meters and
sCTkNotebook all read `_tw.GLOBAL_THEME_REGISTRY` directly, because
`final_kw` has had the vector keys stripped out of it by the time they want
them. Every one of them repeats the same six lines. A shared accessor would
remove the duplication and give one place to document why reading `final_kw`
is wrong.

**Backfit `_THEME_TRACKED_KEYS`.** `sCTkScrollbar` originated the override
recording pattern under this name and has since been moved to the shared
`_record_theme_overrides()`. The constant is still declared and still read by
its query branch. Either finish the migration or document why it stays.

**The triplicated dial scroll handlers.** `sCTkDialContinuous`,
`sCTkDialRange` and `sCTkDialSelector` each carry their own copy of the
wheel and trackpad handling. They have already diverged once. The base class
is the right home.

**Guard the deferred callbacks against teardown.** Closing a preview produces
`invalid command name "...<lambda>"` from `after()` and `after_idle()` calls
firing after their widget is destroyed. Harmless, but it buries real errors
in the console. Every deferred call needs a `winfo_exists()` check at the top
or its id cancelled on `<Destroy>`: entry view scrolling, scroll rebinding,
state repaints, the dial's binding injection, the file explorer's fill.

**`_custom_current_state` should be `_state`.** Two names for one thing across
the library. A rename with no behaviour change.

**Does any other widget's `set()` fire its command?** `sCTkSpinbox.set()` did,
which made construction order load-bearing -- setting an initial value called
back into an interface that did not exist yet. It now stays quiet and only
user-driven paths emit, matching CustomTkinter. `sCTkDialRange.set()`,
`sCTkDialSelector.set()` and `sCTkSelector` are worth the same check.

**`sCTkOptionMenu*`'s border redraw forces a whole-window layout** (found
2026-11-06, cProfile of the app's startup). `sctk_optionmenu_border_mixin.
_redraw_border` calls `update_idletasks()`, so one `configure()` of an option
menu lays out the entire window there and then -- 2.2 s at the app's startup,
almost all of it CustomTkinter scrollbars redrawing. Redraw on `<Configure>`
instead, or measure without forcing a layout. The app now avoids it at
startup (the Channels tab's set menu is set only once the tab is shown), but
any configure while the layout is stale pays it.

**Labelled frames are scrollable frames, and those are expensive to build.**
Each `CTkScrollableFrame` costs ~0.18 s, mostly its scrollbar -- the Setup
tab's five labelled boxes, whose scrollbars are hidden anyway, are most of its
1.7 s. A labelled frame that does not scroll could skip the scrollable frame.

**Should `sCTkTextboxSecondary` have a border?** It has `border_width: 0` and
no `border_color`, which is deliberate -- it is how it differs from Primary,
which has a visible frame. Setting a border colour in the Designer therefore
appears to do nothing. Adding one means both keys plus a
`disabled_map.border_color`, values lighter than Primary's so the tiers stay
distinguishable, and an edit to `sCTkTextboxSecondary.md`, which currently
states the absence as a design choice.

---

<a name="documentation"></a>
### Documentation

**Check the README directory tree against reality.** It has not been verified
since the structure changed.

**Screenshots for `sCTkNotebook.md`.** The page references
`images/sCTkNotebook_Dark.png` and `_Light.png`, which do not exist yet.

**Record the Tk and CustomTkinter name collisions** in `Developing.md` --
see [Things worth not relearning](#things-worth-not-relearning) below. Four
were hit in a single session and each cost a debugging round.

**User documentation tidbits -- ubitx_cec_desktop.** Things to put in the
operator's guide when it is written, collected here as they come up:

* *Undoing a session's channel edits* (Mark, 2026-11-06). Edits to the app's
  channel sets save at once, with no undo. Before a session's first change
  the app keeps the file as it was in
  `~/.ubitx_cec_desktop/channels.json.bak` -- one copy, replaced by each
  session's first change. To go back: quit the app, copy
  `channels.json.bak` over `channels.json`, start again. To keep or move
  channels, copy `channels.json`.
* *Terminology* (Mark, 2026-11-06): the rig's S-meter input is the "radio
  S-meter sensor" -- never "A7", the Nano pin it is wired to.
* *S-meter levels*: stored in the rig's EEPROM; never calibrated they are
  useless (all 0 reads everything as S9, all 255 always S0). Set them in
  EEPROM settings if listening through the radio's sensor; the SDR's meter
  is scaled in the app instead. The sensor is used only when listening
  through the radio -- never through an SDR, even one without a reading.
* *RIT and VFO A/B*: the rig has one RIT and switching VFOs turns it off;
  the app puts it back, with its offset, when you return to that VFO.
* *RIT and split*: in split RIT applies to the receive VFO and is kept by
  the app (the firmware's would ignore split on transmit); transmit stays on
  the other VFO. Turning split off makes it the rig's own RIT. There is no
  XIT.
  A⇄B takes each VFO's RIT along with its frequency and mode.
* *A/B, A⇄B, A→B*: A/B selects the other VFO; A⇄B exchanges the two VFOs'
  frequency and mode; A→B copies A onto B. Brown's A<->B is an exchange too,
  and the rig follows it.
* *Starting on VFO A*: the app restarts the rig as it connects, and the
  KD8CEC firmware always starts on VFO A (not saved in EEPROM) -- so the rig,
  and an SDR with two VFOs, come up on A whatever they were on (Mark, 2026-11-08:
  accepted as is).
* *Settings that stay in SDRoxide's own window* -- the APF lift, the NR
  engine and the rest rigctl cannot reach; see the SDRoxide section below.

**Anchors: `id` rather than `name`.** Some renderers ignore `name` on an empty
anchor, so a table of contents entry silently fails. Where the heading text
matches the link, the auto-generated slug works without an explicit anchor at
all. Worth a sweep across the widget pages.

---

<a name="pygubu-designer"></a>
### Pygubu Designer

**Four upstream reports are written and ready to file.** Plus the preview
image issue.

**Adding a button to a labelled frame fails in the Designer** (found
2026-11-05). Putting a plain button inside sCTkFrameLabeledPrimary or
-Secondary breaks both the design canvas and the preview; the same button
inside sCTkScrollableFrame works. Not traced yet. NOT caused by the
2026-11-05 border fix (`_clear_right_border()`): Mark tried the previous
release of sCustomTkinter and it fails the same way. So it is the
Designer's, or the labelled frames' builder objects' -- start there, with
the traceback from both the design canvas and the preview.

**A clear-rebuild mixin.** Clearing a property the theme never defined now
sends `""`, which `configure()` drops -- that stops the crash but cannot
remove a colour already applied to the native widget, so the design canvas
keeps showing it while the generated code is correct. The fix is a small
mixin providing `_set_property` with a `recreate_widget()` call on clear,
inherited by each builder object as it is touched. `sCTkSelectorBO` and
`sCTkNotebookTabBO` already do this by hand for structural properties and
would fold into it. Documented meanwhile in `DesignerHints.md`.

---

<a name="naming"></a>
### Naming

**`type` → `selection_type`** on `sCTkFileExplorer` and `sCTkPathChooser`.
`type` shadows the builtin and reads as a data type rather than a choice
between file and directory. Cheap while no `.ui` files depend on it.

---

<a name="not-yet-examined"></a>
### Not yet examined

**`sctk_treeview.py`** is the only widget the audit never reached, and it
predates the current architecture entirely: its imports name modules that do
not exist, it calls `ThemeableWidget.__init__` with a signature that has
changed, it has no `configure()`, `cget()`, `state()` or query branch, and it
targets `self._treeview` where the underlying widget is `self.tree` -- so its
theming has never run. A test harness sits at the bottom of the module
importing itself.

It also depends on `CTkTreeview`, a third-party package. That decision comes
first:

* **Vendor it.** MIT licensed and small. `sCTkFileExplorer` and
  `sCTkSelector` are both derived work already, so there is precedent. Gives
  full control over theming, state and the query form.
* **Depend on it.** Less work, but users install a third package and the
  widget can only be themed from outside.
* **Drop it.** `sCTkTableview` covers flat rows. The treeview earns its place
  only if hierarchy or in-place cell editing is wanted.

Worth knowing whichever way it goes: the upstream does **no ttk styling at
all** -- not a single `ttk.Style` call in 900 lines -- so the tree renders in
ttk's defaults and ignores CustomTkinter entirely. That is the actual work,
and it is unlike any other widget here: a named `ttk.Style`, `style.map()`
for selection colours, a layout override to remove the border, and a
reconfigure on appearance-mode change, since ttk will not track it. Named
styles are process-global, so two differently themed treeviews need distinct
style names.

---

<a name="the-ubitx-interface"></a>
### The uBITX interface

**Finish the redesign.** The mockup is now the working desktop
(`ubitx_cec_desktop.py`): Operate, RX and Channels are built and talk to the
rig and SDR++. Still to do, roughly in order of value:

* ~~The rig connection, on the Setup tab.~~ **Done.** The port comes from the
  settings, the Setup page lists what is plugged in (labelled by chip, with
  "show all" for anything the filter hides), a network rig is typed into the
  same field as `socket://host:port`, and the application opens on Setup when
  there is nothing to talk to rather than failing before a window exists. The
  four outcomes -- nothing chosen, will not open, opened but silent,
  connected -- each say their own thing.

  Left over from it: **`socket://` does not understand an IPv6 address.**
  `parse_rig_port` splits the host from the port on the last colon, which is
  wrong for `socket://[::1]:8080`. The old `comportManager` had the same
  fault from the other side -- it validated IPv6 and then rejected it. Worth
  fixing when somebody asks for it; nobody has.

* **The meters.** *S-meter and scan-on-signal DONE 2026-11-06
  (scan_signal.zip; Skip, hold level kept), working at the station.* Mark: an A7 sensor is assumed
  (the extra I2C Nano is not supported going forward); without an SDR the
  rig's A7 reading is used, with one the SDR's signal report where it has
  one (not SDR++). `cp_` now sets model.s_value through RIG_S_STEPS (KD8CEC
  sends a STEP 0-8, only when it changes, only with the S-meter display
  option on and outside SDR mode -- KD8CEC ubitx_lcd_nextion.ino idle_process).
  The scanner (scanner.py) can HOLD on a signal: "hold on S[n]" beside the
  dwell on the Channels tab -- a channel whose level reaches n is held as
  long as it stays and left SIGNAL_HANG_MS (3 s) after it drops; a reading
  is believed only SIGNAL_SETTLE_MS after arriving; unticked, or with no
  reading (SDR++), it scans by time and the operator presses Stop.
  test_scan_signal.py 12/12 (0/10 on the old files). A SKIP button beside
  Scan (Mark, 2026-11-06): on to the next channel now, held or not. The threshold is
  kept in channels.json beside the dwell (starter_sets.zip).
  Left: `al_` (the malformed S-meter report) stays unwired; RIG_S_STEPS is a
  first guess at what each step means. *Power/SWR (`vm_`):* no sensor yet --
  a future Pico board will have one; the meter's other half stays empty.
* ~~**Settings dialogs**~~ -- DONE 2026-11-06, checked at the station (Mark),
  final zip smeter_when.zip. From the Main branch's Machine and General dialogs, only
  what still does something: (a) the STATION CALLSIGN on Setup is the rig's
  (sc report; never the model's seed) and a changed one is written to EEPROM
  -- 780: key 0x59, bit 7 show-at-start + length, text, one write (Mark:
  "can we update it in eeprom?" -- yes); (b) EEPROM SETTINGS (Other
  Settings): show the callsign at start-up, the S-METER REPORTS switch
  (display option 361, bit 0x08 -- off, the rig sends no `cp` at all) and
  the 8 S-METER LEVELS (230-237), read on opening, Apply lists old -> new
  and asks, restart offered; (c) MACHINE SETTINGS: the COMMAND HEADROOM,
  Main's 40-200 ms list, used at once and saved -- the link no longer
  hardcodes 0.04 (40 ms is the floor); PWR/SWR switch and factors shown
  greyed until the Pico sensor. Dropped as doing nothing now: MCU Update
  Period and Read Wait (the old polling loop), Number delimiter, Virtual
  keyboard, VFO touch-optimized. Addresses from KD8CEC's ubitx_eemap.h,
  read in C byte order (flag 0x59); every write under the checksum limit.
  NOTE: Mark's settings file holds a headroom of 0.09 from the old app --
  now in use; set 40 in Machine settings to go back to the old pacing.
  test_rig_settings.py 10/10 (0/8 on the old files). FIXED same day (Mark:
  "being forced to set levels"): the levels were checked on every Apply, so
  a rig whose stored levels do not rise (never set, or erased) refused any
  change -- now checked only when changed; the dialog says when the rig's
  levels cannot work.
  ADVANCED TIMING (Mark, 2026-11-06; machine_timing.zip): Machine settings
  also sets the link's Nano-speed timings -- step settle, follow-up delay,
  frequency follow, frequency confirm / transmit write / EEPROM read and
  write timeouts, EEPROM read pace, retries (ubitx_link.TIMING_SETTINGS,
  ranges and defaults; apply_timing sets the module's constants, applied at
  connect, saved under "Link Timing"; Reset timing). Defaults unchanged.
  CALLSIGN FIX: the show-at-start-up flag shares a byte with the length, so
  the write now reads it first if not yet read -- before, writing from
  Station without opening EEPROM settings would have turned it off.
  test_rig_settings.py 12/12.
  WARNING + WORDS (Mark, 2026-11-06; smeter_warning.zip): EEPROM settings
  always shows that all-0 levels read every signal as about S9 and to
  calibrate if listening through the radio's sensor; the status line says
  which way the rig's own levels fail (all 0 -> S9, all 255 -> S0, not
  rising). TERMINOLOGY: the operator sees "radio S-meter sensor", never
  "A7" (the Nano's pin) -- for the docs too. test_rig_settings.py 14/14.
  The dialog also says WHEN the sensor is used (Mark): only listening through
  the radio; through an SDR the meter shows the SDR's reading (the rig sends
  none in its SDR mode); an SDR without one (SDR++) leaves the meter empty --
  no fall-back to the sensor.
  ANSWERS for the docs: the Station callsign is the rig's sc report, which
  the firmware sends from EEPROM at boot; a changed one goes to EEPROM, not
  settings.json, and shows on the rig after a restart. All-zero S-meter
  levels: any A7 reading above 0 passes every step, so the rig reports step
  8 (about S9) almost always -- the meter pins and scan-on-signal holds on
  every channel; the levels must be set for the meter to mean anything.
  The SDR's S-meter is scaled in the app (sdr_link: S9_DBFS -44 dBFS, 6 dB
  per S-unit -- a guess from the noise floor) unless the SDR reports
  relative to S9 itself (SDRoxide's STRENGTH); the rig's levels calibrate
  only the rig's A7 meter. DONE 2026-11-10 (s_meter_scale.zip), Mark's
  way: no calibration routine -- an S-METER SCALE, 0-200 %, in Setup > SDR
  settings, saved under Preferences ("s_meter_scale_pct"), 100 % being the
  -44 dBFS / 6 dB-per-S as before. SDR_Link.s_units() is multiplied by it
  (so the scanner's hold-on-signal threshold moves with it too). The
  operator finds S9 with whatever source they trust: S9 reading S7 wants
  9/7, ~129 %. test smscale/test_s_meter_scale.py 5/5 (2/5 on the old
  files). The rig's eight levels from the SDR's reading -- DROPPED (Mark,
  2026-11-10): the two are not connected; the eight levels serve only the
  rig's own S-meter sensor, which is not used while the SDR is enabled. Not done: a live A7
  reading to calibrate against (the firmware's ADC command loops until the
  next command, and its `vn` reports collide with the write acknowledgement);
  the Appearance choice on Station -- DONE 2026-11-10 (appearance.zip):
  Dark / Light / Follow system, saved under Preferences ("appearance"),
  Follow system by default (Mark), applied before the window is built and
  live from Setup. sCTk carries light and dark colours itself; CustomTkinter
  switches them. Follow system: macOS and Windows 10/11 follow the OS
  setting live; on Linux it depends on the desktop (GNOME-style settings
  are read; where nothing can be read, CustomTkinter shows Light -- choose
  Dark there). test appear/test_appearance.py 4/4 (0/4 on the old file).
* **Machine and general settings dialogs (Mark, 2026-11-06).** The S-meter
  calibration (sMeterLevels) and many other machine and general settings
  need dialogs to set them -- they are in the original Main branch, to be
  brought across. RIG_S_STEPS belongs with the S-meter calibration.
  THE OLD APP'S FILE, ~/.ubitx_cec_desktop.ini (seen 2026-11-06), lists
  what it kept. Already set somewhere in this app: Serial Port; SDR,
  SDR Software, SDR Autostart, Radio IP/Port, SDR SSB/CW/Filter widths;
  DSP; the Logbook five; Master Cal, SSB BFO, CW BFO and the five CW values
  (backup dialog, CW tab). READ BUT NOT SETTABLE: MCU Command Headroom,
  MCU Read Wait Period, MCU Update Period (the link hardcodes the headroom),
  NUMBER DELIMITER, PWR SWR switch with PWR/SWR Factor (waits for the Pico
  sensor). NOT IN THIS APP AT ALL -- keep, move, or drop, Mark to say:
  Callsign, CW Copy VFOA to VFOB on Split, TXOffset ("EEPROM"), VFO Touch
  Optimized, Virtual Keyboard Switch, Audio Gain Volume Level. State, not
  settings: Last Active Frequency, SDR Current Mode. The old scanner's
  Scan On Station Time and Scan Set Settings are replaced by channels.json.
* **Starter channel sets (Mark, 2026-11-06) -- DONE (starter_sets.zip).**
  Importing the old .ini's banks was dropped: they were dummies, so the
  offer was no use. Instead the app ships starter_channels.json beside the
  code -- "Time signals" (WWV 5/10/15/20/25 MHz, CHU 3330/7850/14670 kHz,
  USB at the carrier), "CW calling" (the QRP CW calling frequencies 80-10 m,
  CWL below 10 MHz) and "FT8" (the standard dial frequencies 80-10 m, USB) --
  put into channels.json when the operator has NO sets (the first start, or
  a file with none), ONCE: "starter_sets_given" is kept, so deleted starter
  sets do not come back. ChannelSets.add_starter_sets, called at start-up.
  Also: the scan's HOLD LEVEL is kept in channels.json beside the dwell.
  test_starter_sets.py 10/10 (0/7 on the old files). Mark checked the sets at
  the station 2026-11-06. ONE BACKUP (Mark): channels.json.bak, the file as
  it was before the session's first change -- set edits save at once with no
  undo, so this is the way back. Only one kept; a session that changes
  nothing leaves it alone (channel_bak.zip).
* ~~**The CW tab**~~ DONE 2026-11-06, checked at the station (cw_edit.zip) -- key type (`ck_`), speed (`vs_`), sidetone, the two delays
  (`vy_`, `ve_`) and the offset switch (`ch_`). SEEN 2026-11-05: the Keyer
  segmented button is not set from EEPROM -- nothing on the tab is: its
  fields are typed-in placeholders ("500", "10", "250", "1000"), the keyer
  button is not even kept, and the model has no fields for these. Wiring
  needs model fields, the handlers storing (speed arrives as 1200/wpm,
  delays in 10 ms and 2 ms units, key type a word), refresh() showing them,
  edits sending the setters.
  STEP 1 DONE 2026-11-06 (cw_values.zip): the five values the rig sends
  at connect are stored in the model (cw_key_type, cw_wpm, cw_delay_tx_ms,
  cw_delay_rx_ms; cw_tone_reported beside cw_tone) in the operator's units,
  and the tab shows them READ-ONLY, "--" until reported, key chosen on the
  Keyer button (greyed). test_cw_values.py 7/7. To check at the station:
  the values match the Nextion's, and what ck_ really sends (0/1/2 assumed).
  Step 1 CONFIRMED at the station 2026-11-06: all values read correctly.
  STEP 2 DONE 2026-11-06 (cw_edit.zip): the tab is editable -- Return or
  leaving a field sends it, the Keyer button sends its choice; range shown
  beside each field; refused (and put back) out of range; read-only when
  locked or no rig. ubitx_link.set_cw replaces the five never-called
  Set_CW_* (Set_CW_Speed's live command was a byte short). Speed and key
  type: the live command (TS_CMD_WPM, TS_CMD_KEYTYPE) then the EEPROM write;
  tone and delays: the EEPROM write only, using EEPROM.py's addresses. THE
  MODEL CHANGES ON THE ACKNOWLEDGEMENT (vn_ names the address), one write
  at a time, retried twice. Tone and delays are read only at boot, so they
  wait in model.cw_pending -- shown in the field, a note says so, and a
  "Restart rig" button offers the reboot (never automatic); the reports
  after the boot clear them. The live cw_tone (the CW TX offset) is not
  changed until then. Values as the rig stores them: delays in whole 2 ms /
  10 ms, speed through the dot length (45 wpm reads back 44). Speed limited
  to 5-60 wpm: the live command carries the dot length in one byte.
  test_cw_values.py 18/18 (1/18 on the old files). CHECKED AT THE STATION
  2026-11-06: the edits take, and Restart rig works. Also 2026-11-05: the Practice mode switch and
  the disabled Decoder button were REMOVED from the tab -- TX off on
  Operate is the one control, and decoding is DEC. Mostly WIRING: every setter
  already exists in the link -- `Set_CW_Tone`, `Set_CW_Keytype`,
  `Set_CW_Speed`, `Set_CW_Delay_Starting_TX`, `Set_CW_Delay_Returning_To_RX`
  -- and so does every handler; the handlers print and their model writes are
  commented out.

  What the old `cwSettings.py` knows that the link does not say:

  * **THREE OF THEM NEED A REBOOT to take effect** -- the sidetone and both
    delays. Key type and speed apply at once. The old dialog applied the
    changes, slept 1.5 seconds so they reached EEPROM, then offered to
    reboot. Now that `reboot_ubitx()` exists, the tab can offer the same --
    and must not do it silently: a reboot drops the operator off the air.
  * **Key type is a WORD, not a number**: "STRAIGHT", "IAMBICA", "IAMBICB".
  * **The choices live in `globalvars`** -- `CW_Sidetone_Values`,
    `CW_WPM_Values`, `Start_TX_Values`, `Delay_Return_RX_Values` -- and the
    old dialog adds whatever EEPROM actually holds to the list when it is not
    one of them, rather than silently showing the nearest. Worth keeping:
    a rig set to 437 Hz should not read as 425.
  * **"Copy VFO A to B on split" is a SETTING, not the rig's** -- it belongs
    with the configuration, not on this tab's rig controls.
* **The RX tab** -- ATT (`vf_`) and IFS (`ci_`, `vi_`). BUILT 2026-11-10
  (att_ifs_none.zip). ATT AND IFS CONFIRMED at the station 2026-11-10 (Mark);
  "-none-" not yet reported. A switch and a slider
  each, KD8CEC menu limits (ATT 0-250 in 5s, 0 = off; IFS -20000..20000 Hz
  in 50s); live only listening through the rig, rig connected, not locked --
  else greyed with a line saying why. The rig leads: the model changes on
  its reports (the firmware applies any command with setFrequency and
  reports what changed). Switch sent at once, slider once it rests (200 ms),
  shown value held 1.5 s. ATT on from 0 goes to the last level or 50; moving
  the IFS slider turns IFS on. FIXED: Set_IFS_Level sent the fourth byte as
  0 -- a negative shift would have arrived as about +16 MHz; now signed 32
  bits. uBITX_Link.set_att / set_ifs (value, then the toggle a settle later).
  ALSO (Mark): the SDR choice "-none-" (sdr_programs.NONE_CHOICE), first and
  the default; with it Connect, Start it, address and port are greyed
  (_show_sdr_fields), and choosing it applies at once -- an SDR in use let
  go, listening switched to the rig. test_att_ifs.py 8/8 (0/8 on the old
  files). (test_cw_values.py's stale case: passes 18/18 as of 2026-11-10.
  The lock test's stand-in got `toggle_rit_for_operator`: 10/10.)
* ~~Lock, mute and TX-stop are handled as toggles.~~ DONE 2026-11-06: all
  three report their STATE, checked on the rig -- lock 1/0, TX off 1/0,
  speaker 1 in SDR mode (muted) and 0 in speaker mode. The handlers read it
  now, as split and RIT do (rig_states.zip, test_rig_states.py 6/6).
* ~~The CW offset switch (`ch_`)~~ -- DROPPED 2026-09-27: not needed with
  receive and transmit shown side by side; each panel says what it is.
* **HELP (Mark, 2026-11-10) -- BUILT (help_page.zip), to check.** A local page,
  help/index.html beside the program, opened in the browser by the HELP
  button (where "on top" was) -- no internet needed. Getting started (what
  you need; installing KD8CEC 1.2, Nextion build, two routes; the USB-to-TTL
  adapter -- PLACEHOLDER for photos and wiring, the firmware's pins noted
  from source: adapter RX to D9, TX to D8, GND, no VCC -- to confirm; first
  start; SDR setup per program), Operate, RX, Channels, CW, Setup, and when
  things go wrong. Screenshots: placeholders that turn into the picture once
  a file of that name is in help/images/ -- the list in help/SHOTLIST.md;
  Mark takes them (no display here). "To fill in" boxes: hex file names and
  the upload steps, ubitx.h and IDE screenshots, each SDR program's server
  setting, an SDRangel guide. KEEP ON TOP moved to Setup > Station as a
  switch, saved under "Preferences" and ON by default. test_help.py 3/3.
* **LOG QSO WROTE NOTHING -- FIXED 2026-11-11 (log_qso.zip), to check.**
  The new window's dialog was a mock-up: Log only closed it (Mark:
  ~/uBITX_Logbook.adi never changed). New logbook.py -- the old app's
  QSOLogger without its hidden tk.Tk() and message boxes: ADIF or CSV, the
  same nine fields and ADIF header (an existing logbook carries on),
  duplicates (call, date, time, band) refused, a timestamped backup at most
  once per interval. The dialog: every field editable (call, frequency,
  band, mode as ADIF -- CW/SSB --, date and time in UTC, RSTs 599/59),
  Return logs, Escape cancels, the reason shown if refused. Log QSO is
  GREYED while Setup's Logbook switch is off (Mark), with a hover saying
  so. test_logbook.py 9/9 (0/9 on the old files).
* **Log QSO, the Setup tab, EEPROM backup and restore.** Setup's fields do
  not yet read or save the configuration -- including the MCU headroom, which
  the link hardcodes as 0.04 while the settings file holds its own value.
  *EEPROM backup, step 1 DONE 2026-11-06 (eeprom_backup.zip):* the "Radio
  settings -- compare and copy" dialog shows REAL values. On opening it reads
  master cal, SSB BFO, CW BFO and the factory cal, SSB BFO, CW speed and
  sidetone from EEPROM (ubitx_link.read_settings: one read at a time, paced
  and retried like the channel reads, never alongside them; the cal decoded
  SIGNED); the radio's CW values are the ones reported at connect; the
  config file's from configuration.py. Copy goes RADIO -> CONFIG FILE only
  (ticked rows). test_eeprom_backup.py 7/7 (0/7 on the old files).
  CONFIRMED at the station 2026-11-06: reading and copying to the file work.
  *Step 2, restore, DONE 2026-11-06 (eeprom_restore.zip):* a direction
  choice above the table (radio -> file, file -> radio); file -> radio
  lists old -> new and asks before writing; CW values go through set_cw,
  cal and BFOs through the new set_stored (limits from globalvars' bounds,
  the cal as 32-bit two's complement), same write queue and acknowledgement.
  All but speed/key type wait on a restart -- the dialog says which and
  offers Restart rig; restart_rig clears the cal/BFO waits. Not while
  locked or with no rig. FOUND: _eeprom_write read memOffset, which the cal
  and BFO entries in EEPROM.py do not have -- it would have raised; fixed.
  test_eeprom_backup.py 11/11. At the station: key type and master cal
  restore and stick; THE CW BFO DID NOT.
  WHY (KD8CEC source, ubitx_lcd_nextion.ino, TS_CMD_WRITEMEM): the firmware
  compares the checksum BYTE with addr0 + addr1 + length as an int -- no
  % 256 -- so any write whose sum reaches 256 is refused, answered -2
  (65534), nothing written. The CW BFO at 252 with 4 bytes sums to 256.
  FIX (cw_bfo_fix.zip): written as 3 bytes (252+0+3 = 255) -- its top byte
  is zero for any BFO -- and only when the byte left alone is known zero
  from the read; the -2 answer now fails the write at once and says so
  (it used to be retried twice and given up on, with no reason). The same
  limit explains the "broken tenth label slot": 0xFD + 2 + 5 = 260.
  test_eeprom_backup.py 14/14 (11/14 on the old files). CONFIRMED at the
  station 2026-11-06: the CW BFO restores and sticks. Backup and restore DONE.
  Added 2026-11-06 (factory_to_radio.zip): a third direction, FACTORY ->
  TO THE RADIO (Mark) -- master cal, SSB BFO, CW speed and sidetone, the
  rows the rig keeps a factory copy of; same confirm and restart. No
  factory -> file: factory -> radio then radio -> file does it. The factory
  copy is still never written. FACTORY VALUES ARE
  NEVER WRITTEN from the app (Mark) -- read only. A full EEPROM image is out
  of scope: other tools do that.
  *To check:* the formats the config file keeps (defaultubitx_cec_desktop.py
  not seen): copy writes numbers as ints and the key type as STRAIGHT /
  IAMBICA / IAMBICB; reading accepts strings, numbers and "Iambic A".
* ~~Launching the SDR at startup when autostart is set.~~ **Done.** An SDR
  already running is attached to and left running; one this application
  starts is stopped, disconnected and asked to quit, in that order, and is
  never forced where forcing corrupts it. Where each program lives, what it
  is called and how it must be closed are in `sdr_programs.json` -- see
  below.

* **`sdr_programs.json` is where a new SDR goes.** Each entry describes one
  WAY OF DRIVING a program -- its protocol, port, mode names, install paths,
  process name, launch arguments, what it can and cannot do, and how it must
  be shut down. Adding a program is an entry, not code, and an operator's own
  entries in `~/.ubitx_cec_desktop/sdr_programs.json` are merged over the
  shipped ones entry by entry. SDRangel is ONE entry, driven over REST; its
  rigctl entry was removed (see `ARCHITECTURE.md`), and a saved setting
  naming it resolves to the REST one.

  Still to do there: a way to ask for a command line a program cannot guess
  at (rigctld carries the flag; nothing asks yet).

* **One folder for everything this application keeps -- DONE
  (2026-09-27):** `~/.ubitx_cec_desktop/`, the same on every platform (the
  operator's choice over each platform's usual place, which this item had
  proposed). One helper, `app_paths.config_path`, answers "where does X
  live" for every module:

      settings.json      the settings
      channels.json      the channel sets and scan settings
      geometry.json      the window's size and position
      pinned_aids.json   the pinned pop-ups
      sdr_programs.json  the operator's own SDR programs, merged over the shipped file
      sdr_controls.json  the operator's own SDR controls, merged over the shipped file

  No moving of older loose files: the software was never released, so
  nobody has them (the move was written, worked on the station, and was
  taken out). Later: the logbook and any decoder output could live here too.
* **Tidying once the old application is retired:** the settings file's scan
  and channel entries, the SDR++ controller's dormant channel and scan
  methods, `globalvars`' Nextion leftovers, and the "simulate transmit"
  button, now that the rig reports transmit itself.

**SDRangel over REST -- in progress.** `rest_sdr.py`, one step at a time,
each tested against a running SDRangel before the next. Findings are in
`SDRANGEL_REST_NOTES.md`.

1. Frequency -- DONE both ways, confirmed on the station: rig to SDRangel
   to the Hz; a click in SDRangel's waterfall moves the rig (to its 10 Hz
   step).
2. Starting and stopping the device, under the same whose-is-it rules as
   the program -- DONE.
3. Signal strength, from the channel report's `channelPowerDB` -- DONE.
4. Volume and mute -- DONE, confirmed on the station. Volume is exchanged in
   dB as SDRangel's knob shows it (10 log10 of its `volume` factor, -10 to
   +40); mute is the demodulator's own `audioMute`. Both are SDRangel's
   settings, saved by SDRangel and read back on connecting -- not in this
   application's .ini.
   *Small, open:* at the slider's bottom SDRangel's knob reads -9, not -10.
   Probably SDRangel's display of the float it stores (0.1 comes back as
   0.100000001), but not confirmed. Harmless; look at it only if the bottom
   of the range ever matters.
5. Mode and filter -- DONE, confirmed on the station except CW by ear (below).
   Not the channel type after all: all four rig modes live in the one SSB
   demodulator, as its passband (`rfBandwidth` high cut, signed by sideband;
   `lowCutoff` low cut, same sign), on SDRangel's 100 Hz grid and kept
   inside the operator's span. Confirmed: USB/LSB/CWU/CWL from the app and
   the rig; the high cut dragged across zero in SDRangel moves the rig; the
   width kept across LSB/USB and CWL/CWU, reset between SSB and CW; CW wide/
   narrow in 100 Hz steps up to 500, 300 above.
   *Open, blocked -- no antenna on the station yet:* **CW heard at the right
   pitch.** Tune the rig to a CW signal it hears properly and listen in
   SDRangel. About the rig's 500 Hz tone: done. Missing, or far off: the
   rig's displayed CW frequency is offset by the tone, and SDRangel's tuning
   needs a matching shift in CW -- the last piece of this step to build.
   Without an antenna, any steady CW carrier the dongle can hear will do (a
   signal generator, for one).
6. AGC, NR and RF gain on the SSB demodulator -- DONE, confirmed on the
   station, and since folded into step 7's layout: lamps over frames built
   from the channel. What stays true of the SSB demodulator:
   AGC (`agc`): time (`agcTimeLog2` 4-11, a power of two -- 16-2048 ms, a
   flywheel knob), threshold (`agcPowerThreshold` -119..0 dB), gate
   (`agcThresholdGate` 0-500).
   NR (`dnr`): scheme (`dnrScheme`: 0 Average, 1 Avg Std Dev, 2 Peaks --
   confirmed) is READ-ONLY before SDRangel 8.1.0 -- accepted over REST and
   not applied, an SDRangel bug (see the notes and
   sdrangel_dnrScheme_report.txt); chosen in SDRangel's NR dialog, and
   followed. Settable from 8.1.0 (2026-11-11, see "Waiting on SDRangel"). The middle knob is the scheme's own
   setting: `dnrAboveAvgFactor` 20-99, `dnrSigmaFactor` 2-16, `dnrNbPeaks`
   1-40. Alpha dial 0-40, stored as 1 - 10^(-n/10) (0 = no smoothing).
   No notch, squelch, NB or CW peak: those lamps are greyed under it.
   RF gain (`rtlSdrSettings.gain`, tenths of a dB on the R820T's fixed
   steps) is the device's, a large Range knob beside the aids; greyed,
   saying so, while the dongle's own AGC (`rtlSdrSettings.agc`) sets it.
   *Seen, no antenna:* the demodulator AGC "breathes" on noise; much less
   with it off, but not gone. Look again with an antenna.
7. The WDSP receiver -- BUILT 2026-09-27, tested against a stand-in built from
   the station's captures (SSBDemod, WDSPRx, ChannelPower); NOT yet on the
   station. *To check there:* the six lamps and their frames; each switch
   and knob against SDRangel's WDSP window; the S-meter from Channel Power
   (moves with the filter and with a click in the waterfall); CW -- RIT,
   squelch type, ANF off, peak on the tone -- and whether CW is then heard
   at the pitch (step 5's open question, still wanting an antenna); the
   selector knobs' labels fit; and the AGC slope captured as 3.5 dB now
   shows 4 (held in whole dB -- turning it writes whole dB).
   SDRangel's other SSB/CW channel, `WDSPRx`
   (plugins/channelrx/wdsprx), built on NR0V's WDSP library from OpenHPSDR
   and Pi-HPSDR; its author recommends it over the SSB demodulator for SSB
   and CW. It has what the SSB demodulator lacks: an automatic NOTCH (ANF --
   not for CW, it would cancel the signal), a SQUELCH (voice type for SSB,
   AM/level type for AM and CW), NR and NR2, two noise blankers, a CW
   peaking filter, and RIT -- set to minus the CW pitch it puts the signal
   on the marker, which bears on the CW pitch question in step 5.
   Its AGC differs from the SSB demodulator's: on/off; mode Long, Slow,
   Medium or Fast (each fixing hang and decay); slope and hang threshold;
   and a top value in dB. The AGC frame's knobs change with the channel.
   *Plan:* a second channel type in rest_sdr.py -- its own settings block
   and entries in DSP_FUNCTIONS -- so the application drives whichever of
   the two SDRangel has. Notch and SQL then work under WDSP.
   *WARNING:* `GET .../channel/N/report` on a WDSPRx channel CRASHES
   SDRangel before 8.x -- a null pointer in its report code (see the notes);
   on 8.1.0 it answers but its power is frozen at 34.89 dB. Never read it. The S-meter comes instead from a Channel Power
   channel in the same device set, kept on the WDSP passband -- confirmed
   on the station to report channelPowerDB safely.
   *Decided:* prefer WDSP when SDRangel has it, the SSB demodulator
   otherwise. Captures DONE: every field, its numbering and its dial range
   are in the notes, and PATCH applies (unlike SSBDemod's dnrScheme).
   *Decided, the S-meter -- FALLBACK, never required:* a Channel Power
   channel when there is one, for EITHER demodulator (one source, one
   calibration); without it, the SSB demodulator's own report; under WDSP
   without it, no reading. Said once in the console which it is. Missing
   Channel Power costs the meter and nothing else -- never the connection.
   *Decided, the Operate tab under WDSP:* the lamps and frames are BUILT
   FROM WHAT THE CHANNEL OFFERS, so each demodulator shows its own knobs.
     AGC    switch; mode as a selector (Long/Slow/Medium/Fast --
            sCTkDialSelector); top, slope, hang threshold as Range knobs
     NR     switch; scheme NR/NR2 -- live now, REST applies it; NR2's
            other choices left in SDRangel
     Notch  the ANF switch
     SQL    a real switch (WDSP has one); threshold 0-100 %; A needs a
            signal level (Channel Power), R sets 0
     NB     NEW LAMP: switch; NB/NB2; threshold
     CW     NEW LAMP: the CW peaking filter -- switch; bandwidth; gain.
            Its peak frequency follows the rig's CW tone, no knob
   Six lamps -- check the row still fits. *Since reworked:* the lamps in
   two rows of three; a click switches the function; the arrow beside each
   opens its controls in a pop-up (closes on Escape or a click elsewhere;
   PIN keeps it, draggable, several at once, remembered across restarts).
   Gqrx's squelch lamp: click = A when open, R when closed.
   *To check at the station:* each lamp toggles; each arrow opens under its
   lamp; a click back on the main window closes an unpinned one; pinned
   ones survive a restart in place; switching SDR or demodulator rebuilds
   open pop-ups; Split, A⇄B, A→B and the offsets on the TX side.
   *Then:* RIT and a padlock (Lock) as tags in the RX panel's header; TX
   off beside A→B and Log QSO at the end of that row; Mute is the speaker
   icon before the volume slider (crossed out while muted). The bottom row
   is now only mute, volume and status. All latched buttons show ON by the
   library's pressed state rather than a recoloured fg_color. *To check:*
   the emoji icons render on macOS (swap to text if not); each tag lights.
   *Then:* mode on band's line, just right of it; the filter back in a row
   (wide, narrow, reset) with its width beneath; VOLUME a range knob the
   size of RF gain, just right of it, 0-100 -- double-click mutes and
   unmutes (the step its first click made is undone), "muted" beneath
   while muted, greyed while listening through the rig. The bottom row
   holds only the status now. *To check:* double-click on the knob mutes
   without moving the level; the knob follows a volume change made in
   SDRangel.
   *Then:* left to right -- lamps with the filter row beneath them; band
   over mode; RF gain and volume centred in the spare width; the TX group
   at the right.
   *Then:* band over mode over the filter (buttons, "filter" and width on
   one line), centred between the lamps and the knobs; RIT and Lock right
   of the RX dial, TX off right of the TX dial, all at Split's size; TX off
   shows the ALARM colour while on.
   *Then:* the filter back under the lamps with a gap above it ("Filter",
   wide, narrow, reset, width, one line); RIT/Lock and TX off UNDER each
   frequency, the note beside them; the TX group 16 px in from the edge;
   the status (on top, rig ok, sdr) under the TX group -- its own bottom
   row is gone.
   *Decided, automatic -- no controls:* in CW, RIT set to minus the CW
   pitch (the readme's trick: the signal lands on the marker -- may settle
   step 5's pitch question), undone in SSB; squelch type Voice in SSB and
   AM in CW (FM never); ANF off in CW, its lamp greyed with a note saying
   why -- it would notch out the signal.
   *Left in SDRangel:* equalizer, profiles, audio pan and binaural, the
   AM/SAM/FM demodulators.
   NB threshold: 2-50, stored as shown (30 on the dial, 30 captured).
   CW peak filter: spin boxes, stored as shown -- cwPeakFrequency 600 Hz,
   cwBandwidth 100 Hz (its -3 dB width), cwGain 2 (linear, not dB).
   Limits from SDRangel's own dialog definitions (wdsprxcwpeakdialog.ui,
   wdsprxgui.ui): peak frequency 300-1000 Hz (step 10), bandwidth 20-200 Hz
   (step 10), gain 1.0-10.0 (step 0.1 -- a FRACTION, unlike every other
   knob; a Range knob in tenths); RIT frequency -1000..+1000 Hz. So a rig CW
   tone outside 300-1000 cannot be the peak frequency -- clamp and say so.
   All dial ranges now in hand.
8. ARRANGE SDRangel's window -- DROPPED (2026-09-27): done by
   documentation instead. Tried: rolling the channel windows up through each
   channel's rollupState works over REST (section names settingsContainer
   plus spectrumContainer, or dataContainer for Channel Power); moving a
   window to another workspace works too (PUT .../channel/{n}/workspace)
   but was not wanted. Not possible over REST: a window's hide (eye) button
   -- Qt's plain hide(), recorded nowhere -- z-order, and window position or
   size. Kept here so it is not rediscovered.
9. SDRangel set up BY the application -- DROPPED for DOCUMENTATION
   (2026-09-28, the operator's decision: too many options -- dongles,
   channels, order -- for a wizard to get right). Write instead a step-by-
   step setup guide: the device, the WDSP receiver FIRST, the Channel Power
   channel, the Morse Decoder, no SSB demodulator, saved. The plan below
   was for the wizard, kept for the guide's content.
   Was: NEXT (planned for 2026-09-28).
   THE PLAN, as the operator put it: a simple WIZARD that starts from an
   empty SDRangel; asks which dongle (from the ones SDRangel can see); adds
   the WDSP receiver FIRST (it must be the first channel -- the Morse
   decoder's window defaults to the first channel, see the notes, "The
   Morse decoder"), then the Channel Power channel and the Morse Decoder
   feature, with the decoder's source set to the WDSP receiver. Maybe roll
   up the power channel's and the decoder's windows (`rollupState` -- see
   the notes, "SDRangel's windows"). No SSB demodulator.
   (Step 8, arranging its
   windows, was dropped: the windows' layout is left to documentation.) Install SDRangel,
   plug in a dongle, and the application does the rest: the device set, the
   dongle in it, a WDSP receiver (or SSB demodulator) and a Channel Power
   channel, then saved in SDRangel so it is there next time. Possibly a list
   of the dongles SDRangel can see, to choose one. Today every one of those
   is a step the operator has to know to take, and the first thing a new
   user meets.
   *To find out first* -- believed from SDRangel's API, NOT yet tried:
   `GET /sdrangel/devices` (the hardware it can see -- the dongle list),
   `POST /sdrangel/deviceset` (a new device set), `PUT .../device` (put a
   dongle in it), `POST .../channel` (add a channel by type), and whether a
   whole SDRangel configuration or preset can be shipped and loaded over
   REST instead of built step by step. And what SDRangel does when a device
   set is added while it already has one.
   *Rule to keep:* the application attaches to what the operator has and
   only closes what it started. Building a setup is a new kind of reach into
   somebody else's program, so it happens only when ASKED -- a "Set up
   SDRangel for me" button on Setup, with what it will add listed first --
   never automatically on connecting, and never over a setup that exists.
10. WATERFALL WIDTH from the application -- BUILT (first candidate, the
   device's sampled band): a "Bandwidth" slider under the modes steps
   log2Decim over the sample rate's divisions, 48 kHz and up (1024000 gives
   64k, 128k, 256k, 512k, 1024k); sent when it settles, then the band is
   framed again. BAND FRAMING: after a band change, and after a bandwidth
   change, the device centre goes toward band start + bandwidth/2 -- never so
   far that the signal leaves the inner 80 % of the sampled band. A band
   change puts the rig AT the band start, so in practice the centre is
   start + 0.4 x bandwidth, and the spectrum opens a tenth of the bandwidth
   below the band edge. CONFIRMED at the station, 2026-09-27: 40 m opens
   centred on 7025 kHz at 64k and about 7100 kHz at 256k. The model's BANDS
   are (name, start, end) -- confirmed. CPU, measured at the station
   2026-09-27: about 50 % at both 64k and 1024k without decoding; with DEC,
   about 60 % at 1024k and still 50 % at 64k. So the width costs little --
   the dongle samples at 1024k whatever the decimation -- and SDRangel's own
   spectrum and waterfall drawing is the likelier base cost. *Still to
   check:* the WDSP channel keeps working at every width. The note below is the
   original survey.
   WATERFALL WIDTH, original note. A control on Operate that
   sets how much spectrum SDRangel's waterfall shows: wide to look round the
   band, narrow to see a pile-up or a CW signal close up. Three different
   things in SDRangel are called that, and which one is meant decides it:
   * THE DEVICE'S SAMPLED BAND -- the main waterfall, 64 kHz now: the
     dongle's sample rate over 2^`log2Decim` (`rtlSdrSettings`), both
     settable over REST like the gain. Wider shows more but CHANGES TUNING:
     the transport moves the channel offset within this band and retunes
     the centre beyond it (OFFSET_REACH_SHARE), so the band it knows must be
     re-read when this changes. Also CPU, and the dongle's usable rates.
   * THE MAIN SPECTRUM'S ZOOM -- the same band, magnified. Whether REST
     reaches it at all is unknown: SDRangel has per-device-set spectrum
     settings (`/deviceset/N/spectrum` -- believed, NOT tried); zoom may be
     GUI-only.
   * THE CHANNEL'S OWN SPECTRUM -- `spanLog2`, the span beside the passband.
     On the SSB demodulator a `spanLog2` PATCH did NOT take (see the notes);
     untried on the WDSP receiver. It also limits the passband -- the span
     is what the filter is kept inside.
   *To find out first:* which of the three is the waterfall that matters
   beside this application, and whether REST moves it. The first is known
   to be settable and is the likeliest; its cost is the tuning rework.
   Fits with 8 (Arrange SDRangel), which decides which waterfall is shown.

**Test SDRangel's REST API.** The highest-value open question: does it report
signal strength, and does it accept filter, AGC and noise-reduction changes?
That single answer decides whether the controls currently drawn as disabled
become real. SDRangel runs on Windows, Linux and macOS, has a documented REST
interface rather than a rigctl socket, carries channel power and SNR
measurements natively, and includes a Morse decoder -- which would make the
CW tab's decoder placeholder real too.

Also worth confirming: is the decoder's OUTPUT reachable through the API, or
only drawn in its own window? Decoded text has to reach the application to be
useful. Same question for the frequency scanner's results.

**Why the current backend is a dead end.** SDR++'s rigctl server does not
expose signal strength -- the meter in the popup is `random.uniform`. An
SDR++ plugin was attempted and hit a private class wall around the one value
needed; screen scraping would break on any layout change. Gqrx's remote
protocol *does* expose strength (`l STRENGTH`, in dBFS) and takes a filter
width alongside the mode (`M USB 2400`), but it is Linux and macOS only, and
its command set stops short of AGC and noise reduction. The underlying
problem is that rigctl was designed for rigs, not receivers.

**Investigate `solsdr`** — https://pypi.org/project/solsdr/ — Jeff Francis,
N0GQ. A headless SDR engine in Python with an IQ server and a text control
API, the GUI being an optional separate client over the same interfaces. Its
feature list covers exactly the ground currently marked "awaiting backend":
stateful NR, noise blanker, notch, squelch, S-meter, Morse decoder, CAT via
rigctld. Author describes it as beta core, alpha edges. Worth reading for
what the DSP work involves and how it decomposes, whether or not it is used.

**Headless, as a longer-term direction.** Removing the second window entirely
means no lining up, no competing chrome, no duplicated readouts. But the two
products differ completely:

* **SDR++ headless streams raw IQ.** Its `--server` mode is a SpyServer
  alternative: the *client* does all the demodulation. Going that way means
  writing the filters, AGC, noise reduction, S-meter and demodulators --
  building an SDR rather than controlling one.
* **SDRangel headless runs the full chain.** `sdrangelsrv` exposes the DSP
  over REST, so there is nothing to write.

**Backend capability table.** The interface should grey what a backend cannot
do rather than pretending. Each backend declares what it supports, and the
`SDR Software` setting under Setup is where the choice is made.

| Backend  | Transport      | Signal strength        | Filter width | AGC / NR | Volume |
| :---     | :---           | :---                   | :---         | :---     | :---   |
| SDR++    | rigctl socket  | no — meter left empty  | yes          | no       | the computer's master volume |
| Gqrx     | rigctl socket  | `l STRENGTH`           | via `M`      | no / n/a | its own `AF` gain, in dB |
| SDRangel | REST           | `channelPowerDB`, to wire | expected  | expected | its own audio gain, expected |

Measured against a running Gqrx: it reports `SQL STRENGTH AF LNA_GAIN` to
`l ?`. **Gqrx has no noise reduction at all** -- AGC, squelch and noise
blankers are its list -- so an NR control can never light up there, whatever
is added to its remote control.

The boundary is ready for this. Only `SDR_Link` talks to the controller, and
volume already goes through it, so SDR++ answers with the system volume and
Gqrx with its own `AF` gain -- without the Operate tab changing.

**Where the remaining controls come from.** rigctl was designed for rotators
and radios, not SDRs, and no SDR exposes everything through it. Three routes,
in the order they are worth trying:

1. **SDRangel's REST API -- the most promising.** A control interface written
   for the program itself rather than a protocol borrowed from elsewhere, so
   AGC, noise reduction, squelch and the rest should be reachable without
   patching anyone's source or asking the operator to run a special build.
   It needs a SECOND TRANSPORT beside `RigctlSDR` -- HTTP and JSON rather
   than a socket and lines -- behind the same interface `SDR_Link` already
   uses, declaring its own capabilities. That boundary is what makes this a
   day's work rather than a rewrite.

   **What SDRangel brings that the others cannot.** Its REST API is at
   `http://host:8091/sdrangel/...`: device sets and channels addressed by
   index, `PATCH` for a partial settings change, `POST` to add a channel.
   There is also a REVERSE API -- SDRangel forwards every settings change to
   an endpoint of ours, in the same JSON -- which would replace polling
   with being told. One of its own example scripts is a scanner that stops
   when a channel's squelch opens, which is the behaviour ours wants.

   * **A WDSP receiver plugin** (the DSP library behind OpenHPSDR) with
     real AGC, noise reduction and noise blanking -- the controls Gqrx
     would need patches for and SDR++ cannot do at all.
   * **A MORSE DECODER feature** (v7.21.0, on the GGMorse library) -- what
     the CW tab's greyed-out Decoder button is waiting for. It is a FEATURE
     rather than part of a demodulator, so it takes audio from any of them
     (SSB for real CW), and it detects pitch and keying speed itself, with
     a lock once it has them. NOT IN THE WINDOWS DISTRIBUTION -- GGMorse
     does not compile there. Whether the decoded text comes back over the
     API needs checking against a running instance: features have settings
     and report endpoints, and the text may be in the report. If it is not,
     the decoder can write to a text file, which the application could
     follow as it is written.

   Decoding then becomes another capability: offered where the SDR has it,
   greyed out for SDR++ and Gqrx, which have no decoder at all.

   **Its discovery differs from rigctl's**, and should be designed first:
   rigctl has exactly one thing to talk to, while SDRangel has device sets
   and channels, any number of them. Finding the right demodulator channel
   -- and deciding what to do when there are none, or several -- is the
   first piece of work, not an afterthought.

2. **Patching Gqrx's remote control.** Its protocol file is small and the
   pattern is well established -- `PR #1463` (filter shape) is a complete
   worked example of adding a LEVEL, and `dsward2/gqrx#2` (UDP streaming) of
   adding a TOGGLE. Six pieces each: the name in `l ?` / `L ?`, a branch in
   `cmd_get_level` and `cmd_set_level`, a mirror variable kept current so
   reads are right, a slot on `MainWindow` moving the real control, a
   `connect`, and a line in `resources/remote-control.txt`.

   AGC would follow the level pattern, the noise blanker the toggle one.
   Neither has an open PR. Other open PRs worth adopting rather than
   inventing: filter shape (#1463), bookmarks (#1464), device selection
   (#1446). Read a PR's diff at
   `https://patch-diff.githubusercontent.com/raw/gqrx-sdr/gqrx/pull/<n>.diff`
   -- GitHub's own pages refuse automated reading, that host does not.

   **The risk of an unmerged PR lands on the USER'S BUILD, not on this
   code.** Capabilities are discovered at connect, so a stock Gqrx simply
   greys the control and a patched one lights it up. Publish a patch against
   a release tag, not binaries: `dsward2/gqrx` ships signed macOS builds of
   exactly this kind, which is a real maintenance burden and not one to take
   on unless people ask.

3. **Screen scraping -- a last resort, for closed software only.** Gqrx is
   Qt and exposes a real accessibility tree; SDR++ draws its interface with
   Dear ImGui straight onto an OpenGL surface, so there is nothing to find
   there but pixels, and any click is coordinates that a resize, a theme or
   a scroll invalidates. Three platforms, three mechanisms -- macOS
   Accessibility via `pyobjc` (and its permission prompts), Windows UI
   Automation via `pywinauto`, Linux AT-SPI via `pyatspi` (restricted under
   Wayland) -- so extra packages and per-platform code, carried by the
   operator. READING STATE BACK is the harder half and the reason it fails:
   clicking NR is easy, knowing whether NR is on is not. If it is ever
   built, it goes behind the same capability boundary as a per-application
   driver -- never mixed into `SDR_Link`.

**Gqrx remote-control patches -- DEFERRED (2026-09-27).** Searched again:
no release or open PR adds AGC, noise blanker or noise reduction (latest
release 2.17.7, May 2024; nothing merged since). Gqrx HAS AGC (off/fast/
medium/slow/user, gain, threshold, slope, decay, hang) and NB1/NB2 with
thresholds, but no noise reduction (issue #1362) and no notch -- so a patch
of ours, on the #1463 pattern, would add AGC and NB, and the rigctl
transport would need switched functions. Worth watching: #1458 (on-demand
FFT data -- an app-drawn waterfall) and #1456 / #1426 (separate hardware and
receive frequencies -- band framing for Gqrx).

**Gqrx versions differ in ways that matter.** 2.17.5 fixed responding to
pipelined remote commands and limited UDP packets for netcat compatibility;
2.17.4 added `\chk_vfo` and `\get_powerstat`. Some odd behaviour seen while
testing by hand may be version-dependent rather than protocol-dependent.

---

<a name="the-application"></a>
### The application — bugs worth fixing in the current code

**Rewire the USB-to-TTL monitoring adapter: GND and its RX only.** *Hardware, open.*

With the adapter plugged into the Nano's serial lines, the rig re-sent the
same reports (`vs`, `vy`, `ve`, `cn`) endlessly, unasked, until the adapter was
unplugged or the rig power-cycled. The suspect is the adapter's TX, which
drives the Nano's RX: idle levels, echo, or back-feeding the Nano through the
pin. The test is to disconnect only that wire -- if the repeating stops, that
was it; if not, look at GND and VCC next. VCC should not be connected at all.

The current wiring cannot drop TX alone, so it needs a different lead or
separate jumpers. Until then, unplug the adapter when not monitoring. The
reader now says once when a report repeats 20 times in 5 s
(`READER_REPEAT_WARNING`), so a return of the problem shows up in the console.

Found on the way, and fixed: the reader lost a report whenever one was split
across two passes (the "skipping prior byte" floods), and a continuous stream
froze the interface. Partial reports now carry over; each pass is capped at
512 bytes.

SEEN AGAIN, 2026-09-27, adapter plugged in: at start-up the line from the rig
was held LOW for 17344 zero bytes (~3 s at 57600), then came back. The start
of the boot burst was lost with it -- presets through the primary VFO -- and
VFO A read 27,926,000, far from the last sessions. A second symptom of the
same adapter, it seems: it gets into a stuck state. Unplug it when not
monitoring until it is rewired; if it recurs WITHOUT the adapter, it is not
the adapter. Unplugging and replugging the adapter cleared it: the next
start-up was clean, every value arriving -- so the adapter itself gets stuck,
and a replug resets it. (27,926,000 came back again on the clean start, so
it is what the rig had stored, not damage.)
SEEN A THIRD TIME, 2026-09-27 evening: line held low for 11837 zero bytes,
then the unasked-report flood (vy/ve/tuning preset and "val=120" junk,
flagged by the app's "without being asked" warning), settling once the
rig's start-up report came through. Power-cycling the adapter cleared it
again. Same fault, same cure: it is the adapter.
*Possible recovery in software:* when the line comes back after being held
low during the boot burst, reboot the rig once more to get the burst again
-- ties in with the item below.

**UNRECOVERABLE START-UP, 2026-11-10 (Mark):** caught in an endless loop
on "Tuning Preset 1". Not diagnosed: Mark will catch the console next time.
Two readings: (1) the rig flooding unasked (the adapter's symptom above --
`Tuning Preset 1:` and vs/vy/ve/cn over and over, READER_REPEAT_WARNING's
line); (2) the app resending -- but Set_Tuning_Preset goes only at connect and
in restart_rig, which runs at most RIG_REPORT_RETRIES (2) times, so that would
be a bug. PLAN if (1): when the repeat warning fires, restart the rig (not
while transmitting), at most twice, then tell the operator to power-cycle or
unplug the adapter -- instead of scrolling forever. Ask: was the adapter
plugged in, and what cleared it.

**Ask the rig for values that have not arrived.** *Done 2026-11-06; the late-answer fix confirmed at the station.*

`_read_all_values()` is GONE -- 101 lines that blocked, counted to 26, timed
out after five seconds and raised modal dialogs from inside the loop. The
reader starts instead and the rig's boot burst arrives through the ordinary
handlers, so the window appears at once and the readouts fill in behind it.

What is there now: every report's code is recorded as it passes through
`_process_radio_command`, and `check_expected_reports()` PRINTS which of the
twelve values the interface needs have not arrived, two seconds after
connecting. Six others -- active VFO, split, RIT, lock, speaker, transmit
inhibit -- are reported ONLY when not in their default state, and the rig
comes up in all of them, so their silence is an answer; `RadioModel` starts in
exactly those states.

~~What is left: ASK for what has not arrived, rather than print it.~~
DONE 2026-11-06 (report_recovery.zip), by RESTARTING the rig -- it has no
request for one value, it sends them all as it boots. `_check_rig_answered`
restarts it when values are missing, checks again 2.5 s later, at most
twice (RIG_REPORT_RETRIES), never while transmitting; what arrived the
first time stays counted. `uBITX_Link.restart_rig()` = reboot + the fine
tuning preset again, as at connect; the CW tab's Restart rig uses it too
(before, it left the rig on its own coarse preset). test_report_recovery.py
5/5. To check at the station: a normal connect still says "all 12 expected
values arrived" with no restart -- if one of the twelve is NEVER sent by
this firmware, every connect would restart twice, and that code should
leave EXPECTED_REPORTS. Next: the "skipped N bytes" messages at startup.
Seen 2026-11-06: `m.vs.val=100` eleven times, skipped. Mark: not a report
that lost its "p" -- the ill-formed run-together case his old validateKey
caught ("looks like val"). The skipped/dropped messages now print the raw
bytes in hex, 0xff included (rig_hex.zip), to see the terminators before
deciding the recovery.
FOUND 2026-11-06 (rig_late.zip): a rig still BOOTING was called silent.
It held its line low for 17 352 zero bytes (~3 s) before the first report,
past the 2.5 s answer check -- so rig_state went "silent", the backup
dialog said "no radio" over a working rig, and the missing-values restart
never ran. Now: bytes arriving (zeros included, uBITX_Link.bytes_seen) mean
wait, up to RIG_ANSWER_MAX_MS (10 s); and a rig called silent that then
reports is put back to connected (_rig_answered_late, from refresh) and its
values checked. The repeated vs/vy/ve/cn lines are the rig re-sending after
the app's tuning-preset command -- noise, not a fault. test_report_recovery
9/9 (6/9 on the old files).

**This matters more than it looks, because the reboot is not portable.** The
whole arrangement rests on rebooting the rig: the burst is what the boot
produces, and "silence means the default" is only true of a rig that has just
started. The reboot key (`5945486C`) is KD8CEC's on a Nano -- a Pico or a
Teensy build reboots differently, or cannot be made to from here at all. On
any of those, connecting means asking, and the same is true of any
connect-without-rebooting option offered to an operator who is mid-QSO.

**The reboot is doing a SECOND job, easily missed.** It does not only produce
the burst -- it guarantees the conversation starts at a frame boundary. Plug a
rig in mid-transmission, or connect to one already talking, and the reader
joins a byte stream in progress: a partial frame, a checksum that fails, and
everything after it read against the wrong boundary. That is the fault the
channel reads had, where one dropped reply filed every later value against
the wrong slot -- and it looks like a working connection until a frequency
arrives as a label.

So whatever replaces the burst must RESYNCHRONISE rather than assume: find the
frame preamble, discard whatever precedes it, and only then start reading.
Without that, asking works on a quiet rig and fails on a busy one.

The pattern to follow is the channel reads: one request at a time, each
confirmed before the next, retried when a reply does not come, progress
reported upward. That is what made reading twenty channels reliable after the
first attempt filed labels as frequencies.

**The reboot is doing two jobs**, and whatever replaces it inherits both --
see `ARCHITECTURE.md`, "Starting from a known point".

~~Choosing Gqrx on Setup does not offer its port.~~ **Fixed**, and not for the
reason guessed here: the test compared against the PREVIOUS program's
default, so choosing Gqrx while the setting still said None matched nothing
and the field kept 4532. It now offers the new program's port unless the one
there is not any program's default -- which means somebody typed it.

**A 10 Hz tuning step does not reach the SDR.** *Not seen since, and nobody
set out to fix it -- so it is kept, not closed.*

Turning the 10 Hz digit moved the rig, and the SDR did not follow until the
100 Hz digit changed. What changed in the meantime, and could account for it:
the rig is now REBOOTED on connecting, and the finest tuning preset is set
afterwards. If that preset had not been taking effect before, the rig would
have rounded a 10 Hz step away and reported the rounded value -- which is the
first candidate below. That is a guess, not a diagnosis.

If it returns, suspect one of:

  * the rig ROUNDS to its tuning preset and reports the rounded value, so
    nothing changed to pass on -- but the preset is set to the finest at
    connect for exactly this reason, so check it is still in force;
  * `SDR_Link.follow()` compares against `_sent_frequency` and skips what it
    thinks it already sent;
  * Gqrx rounds what it is given, or its own step is coarser.

  A console trace of `vc`/`va` reports while turning the 10 Hz digit, beside
  what `follow()` sends, would say which in a minute.

These affect what is running today, not just the rebuild.

**The SDR connection blocks the interface.** *Mostly dealt with.*
`SDRPlusPlusController` is gone; `RigctlClient` waits half a second for a
reply and treats silence as "not supported", so a wedged SDR costs that
rather than the session. What remains: those waits are still on the interface
thread, so a program that stops answering can hold the window for half a
second at a time, and connecting to a silent server costs a few seconds at
startup. A thread would end it properly.

The rig does not have this problem: it is paced by the MCU headroom settings
and the Nano always answers. The SDR has no such protection, and it is the
one place in the code where a thread or a non-blocking socket earns its keep.
Both transports are single-threaded today -- neither imports `threading` --
so anything introduced there is new, and its results must reach the interface
through the Tk loop rather than directly.

**Some `xx_UX_` handlers still store nothing.** Wired since this was first
written: the tuning presets, the CW tone and tweak, and the memory reads and
write acknowledgements. Still unwired: the meters, the CW settings, ATT and
IFS -- listed with the rest of the remaining work
under [The uBITX interface](#the-ubitx-interface). Some are deliberately
ignored: `vr_` (its value is a firmware figure, not the RIT base), `ch_`
(the CW offset switch -- dropped, see above), `c0_`, the
greenbox lines, `cm_`, `vv_` and the spectrum reports.

*The four `comportManager` bugs that were here are superseded.* That module
is not used any more -- `serial_ports.py` replaced it -- so its missing
parentheses, its bare `except:`, its view work and its IPv6 handling are
history. The IPv6 fault outlived it, though, and is noted against the rig
connection above.

---

### No font sizes on sCTk widgets -- DONE (2026-11-05)

Every `font=(...)` on an sCTk widget in ubitx_cec_desktop.py is gone --
Operate, RX, Channels, CW, Setup, the pop-ups, EEPROM backup, About and Log
QSO. The theme's tiers (Primary, Secondary, Tertiary) set the size; where a
size had been wanted smaller, the widget moved down a tier (the knobs'
values and the pop-ups' headings are Tertiary now). The rule is in a FIX
comment at the top of `_build_operate`.
TWO SPECIAL CASES KEPT, both drawn sizes rather than label tiers (Mark's
decision): the frequency display's `FREQ_FONT_SIZE` (56) and the dials'
end labels, `RANGE_KNOB_LABEL_FONT` -- which `_range_canvas_size` also uses to
measure the room a dial needs.
About and Log QSO's value labels stay Secondary -- checked, fine (Mark,
2026-11-06).
Setup reworked the same day: the bottom row in halves, Logbook (two fields
a line, Format and Backup in one column) and "Other Settings" (three
buttons a line); a CW port line in the SDR group (see SDR settings, 1).

<a name="much-later"></a>
### SDR isolation and the config folder (2026-09-27)

- DONE: the controls' ranges, labels, units and conversions moved out of
  rest_sdr.py into sdr_controls.json (+ sdr_controls.py, named conversions);
  RF gain steps too. The window names no SDR and holds no SDR's numbers:
  every listening aid goes through SDR_Link's one description (has_dsp,
  dsp_blocked, dsp_switchable, dsp_on, toggle_dsp, knobs, dsp_actions);
  Gqrx's squelch is described there, not special-cased in the window.
- DONE: ~/.ubitx_cec_desktop/ (app_paths.py) holds settings.json,
  channels.json, geometry.json, pinned_aids.json, sdr_programs.json and
  sdr_controls.json -- see "One folder" above. The About box shows where
  the settings are.
- *Checked at the station, 2026-09-27:* the refactor works with SDRangel
  (WDSP: squelch switch and threshold), Gqrx and SDR++. The WDSP passband
  workaround works: USB <-> LSB moves the far cut, wide/narrow keep the
  sideband, AGC and RIT no longer make the filter jump; the Notch lamp greys
  in CW with its note. RF gain steps, volume and double-click mute work.
  The folder works: settings, channel sets and window position all there.
- DONE: the bandwidth slider and band framing, confirmed at the station
  (40 m centred on 7025 kHz at 64k, about 7100 at 256k -- start + 0.4 x
  bandwidth, since the rig lands on the band start).
- DONE: out of every ham band the band spinbox shows "—" rather than the
  last band chosen, and its arrows go to the nearest band that way (from
  below 160 m or above 10 m, to that end band). The spinbox steps from the
  position of the last value it showed from its list, so the application
  sets that position (_aim_band_arrows) and corrects DOWN in _on_band --
  the library is unchanged. CONFIRMED 2026-11-06: "—" shown off-band, and
  the arrows go to a real band.
  (Library idea, not needed: a way to tell sCTkSpinbox where stepping
  starts, instead of the application setting its _current_index.)
- DONE: a **Defaults** button in each listening-aid pop-up that has known
  defaults -- SDRangel's resetToDefaults() values, as "default" per setting
  in sdr_controls.json. One PATCH; the switch is left as it is. WDSP AGC,
  NR, squelch, NB, CW peak; SSB demodulator AGC and NR (not its alpha: the
  source stores 1.0 and how that maps to the dial is not known -- read it
  off a fresh demodulator to add it). Confirmed on the station.

### CW decoding through SDRangel's Morse decoder -- BUILT (2026-09-27)

DEC, the seventh lamp. Found at connect (`GET /featureset`, id
"MorseDecoder" -- capability `decoder`); greyed with its reason where there
is none, and outside CW. On: a UDP socket of the application's own on
127.0.0.1 (a port the system picks), the decoder's UDP output PATCHed to it
and the feature asked to run; its text read on the poll and shown in a strip
along the bottom of the Operate tab, newest at the right -- the strip only
there while DEC is on. And the receiver set for decoding, the operator's
choice: filter narrowed to 250 Hz (200 on SDRangel's grid) unless already
narrower, AGC off, CW peak on. Off: all three put back, and the decoder's own
UDP settings restored. Leaving CW stops it (the filter is then the new
mode's). Not reachable, so not shown: its pitch, speed and confidence.
FIX (2026-09-27, after the first station try did not choose the WDSP
receiver, start the decoder or tick UDP): the source is now chosen by the
feature's actions POST, the decoder started by POST run (and stopped at DEC
off only if it was stopped before), and every step read back and reported
in one `[sdr] CW decoder:` console line.
CONFIRMED at the station, 2026-09-27, once the SSB demodulator was removed
(the decoder's window defaults to the first channel and overrides a REST
choice when its list changes -- notes, "The Morse decoder"). The decoder's
window still shows stopped, UDP off and its own source: it is not told of
REST changes. FIX: the strip now fills from the left and scrolls left once
full, holding as much as its width allows.
CONFIRMED 2026-11-06: resizing the window -- the strip refits to its new
width.
FIX (2026-11-05): the strip's Courier went with the other fonts, so the line
is now FITTED BY MEASURING the text in the label's own font
(`_decode_tail`), not by counting characters -- a count from one letter's
width stopped two-thirds across. CONFIRMED with SDRoxide Brown: it fills to
within a couple of centimetres of the right-hand end, then scrolls left.
*Was to check:* DEC in CW -- the console line says UDP on,
source chosen, decoder running; the decoder's window shows the WDSP
receiver as source, UDP ticked, Start pressed; text in the strip. DEC off
restoring filter, AGC and CW peak, and the decoder's UDP box as it was.

### SDRoxide over rigctl -- WORKING (2026-09-28)

A new entry in sdr_programs.json: its Hamlib server (Settings > Servers),
port 4532 -- the same as SDR++, so not both at once. CONFIRMED at the
station: tuning both ways, USB/LSB/CW, volume, mute, and the S-meter (its
STRENGTH is Hamlib's dB over S9, now `"signal_unit": "S9dB"` and shown in
dBm -- it matched SDRoxide's own meter). It does not choose a mode from the
band plan when tuned.
Found with nc: it answers `RPRT 0` at once but applies the change a moment
later, so an immediate read-back is the OLD value -- which would have
pulled the rig back. Fixed by `"settle_seconds": 1.5` (rigctl_sdr._stale).
Not offered over rigctl: squelch (`l SQL` -> RPRT -11), and `l ?` / `L ?`.
Squelch is in SDRoxide's window but not its rigctl server: `l SQL`,
`L SQL`, `u SQL`, `U SQL` all RPRT -11 (2026-09-28) -- asked for in the
issue draft. AGC is not reachable either (`l AGC` / `L AGC` -> RPRT -11, 2026-09-28),
so its lamp stays greyed. FILTER BOUNCING at the station (2026-09-28): narrowed, then went back.
Traced (UBITX_SDR_TRACE=1 prints every rigctl command and every change the
poll reports) and tested with nc: SDRoxide's rigctl server IGNORES the
width of an `M` naming the mode it is already in, and takes any width --
presets or not (2000 held) -- when the mode changes. Each mode change
takes it about a second. WORKAROUND, `"width_needs_mode_change": true`:
a new width in the same mode goes through the other sideband (or other
CW) and back, the mode and width it reports meanwhile ignored
(RigctlSDR._send_mode, _hop); settle_seconds raised to 3. Tested against a
fake that behaves so. REPORTED upstream? -- draft in
sdroxide_passband_issue.md. *To check at the station:* each filter
button in USB and in CW holds, with at most a short blip; the rig never
changes mode. Remove the workaround when SDRoxide is fixed.
FIX, same day: SDRoxide keeps NB, NR, notch (and more) PER MODE, so the hop
loaded the other sideband's -- the notch lamp flickered and came back on or
off. During a hop the switches, volume and mute it reports are ignored, and
the switches as they were are sent back once it is over. Tested against a
fake with per-mode memory. CW is one mode in SDRoxide: both CWs map to
`CW` (ambiguous, as SDR++), and the hop from CW goes through LSB.
POSSIBLE BUG, not reproduced (2026-09-28, SDRoxide): setting CWL on 10 m
sometimes ended in LSB -- seemingly around filter changes, not
consistently. SUSPECT: the filter hop. From CW it goes through LSB; if
SDRoxide has not come back to CW with the new width within the hop's
window (3 s), the hop is dropped and the next read -- still LSB, or LSB
applied late -- is believed as the operator's, and the rig is switched to
LSB. Two queued mode changes behind another command could take that long.
*When it happens:* run with UBITX_SDR_TRACE=1 and keep the lines around
it -- whether `M LSB <w>` / `M CW <w>` were sent just before, and whether
`<- changed in the SDR: 'LSB'` follows. CAUSE FOUND in SDRoxide's source (2026-09-28, main 807b0fc = v1.6.8
for the rigctl server -- nothing relevant waiting unreleased): its set_mode
drops an `M` naming the mode it REPORTS, width and all, on purpose (WSJT-X
re-sends its mode). Sent together, the hop's return arrived while it still
reported CW, and was dropped -- leaving LSB. FIXED: the hop is TWO STEPS,
the return sent only once it reports the other mode (RigctlSDR._follow_hop);
a real mode change cancels a hop. Tested against a fake with the same rule,
at 0.8 and 2 s per change: back every time, no retry needed. Also from the
source: CWR is taken as CW; STRENGTH is dBm + 73 (S9dB, as set). Earlier
fix kept as the fallback (2026-09-28): when a hop's window ends without the mode and width coming
back, the mode wanted is sent again (twice at most, a console line each
time) rather than what is read being believed; no mode read within a hop
reaches the rig. Tested against a fake SDRoxide 2 s per mode change, and
one that loses the return command: both came back to CW, LSB never
reported. *Watch for:* "[sdr] SDRoxide not back from a filter change"
in the console -- how often, and whether LSB still turns up on the rig.
BUILT: the NB, NR and Notch lamps, from the rigctl transport
(`rigctl_sdr.SWITCHES`, `u`/`U NB`, `NR`, `ANF`) -- found at connect by
reading and sending back, so rigctld gets them too where its rig answers.
Switches only; the pop-ups hold no knobs. Within the settle window, as
the other settings. The notch goes off on entering CW. Tested against a
fake server that applies changes half a second late. *To check at the
station:* each lamp switches SDRoxide's own NB, NR and ANF, and follows
when they are switched in SDRoxide; entering CW turns the notch off. Not reachable: its CW decoder's
text (no output to other programs documented).

### Your own sdr_programs.json merged SETTING BY SETTING -- FIXED (2026-09-29)

Found at the station: `{"sdroxide": {"decoder_udp_port": 9999}}` in
~/.ubitx_cec_desktop/sdr_programs.json was IGNORED -- the file was merged a
whole program at a time, so the partial entry replaced SDRoxide's whole
description and was refused for having no protocol (a console line said so).
The earlier `width_needs_mode_change: false` override was ignored the same
way. sdr_programs.load() now merges settings within a program the shipped
file lists; a new program is still described in full.

### Protecting the SDR on transmit -- DECIDED (2026-09-28)

The SDR's antenna relay is switched by the Pico uBITX board's own
OPTO-ISOLATED OUTPUT, from the firmware: set it, wait the relay's throw time
(10-15 ms for a small coax relay), then the rig's T/R relays and RF; on
key-up, RF off, back to RX, a short hold, then release. It leads the RF by
construction and works with the computer off. Wire it so a de-energised
relay leaves the SDR grounded or disconnected. Nothing needed in this app
(a status lamp for the port would be optional). Considered and set aside:
a second USB-TTL adapter's RTS/DTR driven from `model.transmitting` -- the
rig's RX/TX message arrives after RF for overs keyed at the radio; and
SDRoxide's T/R-switch tab, which throws only on its own transmit or a
hardware sense wire, and is not reachable over rigctl.

### Waiting on SDRoxide -- upstream PRs: 1, 2, 3 and 5 MERGED, released in v1.6.11

**Status 2026-11-04:** PRs 1, 2, 3 and 5 were merged by the author and are in
release v1.6.11 (2026-11-01) -- checked in that release's source. PR 4 (hide
the control strip and the CW panel, and the window minimum that follows them)
was not merged; to be rethought (see 4 below). Switched in the app, in the
shipped `"sdroxide"` entry, for v1.6.11 and later -- DONE 2026-11-04:
- `"width_needs_mode_change": false` and `"settle_seconds": 1.5` (PR 1);
- `"decoder_udp_port": 9999` (PR 3);
- nothing for PRs 2 and 5: found at connect.
The mode switch-and-back code (`RigctlSDR._send_mode` / `_follow_hop`) stays:
the `"sdroxide-brown"` entry still needs it until brown merges its PR 1.
The upstream PR branches are deleted from the clone and the fork; PR 4's
`panadapter-view` was kept for a rethink, then dropped (brown's dock/undock
covers it) -- deleted 2026-11-04.
An SDRoxide older than v1.6.11 needs the old values back in the user's own
`~/.ubitx_cec_desktop/sdr_programs.json`.
The original list, kept for what each one does:


Five PRs prepared 2026-09-28/29 (sdroxide_prs_bundle.zip, with instructions):
1. rigctl: a new width in the mode already running sets the filter. When
   released: SDRoxide's entry `"width_needs_mode_change": false`, and try
   `"settle_seconds"` lower (1.5). Test first: in USB, `M USB 2400` then
   `m` after 2 s reads 2400.
2. rigctl: squelch, AGC and NR strength as Hamlib levels; `U NR 1` keeps
   the chosen engine. When released: nothing to switch -- the SQL lamp,
   the AGC lamp with its speed knob, and NR's strength knob appear at
   connect (built 2026-09-28, `rigctl_sdr.LEVEL_KNOBS`; `rigctl_agc` /
   `rigctl_nr_strength` false, or "squelch" in `known_missing`, turn each
   off). Test first: `l SQL`, `l AGC`, `l NR` answer numbers.
3. Decoded CW over UDP, the CW panel's settled copy as plain text to
   127.0.0.1:9999 (the form and port SDRangel's Morse decoder uses) -- for
   our DEC strip. When released: enable it in SDRoxide (Settings > Servers),
   then `"decoder_udp_port": 9999` in SDRoxide's entry (null until then).
   The app side is BUILT (2026-09-28, RigctlSDR.set_decoder / _read_decoder:
   DEC listens on that port while on). TESTED at the station 2026-09-29
   with a PR 3 build: the strip showed exactly what SDRoxide's CW panel
   copied (make_cw_iq.py's practice recording played with --file).
   Not in PR 3: the SKIMMER's spots -- a DX-cluster-style telnet spot
   output ("DX de ...", as CW Skimmer and RBN publish) would suit them;
   left for later, after seeing how the author takes PRs 1-3.
4. Settings > UI switches to hide SDRoxide's control strip (a STRIP chip in
   the corner brings it back) and its CW panel -- SDRoxide as a bare
   panadapter beside our app. Nothing in our app; untick both in SDRoxide
   once released.
   DROPPED 2026-11-04: SDRoxide Brown's dock/undock gives the bare waterfall
   and frequency view this was for. Patches and PR text deleted from the
   project; the fork's `panadapter-view` branch deleted too.
   (Was: NOT MERGED -- RETHINK.) Built and tried 2026-09-29: the switches work, but
   the window's minimum (800 x 500, fixed in gui_main.rs) did not shrink, so
   a follow-up made it follow the strip and panel; and below 600 x 440
   SDRoxide's Auto layout goes to its phone layout, which drops the spectrum
   trace (Layout = Desktop keeps it). Worth asking the author how a "bare
   panadapter" should fit his layout tiers before redoing it.
5. rigctl: the RF gain -- the stage SDRoxide's Gain slider moves -- as
   Hamlib's RF level, 0..1 across its range. BUILDS ON PR 2 (its branch is
   made from PR 2's). When released: nothing to switch -- the RF GAIN knob
   comes alive at connect, in percent of the range (built and tested
   against a fake SDRoxide 2026-09-29, RigctlSDR.set_rf_gain; "rigctl_rf_gain":
   false turns it off). Test first: `l RF` answers a number that follows
   the slider. TESTED 2026-09-29: built on the Mac, 46 rigctld tests pass
   on PR 2 + PR 5, `l RF` / `L RF` right, and the knob works in the app.
6. If the location of the SDR is ever defined in the SDR settings, there is no way to completely erase it without hand editing the settings file.
7. NEXT PR CANDIDATE (2026-11-04): the WATERFALL WIDTH over rigctl, so the
   Operate tab's Bandwidth slider (and band framing) work with SDRoxide. Today
   the slider is greyed for every rigctl SDR: the capability `bandwidth` comes
   only from SDRangel's REST transport (log2Decim). SDRoxide can do it inside
   (`Command::SetSampleRate`, `Command::SetDecimation`, an on-screen span) but
   its rigctl server has no command for any of them -- checked in upstream's
   and brown's `crates/sdroxide-rigctld/src/proto.rs`.
   *Plan:* use Hamlib's own spectrum-scope levels (added in Hamlib 4.x for the
   IC-7300/7610 scope) rather than inventing one -- `SPECTRUM_SPAN` (the width
   shown, Hz) for the slider; `SPECTRUM_MODE` and `SPECTRUM_EDGE_LOW/HIGH`
   possibly for band framing. Advertised in `\dump_state` like the other
   levels. App side: found at connect, moved by the slider -- as RF gain.
   *Checked in Hamlib's rig.h (2026-11-04):* SPECTRUM_MODE 1<<40 (1 centre,
   2 fixed, 3/4 scroll), SPECTRUM_SPAN 1<<41 (int Hz, centre mode),
   SPECTRUM_EDGE_LOW/HIGH 1<<42/43, SPEED/REF/AVG/ATT 1<<44-47; funcs
   SPECTRUM 1<<43, SPECTRUM_HOLD 1<<44. From OH3BHX's spectrum work (4.5).
   rigctld's \dump_state carries the level masks and `level_gran=` (min/max/
   step) but not the `spectrum_spans` list. *Proposed mapping:* decimation
   (span = rate / 2^n; SetDecimation already rounds and clamps) -- the same
   as SDRangel's log2Decim behind our slider. Issue drafted:
   sdroxide/issue_spectrum_span.md -- its one question is decimation or the
   displayed zoom. SUBMITTED as an issue 2026-11-04. ANSWERED: decimation;
   brown built it himself as #479, MERGED 2026-11-05 (l/L SPECTRUM_SPAN in
   Hz; RPRT -11 where there is no decimation; no level_gran/spectrum_spans,
   which we do not need). APP SIDE BUILT 2026-11-05 (spectrum_span.zip):
   RigctlSDR finds SPECTRUM_SPAN at connect (capability `bandwidth`), offers
   the span x powers of two (48 kHz..20 MHz) trimmed to what the SDR is found
   to allow, sets with L, reads back in the poll (own 2 s settle window),
   follows a change made in the SDR; set_frequency accepts band= and ignores
   it -- over rigctl the SDR places its span itself, so no band framing.
   10 transport tests. CONFIRMED ON THE STATION 2026-11-05 (brown main
   25ba95d6, RTL-SDR at 2.4 MHz): found at connect, the slider starts at
   SDRoxide's width, every step applied down to 75 kHz (decimation 32, its
   floor). Then: the same width is no longer sent twice (it re-sent F too).
   Also confirmed: brown's DEC chip (top bar, beside the gain) moves the
   app's slider; asking past the widest (19.2 MHz) gave 2.4 MHz and trimmed
   the slider -- after a ~2 s pause (SPAN_SETTLE_SECONDS), which goes away
   once the device rate is readable.
   SEEN: SDRoxide's display ZOOM is separate from the sampled span. Narrowing
   the span below what is shown zooms the view in with it; WIDENING it is not
   seen until zoomed out in SDRoxide -- the view keeps its zoom. Possible ask
   for brown: fit the view when the span changes over rigctl, or expose the
   zoom (Hamlib has SPECTRUM_EDGE_LOW/HIGH in fixed mode). ASKED 2026-11-05
   on #479, with the device rate (and how he would like it -- `\dump_state`
   or otherwise); asked whether he does them or we send a PR.
   ANSWERED 2026-11-05: no new `\dump_state` line (hand-written, parsed line
   by line by Hamlib's netrigctl -- a line for one feature risks every
   client); he will add `spectrum_spans`, the protocol's own place for the
   device's real spans. And he will look at refitting the view on a span
   change. He asked what we expect; REPLIED 2026-11-05: the waterfall -- a
   span change over rigctl resets the view to the whole new span, widening
   or narrowing, and the operator re-zooms; changes made in SDR Oxide itself
   unchanged. Offered a PR for either. Waiting.
   2026-11-09: brown CLOSED #469 with no comment. CHECKED brown main
   6c41fe8b (2026-11-08): neither follow-up is in -- no `spectrum_spans` in
   any crate (no commit ever added it), and no commit refits the view on a
   rigctl span change; #479 (the span itself) is all that landed. His own
   TODO.md still lists #469 in its backlog. Mark asked him to confirm;
   waiting on his answer. PLAN (Mark, 2026-11-09): next week, write the PRs ourselves --
   `spectrum_spans` in `\dump_state` (its documented sentinel and order),
   and the view refit on a rigctl span change (keep the `ctr_zoom_sim` tests
   green and add the gesture) -- each its own PR, brown's house rules.
   GO-AHEAD from the maintainer 2026-11-09 to make the PR(s); to do later.
   PR 1 OPENED 2026-11-10: #641, "rigctl: list the spans SPECTRUM_SPAN can
   give in \dump_caps" -- Hamlib's own "Spectrum spans:" line (narrowest
   first, "%.0f " each) in \dump_caps, NOT \dump_state (the maintainer's
   concern: netrigctl parses \dump_state line by line; it never sends
   \dump_caps -- checked in Hamlib's source). Spans = device rate / each
   power of two up to max_decimation; each one L SPECTRUM_SPAN sets exactly.
   3 tests, 58 in sdroxide-rigctld; red check done; fmt clean for the crate
   (brown main has unformatted files elsewhere -- use cargo fmt -p). Checked
   on the station: \dump_caps lists 75000..2400000 at 2.4 MS/s; L 300000
   then l reads 300000 once applied. NOTE: brown's rigctld files are CRLF --
   apply our patches with `git am --keep-cr`. APP SIDE BUILT (rigctl_sdr.py):
   at connect, where SPECTRUM_SPAN exists, "+\dump_caps" is asked (extended,
   ends with RPRT -- no wait on an older brown); a "Spectrum spans:" line
   makes the slider offer exactly those; without it, the old powers of two.
   test_span.py 13/13. Works at the station with the PR build. When #641 is
   merged and released: remove MAX_SPAN_HZ and the trim-on-refusal.
   REVIEWED 2026-11-10 by F4NRM: "Looks good", two non-blocking points, both
   done and the commit amended (a75c9098, force-pushed): the comment on
   dump_caps cites Hamlib's source for the label (tests/dumpcaps.c
   `fprintf(fout, "Spectrum spans: %s\n", prntbuf)`, permalink at Hamlib
   9199f8a2; src/sprintflst.c "%.0f " each) -- and corrects "ascending":
   Hamlib only requires the list to end with 0, the rigs list narrowest
   first; TODO.md's line carries "[#641](...) · rigctl: list the spans...".
   Reply posted (REPLY.md). MERGED 2026-11-10. Next: Mark checks whether
   it is in the overnight build; once in a release, remove MAX_SPAN_HZ and
   the trim-on-refusal from rigctl_sdr.py.
   PR 2 OPENED 2026-11-11: #666, "Refit the view when the span is changed
   from outside" -- option A below, as built: spectrum::refit_on_outside_
   span_change (decimation changed on the same device, not the value this
   screen's DEC chip asked for -- decim_asked), checked first in
   recenter_if_tuned_away; 3 tests + a ctr_zoom_sim case (Sim::dev_span).
   ALSO carries #641's review points: the maintainer merged #641's FIRST
   commit (90e783a), before the amended push, so the Hamlib citation and the
   TODO number were not in main. Checked on the Mac: the 4 new tests,
   ctr_zoom_sim 11/11, rigctld 58, red check, and at the station (wider,
   narrower, Brown's DEC chip keeps the zoom, CTR keeps the line in the
   middle; narrowing past the dial recentres -- Brown's own, expected).
   NOTE: brown's tree is LF now (aa485d0c6) -- plain git am again.
   Was: PR 2 NEXT: the waterfall refit -- OPTION A (Mark, 2026-11-10): interface
   only, no wire change -- brown's window refits to the whole new span when
   the decimation changes and that window did not ask for it (rigctl,
   another client); its own DEC chip keeps the zoom as today. Beside
   refit_on_window_growth in app/spectrum.rs; a ctr_zoom_sim case. Option B
   (a RadioState field marking rigctl changes, PROTO_VERSION bump) rejected:
   a wire change for what is basically one user.
   *App side when `spectrum_spans` lands:* read the spans from `\dump_state`
   at connect -- exact slider steps; remove MAX_SPAN_HZ and the 2 s pause
   at the top (SPAN_SETTLE_SECONDS' trim). None of our PRs added a
   `\dump_state` line -- #452 and #454 set bits in the existing level masks.
   RELEASED in brown pre-release v2.2.3.6.5_brown (2026-11-05, tag on main
   35a6c197) -- no build from main needed for the span. #491 (APF) is NOT in
   that tag; it comes in the next pre-release.
   Upstream SDRoxide: offer #479's change there too, later.
   *NEXT, once it works on the station:* ask brown to make the DEVICE RATE
   readable over rigctl -- #479 already carries it in RigState
   (`device_rate_hz`); it just is not exposed. With it the app computes the
   exact spans (rate / 2^n), as for SDRangel, instead of guessing. Until
   then `rigctl_sdr.MAX_SPAN_HZ = 20 MHz` is a GUESS (just above a HackRF):
   the slider starts with steps the device cannot reach -- up to 12.3 MHz
   for an RTL-SDR at 768 kHz -- trimmed once a drag past the top shows the
   limit. Remove the guess when the rate is readable.
   Then the same for brown.
8. CW PEAK FILTER (2026-11-04): SDRoxide (upstream and brown) has no receive
   audio peak filter, so the CW lamp stays greyed. Moderate work -- the
   peaking biquad exists (brown `sdroxide-dsp/src/eq.rs`, transmit EQ), it
   would sit beside the auto-notch stage, CW only, ahead of AGC; needs a
   state field (wire change: PROTO_VERSION + round-trip test), a chip and
   pop-up in eleven languages, and Hamlib `APF` over rigctl. ASK FIRST: issue
   drafted, sdroxide/brown/brown_issue_cw_peak.md; SUBMITTED 2026-11-04
   (issue #468). ANSWERED 2026-11-05: a
   cautious go-ahead -- we write it, built so it can be REVERTED cleanly.
   WRITTEN 2026-11-05 (brown_cw_peak.zip, branch brown-cw-peak, one commit on
   brown main a132702f): RxState.cw_peak (on, width 20-200 Hz, lift 1-20 dB),
   per mode; SetCwPeak, wire 268 -> 269; filter after the decoder tap and ahead
   of the AGC, CW only, centred on the passband middle (the pitch); rigctl
   U/u APF switch, L/l APF width (0 widest .. 1 narrowest), only where the
   filter runs, refused outside CW; APF chip greyed where the rig supplies
   the audio; 8 messages x 11 languages; manual; brown's TODO.md; PR text with
   git revert + manual rollback. NOT COMPILED here -- build, tests and fail
   checks on the Mac -- all green. PR #491 OPENED and MERGED 2026-11-05, on brown main
   35a6c197 (v2.2.3.6.5_brown). App side once released: the CW lamp found at
   connect through `U APF` / `L APF`.
   APP SIDE BUILT 2026-11-05 (app_apf.zip): APF a switch beside NB/NR/notch
   (the CW lamp), found by READING it (Brown refuses a set outside CW, so
   sending it back would have greyed it when connected in USB); its pop-up a
   continuous Width knob, 20-200 Hz; the lamp greyed outside CW, saying why.
   test_apf.py 6/6. CONFIRMED at the station 2026-11-05: the lamp switches
   Brown's APF, the knob sets its width and follows a width set in Brown.
   *Upstream SDRoxide too (Mark, 2026-11-05):* brown is CB- and listening-
   focused; the ham CW peak belongs in dividebysandwich/sdroxide as well. Once
   #491 has been reviewed and merged (so brown's review points are folded in),
   port it as its own branch off upstream main -- upstream's PROTO_VERSION,
   its own languages and rules, the same rigctl APF -- with the span (#479)
   as a separate PR beside it. Ask upstream first in a short issue, as for
   brown.
   *VFO A/B and split with SDRoxide (Mark, 2026-11-05):* today the app uses
   only SDRoxide's current VFO (F, M, J); its VFO B, A/B selection and SPLIT
   are never read or set -- the poll's split check is an empty placeholder
   and SDR_Link._from_sdr_split does nothing. Over rigctl Brown has all of
   it: V VFOA/VFOB, S/s (split and the TX VFO), I/i (the TX VFO's
   frequency). FIRST: wire VFO A/B so an action in SDRoxide is KNOWN -- the
   poll reads which VFO is active (and B's frequency), and reports a change
   made there, the rig leading as for RIT. SPLIT ITSELF probably DEFERRED:
   mirroring the rig's split into SDRoxide (TX frequency on the other VFO,
   SPLIT lit) is display only, and open questions are whether it goes both
   ways and whether Brown draws a TX marker in split (its manual says only
   XIT does).
   *VFO A/B DONE 2026-11-06 (vfo_sync.zip), to check at the station.* Over
   rigctl, where the SDR has two VFOs (found at connect: "v" names one and
   "f VFOB" answers -- SDRoxide, Brown; a program that then refuses V or
   "F VFOB" drops back to one VFO): the SDR's ACTIVE VFO is the rig's
   receive VFO, and its OTHER VFO holds the rig's other VFO's frequency
   ("F VFOx hz", which Brown takes outside VFO mode) -- so in split the SDR's
   other VFO is the TX frequency. A or B chosen IN THE SDR is asked of the
   rig (toggle_vfo), the rig leading: the SDR's new reading is not taken for
   a QSY, nothing is sent back while it waits, and if the rig has not
   switched in VFO_CONFIRM_SECONDS (2 s) -- or is transmitting -- the SDR is
   put back on the rig's VFO. The poll reads "v" before "f". Gqrx and SDR++
   follow the rig's receive frequency on their one VFO, as before. Brown
   keeps ONE mode for both VFOs (its get/set_mode ignore the VFO): on a
   switch the rig's receive VFO's mode is sent, as always. Split itself
   (SPLIT lit in the SDR, S/s) still deferred. test_vfo_sync.py 9/9 (0/9 on
   the old files).
   FIXED 2026-11-08 (vfo_hold.zip; Mark: A->B then quickly back to A, and
   SDRoxide's late B -- with B's frequency -- was pushed onto the rig):
   SDRoxide applies "V" late and its profile has no settle window, so its
   late reading looked like the operator's. Now after the app switches the
   SDR's VFO, "v" and "f" are not reported for VFO_SETTLE_SECONDS (3 s),
   held by time alone (a matching read does not end it -- straight after
   A->B->A the SDR still reading A is just the SDR not having moved yet).
   When the hold ends, an SDR not on the VFO sent is sent it again rather
   than taken as the operator's choice. A tune made in the SDR within those
   3 s is reported once they are over. test_vfo_sync.py 12/12.
   ROOT CAUSE FOUND 2026-11-08 (vfo_named.zip; Mark: SDRoxide "doesn't
   switch back" and its B is forced onto the rig's VFO A): Brown parses a
   bare "F hz" against the VFO its last PUBLISHED state calls active (proto.rs:
   `vfo = st.active_vfo` from the snapshot), and "V" is applied later by the
   engine -- so "V VFOB" then "F <B's frequency>" wrote B's frequency onto A.
   Back on A, SDRoxide showed B's number, and after the hold it was reported
   and pushed onto the rig. Now, with two VFOs, the active VFO's frequency is
   always sent NAMED ("F VFOB hz"). test_vfo_sync.py 13/13; the old code
   reproduces the overwrite. Worth telling Brown (an issue): a bare F right
   after V lands on the previous VFO.
   SPLIT TRANSMIT FIXED 2026-11-08 (vfo_split_tx.zip; Mark: in split,
   SDRoxide switched to VFO B on transmit): KD8CEC's startTx makes the other
   VFO active while transmitting in split and swaps back after (ubitx_20.ino),
   reporting the swap BEFORE it reports TX. Now, with split on, a change of
   the rig's VFO waits SPLIT_TX_GRACE_SECONDS (0.4 s) for a transmit to show,
   and while transmitting in split nothing is sent -- the SDR stays on the
   receive VFO and its frequency. A real A/B press in split goes through after
   the grace. One-VFO SDRs keep the old behaviour (they follow receive, which
   moves to the TX frequency during the swap) -- to look at if it matters.
   test_vfo_sync.py 15/15. Split transmit CONFIRMED at the station 2026-11-08.
   RIT KEPT ACROSS A VFO SWITCH (Mark, 2026-11-08; rit_per_vfo.zip): the
   firmware has one RIT and its VFO switch turns it off (menuVfoToggle:
   FrequencyToVFO, then ritDisable) -- the VFO left keeps base + offset and
   the base is lost. The link now tells the two "RIT off"s apart (a VFO
   already changed when cr_ 0 arrives = the switch did it), REMEMBERS the
   base per VFO, and on coming back puts RIT back: the VFO to the base, RIT
   on, receive back to base + offset, each step on the rig's report, given up
   after 3 s. Not while transmitting, locked or in split; RIT the operator
   turned off is not put back. FOUND ON THE WAY: _leave_rit ran on the
   switch's "RIT off" and wrote the OLD VFO's base onto the NEW one (VFO B
   jumped to A's base) -- the old code shows it in the test. test_rit_vfo.py
   4/4 (0/4 on the old files). CONFIRMED at the station 2026-11-08 -- RIT comes back on
   return, with SDRoxide's bracket.
   TWO MORE (Mark, 2026-11-08; rit_both_vfos.zip): (1) a different RIT on
   each VFO "lost all RIT" -- a restore cut short by switching again popped
   the VFO's memory, and the restore's first step had already moved the VFO
   to the base, so even kept the offset would read 0. Now each VFO keeps
   (base, receive), and a restore cut short puts it back in memory.
   (2) Switching in Brown kept one RIT for both VFOs: Brown has ONE RIT and
   leaves it on across its VFO switch, and the link pushed that stale RIT at
   the rig's new VFO. Now for VFO_RIT_QUIET_SECONDS (4 s) after the receive
   VFO changes, from either side, a RIT seen in the SDR is not asked of the
   rig; the SDR is given the rig's (that VFO's own, or none).
   test_rit_vfo.py 6/6, test_vfo_sync.py 16/16. From the app: CONFIRMED.
   From Brown, RIT still vanished (Mark): Brown's frequency moves several
   times while the rig switches and puts that VFO's RIT back, reported late
   -- taken as a tune, it was a QSY, and a QSY clears RIT. Now a frequency
   from the SDR is not believed for the same VFO_RIT_QUIET_SECONDS after a
   switch (rit_from_brown.zip). test_vfo_sync.py 17/17.
   AND A FIRMWARE OVERWRITE (Mark: RIT on A, switch to B, B takes A's
   frequency; rit_switch_fix.zip): menuVfoToggle selects the new VFO, then
   ritDisable() calls setFrequency(ritTxFrequency) -- tuning the NEW VFO to
   the OLD one's RIT base. cv arrives before the frequency reports, so the
   link notes the new VFO's own frequency there (_rit_switch_to) and, once
   cr_ 0 shows the switch cleared RIT, writes it back -- unless that VFO has
   its own RIT to restore, which puts it right anyway. test_rit_vfo.py 6/6
   (the old code shows B on A's base).
   A/B, A⇄B, A→B -- THE USUAL MEANINGS (Mark, 2026-11-08: "our definition
   is the wrong one"; vfo_exchange.zip). The app's "A⇄B" only SELECTED the
   other VFO; elsewhere -- Brown's A<->B, most rigs -- it EXCHANGES contents.
   Now three buttons: A/B selects (the old behaviour), A⇄B exchanges
   frequency and mode (uBITX_Link.exchange_vfos: the other VFO written with
   the active one's through the borrow, then the active one with the other's;
   remembered RITs go with their contents), A→B copies. Not with RIT on (a
   note under the buttons says to turn it off), transmitting or locked.
   Brown's own A<->B is now SEEN as an exchange (the poll reads both VFOs:
   each holding the other's old frequency) and done on the rig the same way,
   in the RIT/frequency quiet window; with RIT on, transmitting or locked,
   Brown is put back to the rig's VFOs instead. ALSO: notes cleared with
   text="" never cleared -- sCTk labels ignore an empty string -- in the CW
   tab, the callsign note, the scan note, the decoder note and the backup and
   EEPROM dialogs' status lines; now a space. test_exchange.py 6/6 (1/6 on the
   old files); test_cw_values.py updated for the space. A⇄B CONFIRMED at the station 2026-11-09 from the app and from
   Brown.
   RIT IN SPLIT, KEPT BY THE APP (Mark, 2026-11-09; rit_split.zip). In the
   firmware RIT and split do not mix: startTx with RIT on sends on the RIT
   base and never reaches the split swap -- split silently ignored on
   transmit while the display says split. But in split the receive VFO's
   frequency is never used to transmit, so the APP keeps RIT there
   (model.rit_virtual): base remembered, the receive VFO really tuned to
   base + offset, the firmware's RIT left off so transmit goes to the other
   VFO; off -> the base written back. Out of split the firmware's RIT is
   still needed: only it can change frequency at the instant of keying.
   Hand-offs: split ON with the firmware's RIT on (it clears it without
   retuning, cr_ 0 then cs_ 1 -- the link waits SPLIT_RIT_WAIT_MS to tell
   that from the operator) -> carries on as the app's, receive unchanged;
   split OFF with the app's -> the firmware's real RIT (VFO to base, RIT on,
   receive back). The firmware's transmit swap in split leaves the app's RIT
   with its VFO (rit_offset now uses rit_vfo); A/B in split keeps each VFO's.
   RIT on the transmit VFO (XIT) is not offered -- the firmware has none.
   The app's RIT button and the SDR's RIT both go through
   toggle_rit_for_operator. test_rit_vfo.py 10/10 (the firmware stand-in now
   does split and the transmit swap as ubitx_20.ino does). To watch: the RIT
   lamp may flicker off for the length of each transmit in split (the swap
   hides it, the return brings it back). EXCHANGE with RIT: refused while RIT is on (the
   firmware's or the app's) -- the A⇄B note asks to turn it off; Brown's
   swap is undone. Remembered RITs travel with their contents -- and, fixed
   2026-11-09, the app's split ones too (rit_split_xchg.zip).
   EXCHANGE WITH RIT ON (Mark, 2026-11-09; xchg_with_rit.zip): a RIT is part
   of its VFO's contents and now goes with them. exchange_vfos takes the
   active RIT off first -- the firmware's turned off (cr_ 0 marked as the
   exchange's, so it is not "the operator leaving RIT"), the app's dropped --
   carries base and receive frequency to the other VFO as a remembered RIT
   (the app's kind in split, the rig's else), and if the arriving contents
   bring a remembered RIT it is put back on the active VFO at the end.
   Brown's A<->B with RIT on goes ahead too. test_rit_vfo.py 13/13;
   test_exchange.py updated.
   STATION TESTS A-D (Mark, 2026-11-09), four fixes, test_rit_vfo.py 19/19:
   (1) a borrow's cv in split was taken by the app's-RIT branch, so A<->B
   with the app's RIT was abandoned on the other VFO (+1800 shown) and
   tuning the transmit VFO failed the same way -- the borrow is checked
   first now. (2) D3b, RIT on both then split, A<->B: a RIT remembered as
   the rig's kind becomes the app's, so it shows on the receive VFO at once.
   (3) THE TRANSMIT SWAP IN SPLIT showed as A/B -- panels traded places for
   the whole transmission (TX showed the receive VFO), the app's RIT jumped:
   a cv in split is held SPLIT_TX_GRACE_MS (450) with the roles frozen; a
   transmit makes it the swap, none makes it A/B. Confirmed at the station:
   transmit on the right VFO, display steady. (4) Brown was sent RIT -1700
   for a moment after an exchange -- the RIT now starts once the rig reports
   the new frequency. DECIDED (Mark): in split a VFO transmits on its
   contents, i.e. its receive frequency with any RIT offset, not its base.
   Still open: RIT on both, split on, plain A/B to the other VFO -- its
   rig-kind RIT shows only once split goes off (fix only if seen); the lock
   test's stand-in lacks toggle_rit_for_operator (8/10, test not app).
   2026-11-10, FULL RE-RUN A-F, app and Brown -- ALL PASS (Mark). Fixed on
   the way: RIT off at +0 never repainted (_decide_rit_off now notifies);
   D5 -- the other VFO's remembered RIT becomes the app's when split goes on;
   Brown's A/B was also reported as A<->B (rigctl_sdr: the remembered pair
   swaps with the names, no exchange check that poll); SPLIT NOW SYNCS BOTH
   WAYS with Brown (rigctl "s"/"S", _follow_split/_from_sdr_split, rig
   leads, SPLIT_CONFIRM_SECONDS 3, test_split_sync.py 6/6); RIT off in Brown
   just after a VFO switch was ignored -- the quiet window ends once the rig's
   RIT has been given the SDR. RX/TX shown as blue badges, VFO in capitals.
   Tests: test_rit_vfo 21/21, test_exchange 8/8, test_vfo_sync 18/18.
   The D5 "fix only if seen" item is DONE. The lock test's stand-in fixed 2026-11-10 (10/10).
   Noted: TX lands ~950 Hz above the dial in USB -- check whether it is the
   audio tone or calibration (master cal).
   FREQUENCY CALIBRATION (Mark, 2026-11-10). FIRST CHOICE: a routine in the
   app on WWV -- the rig's own receive on 10 MHz in CW through the rig's
   speaker, tuned until the carrier sits at the CW tone (or matched to a
   reference tone the app plays at the pitch); dial minus 10.000.000 is the
   VFO error -> a suggested master cal, written with the backup dialog's
   confirm-and-restart flow, then checked again (the cal's units are not
   certain: measure, adjust, measure). Fixes TX too (same VFO). The SDR's
   ppm the same way, clicking WWV's carrier in Brown. LATER OPTION: measure
   the rig's CW carrier with the SDR -- rigctl cannot report where a signal
   is (no Hamlib command; STRENGTH is only a level); Brown's TCI server can
   stream IQ (iq_start), so a short FFT during key-down would find the
   carrier to a few Hz. The SDR must be calibrated first (an RTL-SDR
   without a TCXO can be tens of ppm off), and measure in CW, not USB.
   *An .app as the SDR location (Mark, 2026-11-08; mac_app_path.zip):*
   SDR settings' location naming /Applications/sdroxide-Brown.app failed
   with "Permission denied" -- a bundle is a folder, and sdr_launcher ran it
   as a program. Now an .app path on the Mac is opened with `open -a <path>`
   (that copy, not another of the same name); other paths run as before.
   test_mac_bundle.py 4/4 (2/4 on the old file). CONFIRMED at the station
   2026-11-08 with Brown's pre-release, and APF (#491) works in it. Still to watch: finding the
   started process to close it later, and the quit, go by the profile's app
   name -- with Brown and SDRoxide sharing one, see the app-name item.
   *RIT on SDRs without RIT -- FIXED 2026-11-11 (sdr_rit_tuning.zip):*
   since RIT went to Brown (sent the base, with J for the offset), SDRangel,
   SDR++ and Gqrx were ALSO sent the base -- the code took `rit_offset` to be
   0 for them, but it is the rig's -- so with the rig's RIT on they sat on
   the base while the rig listened at the offset. Now `SDR_Link._sdr_tuning`
   subtracts the offset only for an SDR with RIT; the others get where the
   rig listens. Found reading the code; CONFIRMED with SDRangel at the
   station 2026-11-10 (RIT tuned, SDRangel followed; RIT off, back).
   test sdrrit/test_sdr_rit_tuning.py 4/4 (2/4 on the old file); RIT/VFO
   suites still green. *To check:* SDRangel, RIT on at the rig, tune RIT --
   SDRangel's channel moves with it; RIT off -- back to the dial.
   *SDRangel VFO B -- DROPPED (Mark, 2026-11-10: too complicated).* Kept for
   the record: SDRangel has no VFO A/B -- the
   REST transport keeps its one channel on the rig's receive frequency. To
   show VFO B there would need new REST code in rest_sdr.py: a second
   channel (a demodulator, or a marker) created in the device set and kept
   on the rig's other VFO -- muted unless chosen, and removed on disconnect.
   *RIT display:* Brown draws the RIT offset on its panadapter (a dashed dial
   line and a labelled bracket) whenever its RIT is on, which our `J` turns
   on. CONFIRMED 2026-11-06: it shows with RIT on at the rig.
   *A second receiver (Mark, 2026-11-05):* Brown's SUB is a second receiver
   in the same dongle's stream, in the right ear -- in split, the TX side
   while the main listens to the DX. Not reachable over rigctl ("SUB" there
   is only another name for VFO B). Would need a Brown rigctl addition --
   Hamlib's DUAL_WATCH function for the switch, the other VFO for where it
   sits -- asked in an issue first, like #491. A second DONGLE is a second
   radio tab in Brown, its own waterfall and audio; nothing for the app to
   drive there yet.
   *Startup speed (2026-11-06):* the rig's start-up values arrived ~7 s after
   connecting though the rig sends them at ~2 s: they sat in the serial
   buffer while the window's constructor ran (UBITX_RIG_TIMING in
   ubitx_link.py prints when). Fixed in the app (channels_lazy.zip): the
   channel table, its editable columns and its set menu are set only while
   the Channels tab shows. Opening Channels the first time now pays the
   table's fill. CONFIRMED 2026-11-06: first byte read at +2.64 s, was
   +6.85. Library causes in "Library code" above.
   *Lock, TX off and rig mode (2026-11-06, lock_quiet.zip):* the rig's LOCK
   now greys every control in the app that changes the rig or the SDR --
   band, mode, A/B, A->B, split, RIT and the offsets, the filter, the lamps
   and their pop-up knobs, volume, RF gain, the span, the receiver choice,
   channel tuning and scans -- and their handlers refuse too; Lock and TX off
   stay live. THE SDR RULES (Mark): a tune, mode or RIT change made in the SDR
   still goes to the rig while locked -- what is received has changed -- and
   everything changed in the SDR shows. TX OFF is KD8CEC's PRACTICE MODE (its startTx() skips only the T/R
   relay; confirmed, no relay click): a hover says so, name kept. RIG MODE now
   mutes an SDR that has its own mute, and SDR mode gives its mute back as it
   was. Checked at the station 2026-11-06; three fixes after
   (lock_fixes.zip): the SDR status button no longer brings the filter
   buttons back under lock (one place, _show_filter_buttons, for capability
   and lock); the TX off hover was drawn behind the window on the Mac -- now
   a help-style window, raised; Log QSO, About, SDR settings and the
   radio-settings compare open centred over the app, not at the screen's
   top left (_over_app). Log QSO stays live while locked (Mark: right).
   test_lock_and_quiet.py 10/10, test_dialog_place.py 4/4. All three
   confirmed at the station 2026-11-06, the hover included.
   *Document (Mark, 2026-11-05):* the settings that stay in SDRoxide's own
   window because rigctl cannot reach them -- the APF lift, the NR engine,
   and the rest -- collected in one place in the user documentation. App side once it exists:
   the CW lamp found at connect through `U APF` / `L APF`.
Step by step in SDROXIDE_UPGRADE.md.

### SDRoxide Brown -- PRs submitted and all merged 2026-11-04; waiting on a release

Four PRs to madmedicnl/sdroxide-brown, from branches `brown-…` on our fork
AJ6CU/sdroxide (GitHub allows one fork per fork family, so the upstream
fork serves both). Patches, texts and steps: sdroxide/brown/ in the project
(BROWN_PR_INSTRUCTIONS.md). Rebased onto brown's main 2609ddd4 on 2026-11-04.
MERGED into brown's main by 2026-11-04 (fe0d1266): #451 (PR 1), #452 (PR 2),
#454 (PR 5). PR 3 not yet merged; its number: fill in. Not yet in a brown
release, so the `"sdroxide-brown"` entry is unchanged until one ships.
Follow-up to #451 from its review (2026-11-04): CW width centred on the
pitch, and the clamped width compared -- branch `brown-passband-followups`,
patch and PR text in brown_pr6.zip. PR #464. OVERLAPS #463, the
maintainer's own fix for the CW point (centred at the rigctl edge via
`mode_filter`/`centred_on`, filter_for unchanged). #463 does not cover the
clamped-width point. Plan: once #463 merges, cut #464 down to the clamped
width (compare the width `mode_filter` gives), rebased on main.
#463 MERGED 2026-11-04; the maintainer asked for exactly that. Trimmed
patch in brown_pr464_trimmed.zip, force-pushed; #464 MERGED 2026-11-04.
ALL brown PRs merged (#451 #452 #453 #454 #464 #465). The shipped
`"sdroxide-brown"` entry is UPDATED for them (Mark, 2026-11-05):
width_needs_mode_change false, settle_seconds 1.5, decoder_udp_port 9998,
and the local overrides dropped. This assumes a brown build from main
(25ba95d6 or later) until brown makes a release. CONFIRMED on the station
2026-11-05: wide/narrow in USB is one `M USB <w>` each, no hop; DEC on
127.0.0.1:9998 shows the copy; the SQL lamp lights with a threshold and goes
out at the bottom. The brown-… branches are deleted from the fork and the
clone, with local-test and the local rigctl-… names (2026-11-05). Nothing
left from this set.
Follow-up to #452 from its review: a test on dump_state's level masks --
branch `brown-level-masks-test`, brown_pr7.zip, PR #465 -- MERGED 2026-11-04. Its other point (`U NR 1`
can bring back an older engine if the operator switched engine and turned NR
off between two rigctl commands) is answered in #452: the radio state keeps
no engine while NR is off, so a fix would be engine-side. Awaiting his view.
#454 (PR 5) merged with no comments.
PR 3 is #453: the reviewer's WsjtxConfig round-trip test pushed to its
branch 2026-11-04 (0bcbb94a), 23 proto tests passing -- it was the only
thing blocking the merge. Rebased onto main 62fd7dc7 the same day (the
eleven .ftl files conflicted: both sides had appended messages; both kept)
and force-pushed; conflicts cleared. MERGED 2026-11-04. When brown releases
it: `"decoder_udp_port": 9998` in the shipped `"sdroxide-brown"` entry.
1. `brown-same-mode-passband` (#451, merged): a new width in the mode running sets
   the filter. When merged and released: in the shipped `"sdroxide-brown"`
   entry, `"width_needs_mode_change": false`, `"settle_seconds": 1.5`.
2. `brown-sql-agc` (#452, merged): SQL, AGC and NR strength levels. When merged:
   nothing to switch.
3. `brown-cw-text-udp` (#___): upstream's decoded-CW output, ported; brown's
   own "Decoded text over UDP" is JSON and never sends CW. DEFAULT PORT 9998
   in brown, not upstream's 9999, since brown suggests 9999 for its JSON
   feed. Protocol v264. When merged: `"decoder_udp_port": 9998` in the
   shipped `"sdroxide-brown"` entry. Most likely to need rebasing again:
   brown bumps the protocol version and adds translations often.
5. `brown-rf-gain` (#454, merged): RF level. Builds on #452 (PR 2). When merged:
   nothing to switch.
Until then the station runs a `local-test` build (all four merged, never
pushed), with the three settings above in `~/.ubitx_cec_desktop/
sdr_programs.json` under `"sdroxide-brown"`. After each merge: `git pull`
main, delete that PR's branch, and remake local-test from main with the rest.

### SDRoxide Brown as its own program -- the Mac app name is ambiguous (2026-11-03)

madmedicnl/sdroxide-brown has its own `"sdroxide-brown"` entry in
sdr_programs.json beside `"sdroxide"`. Its Windows install has a folder of
its own (`C:\Program Files\sdroxide-brown\sdroxide.exe`), but on the Mac
the two builds collide:
- Brown's disk image holds `sdroxide.app`, bundle name `sdroxide`, and the
  same bundle identifier as upstream (`com.github.dividebysandwich.sdroxide`).
- The Mac's file system ignores case, so `/Applications/sdroxide.app` IS
  upstream's `/Applications/SDRoxide.app`: only one can be installed there,
  and both entries' Mac paths start whichever it is.
- Opening "by name" (`launch_as_application`, `open -a`, and the osascript
  quit) can reach the wrong one, so brown's entry has it OFF for now.
- Both run as a process called `sdroxide`, so `running_process` cannot tell
  which is already running, and "attach to the one already open" may attach
  to the other.
Options, not yet chosen:
1. Ask the brown maintainer for a bundle name and identifier of its own
   (e.g. `SDRoxide Brown.app`, `…sdroxide-brown`) -- fixes it for everyone.
2. Document renaming the app after installing, and point the entry there.
3. Rely on the SDR Path setting for brown (what we do today with the
   local-test build), and leave brown's Mac path empty.
Also: when both run, the rigctl `_` (get_info) reply may tell them apart --
both say "sdroxide <version>", but brown's version numbers differ from
upstream's. Checked in the source only, not yet against the two programs.

### SDR settings -- found 2026-11-04

1. BUILT 2026-11-05 (setup_cw_port.zip), to check on the station: a "CW
   port" line in Setup's SDR group, saved PER PROGRAM into your own
   sdr_programs.json (sdr_programs.set_user_setting; empty = the usual port
   back), moved to at once if DEC is on; greyed with the reason for SDRangel
   ("set up automatically") and for programs without a decoder. 4 tests.
   Was: **The CW decode port setting should be greyed for an SDR without decode
   over UDP.** Only a program whose entry has a `decoder_udp_port` (SDRoxide,
   SDRoxide Brown) can use it; for the others it should be shown greyed,
   with the reason, as other unavailable controls are.
2. BUILT 2026-11-05 (sdr_path.zip), to check on the station: choosing a
   DIFFERENT program on Setup clears the custom location (the same program
   again keeps it; a console line says so), and SDR settings' button is
   "Save", not "Keep". Per-program paths not done -- clearing was Mark's
   choice. 4 tests.
   Was: **The SDR path in the advanced dialog overrides the SDR program chosen --
   even when a different one is selected.** The "SDR Path" setting
   (`gv.config.get_sdr_path()`, handed to `sdr_launcher.start`) is one
   setting for every program, so a path set for one is used to start any
   other. It should belong to the program it was set for (keyed by the
   program in the settings), or at least be ignored for a different one.
3. BUILT 2026-11-05 (sdr_path.zip): "custom location set" beside Connect
   on Setup's Software line while a path is set.
   Was: **Say when the standard location is overridden.** If a path is set, the
   SDR settings box should say so, so users know to check the advanced
   setting -- otherwise a program that starts from an unexpected place, or
   will not start, has no visible cause.
4. ~~SDRoxide started muted: the app shows it unmuted.~~ CLOSED 2026-11-06:
   not reproduced with brown v2.2.3.6.5 -- started muted, the app showed it
   muted. (The code path was right all along: discover reads `u MUTE` and the
   connect redraw shows it.)

### Waiting on SDRangel -- workarounds, now version-gated

First checked against 7.27.2-1315-gc43757c88 (2026-09-27). Re-checked on
**SDRangel 8.1.0, 2026-11-11**, at the station, by curl with the app closed.
The app now reads SDRangel's version at connect (`GET /sdrangel`, said in
the console: "[sdr] SDRangel 8.1.0; its WDSP passband is read and written as
SDRangel's own") and leaves off the workarounds a build no longer needs. An
unreadable version counts as old, so every workaround stays on. Done in
sdrangel_version.zip (rest_sdr.py, sdr_controls.py, sdr_controls.json;
test sdrver/test_sdrangel_version.py 8/8, five fail without the change).
8.1.0 is the build tested; 8.0.0 may well have the same fixes but is
untested, so the gate is 8.1.0. Lower it only after checking an 8.0.0.

- ~~WDSP RECEIVER'S PASSBAND IS WRITE-ONLY over REST~~ FIXED in 8.1.0
  (SDRangel commit a0918b57 maps rfBandwidth to the WDSP high cut). Checked:
  `rfBandwidth -3000` then `lowCutoff -600` read back -3000 / -600 and the
  window showed LSB; back to USB read 3000 / 0. *Done:* `rest_sdr.
  PASSBAND_FIXED_IN = (8, 1, 0)`; `_stale_passband` is true only for a WDSPRx
  on an older SDRangel. On 8.1.0: separate PATCHes, the read-back check, and
  following SDRangel's own filter knobs again. *To check at the station:*
  USB/LSB/CW switches from the rig, and dragging the filter in SDRangel's
  WDSP window moves the rig's mode/width.
- ~~SSB DEMODULATOR'S dnrScheme IGNORED over REST~~ FIXED in 8.1.0: PATCH
  `{"dnrScheme":2}` read back 2. *Done:* `"read_only": true` replaced by
  `"read_only_before": "8.1.0"` in sdr_controls.json (a new key, parsed by
  `sdr_controls.parse_version`), so the NR pop-up's scheme knob turns on
  8.1.0 and stays shown-only on 7.x. *To check:* turn the scheme knob in the
  app with the SSB demodulator, and SDRangel's NR dialog follows.
- WDSP RECEIVER'S REPORT: NO LONGER CRASHES in 8.1.0 (commit cf483c06 fills a
  WDSPRxReport), BUT ITS channelPowerDB IS FROZEN -- 34.891578674316406 on
  noise and on a signal, while a Channel Power channel beside it read -64
  and -60. (Read in its source: `CalcDb::dbPower` of WDSP's
  `getMeter(RXA_S_AV)`, a constant ~3084.) So `REPORT_UNSAFE` keeps
  "WDSPRx" on every version -- safe now, but useless -- and the S-meter
  under WDSP still needs a Channel Power channel. *To report upstream:* a
  short issue, frozen channelPowerDB in WDSPRxReport (draft offered).
- NR DIALOG LEAVES THE SSB DEMODULATOR'S WINDOW IGNORING CLICKS
  (sdrangel_nr_dialog_click_report.txt). Nothing in the app to remove;
  not re-checked on 8.1.0 (optional).
- *Station setup after the 8.1.0 checks:* remove the temporary SSB
  demodulator; keep WDSPRx as channel 0 and one Channel Power; save.

### Much later

**Fork the theme builder** so a theme can be edited without hand-editing
JSON.

**Drawn corner rounding for the S-meters.** `corner_radius` was removed from
their inspector because it did nothing: the meter draws on a canvas that
covers the whole widget, and Tk cannot round a canvas. It would have to be
drawn -- a rounded rectangle filling the corners in the parent's colour,
masking them. The separator already uses that technique, so it exists in the
library. The complication is knowing the parent's colour, which breaks down
if the parent is transparent.

---

<a name="things-worth-not-relearning"></a>
### Things worth not relearning

Hard-won, and none of it obvious from a traceback.

**Names Tk and CustomTkinter have already taken.** Subclassing inherits a
large namespace, and the obvious names are mostly spoken for. Four collisions
in one session:

| Name      | Whose      | What happens |
| :---      | :---       | :--- |
| `_draw`   | `CTkFrame` | Called from its constructor with `no_color_updates`; overriding it means the widget cannot be built |
| `place`   | `CTkBaseClass` | Rejects `width` and `height` — they must go to the constructor |
| `lower`   | `Canvas`   | Lowers a canvas *tag*, not the widget. Use `tk.Misc.lower(widget)` |
| `state`   | `Misc`     | The window-state method. CustomTkinter's DPI tracker calls it on every open window |

The library's own convention avoids the first: the dials and S-meters use
`self.canvas` and `_draw_dial_base` / `_draw_meter` precisely because
`self._canvas` and `_draw` belong to `CTkFrame`.

**`_apply_font_scaling` takes a FONT, not a size.** It returns the whole
tuple with the size scaled; handed a bare integer it raises

```
ValueError: Can not scale font '38' of type <class 'int'>
```

**And a `try/except` around a call you got wrong turns a loud failure into a
feature that quietly does not work.** `sCTkNotebook` made exactly this
mistake inside a guard that swallowed it and returned the unscaled font, so
its tab labels never scaled on any display and nothing ever said so. It was
found only because the same line was written again in a widget whose guard
happened not to cover it.

Worth the general rule: a fallback should be a fallback from something that
works, not the path taken every time. If an `except` is always running, the
`try` is wrong.

**A guard must name an exception it can see.** `sctk_dial.py` does not import
`tkinter`, so `except tk.TclError` raised `NameError` from inside the
handler -- which aborted the binding pass and took the wheel handling with
it. The symptom was a dial responding to clicks and not to the wheel. Catch
`Exception` where the specific class may not be in scope.

**An unconsumed event fires once per bound layer.** `sCTkDial` installs its
scroll handlers on three layers -- the drawing canvas, the widget, and
`CTkFrame`'s own background canvas -- each with `add="+"`. The wheel handler
did not return `"break"`, so one physical detent propagated through all three
and stepped the dial two or three times.

It hid in plain sight for a while because a caller that COALESCES its
commands masks it completely: a transmit frequency whose writes were being
merged looked correct while a receive frequency ran away at about 2.5 steps
per detent. A layer that merges input can conceal a fault in the layer
producing it.

The trackpad handler had returned `"break"` all along, and applied a
cooldown, which is why one input device behaved and the other did not.

**`_apply_font_scaling` takes a FONT, not a size.** It returns the whole
tuple with the size scaled; handed a bare integer it raises

```
ValueError: Can not scale font '38' of type <class 'int'>
```

**And a `try/except` around a call you got wrong turns a loud failure into a
feature that quietly does not work.** `sCTkNotebook` made exactly this
mistake inside a guard that swallowed it and returned the unscaled font, so
its tab labels never scaled on any display and nothing ever said so. It was
found only because the same line was written again in a widget whose guard
happened not to cover it.

Worth the general rule: a fallback should be a fallback from something that
works, not the path taken every time. If an `except` is always running, the
`try` is wrong.

**A guard must name an exception it can see.** `sctk_dial.py` does not import
`tkinter`, so `except tk.TclError` raised `NameError` from inside the handler
-- which aborted the binding pass and took the wheel handling with it. The
symptom was a dial responding to clicks and not to the wheel. Catch
`Exception` where the specific class may not be in scope.

**`<TouchpadScroll>` arrived in Tk 8.7.** Binding it on an older Tk raises and
the widget cannot be constructed at all. `ScrollBindingMixin` has always
guarded this; the dial and the notebook did not, and failed on Python 3.13's
Tk while working on 3.14's.

**`"transparent"` is not a colour.** It means "take the parent's", and a raw
canvas cannot render the word. Any widget drawing on a canvas has to resolve
it by walking up for a real colour -- `sCTkNotebook`, `sCTkFileExplorer` and
now `sCTkDial` all do.

**The Designer sends every property when any one changes.** Harmless for most
widgets, but one that infers intent from a property being *absent* will see
the others arrive as empty. `sCTkSelector` reads a missing size as "fit the
contents", so editing the width also delivered `height=0` and collapsed the
height. Clearing has to be judged per property.

**The query default is what gets APPLIED when a field is cleared.** It is not
a display value. Reporting a plausible-looking number means clearing sets
that number. For a size, zero is the right default because it means "nothing
asked for"; for a colour, the theme value is.

**`ast.parse` is not `py_compile`.** It accepts a repeated keyword argument,
which is a compile-time error rather than a syntax error. A file can parse
and still refuse to run.

**`grep -c` counts lines, not occurrences.** A count quoted as a verification
target is wrong whenever a line contains the pattern twice. A count that goes
*down* after an additive change is a reliable signal that something was lost.

**The Nano drops a command that arrives while it is busy.** Not while it is
READING -- the 40 ms headroom covers that -- but while it is still CARRYING
OUT the last one: a frequency write, a toggle. A channel's mode sent straight
after its frequency was lost exactly so. Wait `STEP_SETTLE_MS` after a
command the rig takes time over. See `ARCHITECTURE.md` on headroom and
settle.

**Replies matched by order break on one lost reply.** Memory reads say
nothing about which slot they answer, so they are matched by position -- and
when two were dropped, every later reply was filed against the wrong slot,
plausibly. Send one at a time and wait for each. Where a reply names what it
answers, as the write acknowledgement names its address, match by that.

**Erased EEPROM reads as all ones.** A channel slot never written decodes to
536,870,911 Hz in mode 7. Distrust every value read from EEPROM: range-check
frequencies, check mode numbers against the ones that exist, keep only
printable characters in labels.

**Code that worked is not proof of what a report means.** `cs_` was taken
to carry no state because the old handler never read its value. The rig
showed otherwise. Press the control and read the console.

**A test that cannot fail proves nothing.** A check for a fixed bug has to
fail on the unfixed code first. The scanner's stray-timer fix passed its
first test with and without the fix, because the timer never landed in the
window that mattered; only a test that reproduced the stop showed the fix
working. Twice in the same session a test "failure" was the test's own mistake -- a
four-character byte string, a stand-in missing a method -- which is the
other half of the same rule: check the check.

**Tk owns the macOS application menu, and answers Quit with Tcl's `exit`.**
Not Python's: the interpreter is torn down where it stands, so `atexit`,
every `finally` and every signal handler are skipped. Quitting from that menu
left the rig's port open and an SDR still running, while closing the window
behaved perfectly -- a maddening pair of symptoms to hold at once.
`self.createcommand("::tk::mac::Quit", handler)` is the hook, and it is
harmless elsewhere.

**A shutdown must not hang off the window's close button alone.** For the
reason above, and because an application can end in half a dozen ways: the
close button, the menu, the main loop returning, an unhandled error, SIGINT,
SIGTERM, an IDE's stop. One `close_down()`, safe to call twice, reached from
every one of them. SIGKILL cannot be caught by anything, and is the one case
where the port and the SDR are left behind.

**Asking an application to quit has to go through the system, and that means
launching it as one.** A binary started directly is not a registered
application, so `tell application "Gqrx" to quit` has nothing to talk to. The
polite request fails silently, SIGTERM follows, and Qt does not handle
SIGTERM: Gqrx dies without writing its settings, reports an unexpected quit,
and forgets which SDR device it was using. `open -a` instead, and find the
process afterwards to know it is ours.

**An error from `osascript` does not mean the quit failed.** Gqrx answers a
quit with "User canceled (-128)" and then quits. Judging by the return code
declared failure about a program that had gone -- and, since Gqrx must never
be forced, left it alone. Only whether the process is still there settles it.

**A program still starting answers badly about itself.** Its remote control
accepts a connection before everything behind it is ready, so `l ?` comes
back empty and discovery -- taking that as final -- greys out volume, squelch
and the signal for the whole session. Ask again a few seconds later.
Autostart makes this the normal case rather than a rare one.

**A silent "nothing to do" is the hardest failure to read.** Closing printed
not a word about the SDR, which looked identical to leaving it alone
deliberately. Saying what it decided, and why, turned three rounds of
guesswork into one run.

**An exclusive device bends every ownership rule around it.** "Leave alone
what you did not start" is right until the thing you did not start is holding
the one dongle: then the program the operator has just chosen cannot open it,
and doing the polite thing means the switch fails silently. The rule did not
survive contact with the hardware -- what survived was asking. Ours and
stubborn: may we force it? Theirs at all: may we close it? Neither is decided
here, and with nobody to ask, nothing is taken upon ourselves.
