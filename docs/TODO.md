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

**Anchors: `id` rather than `name`.** Some renderers ignore `name` on an empty
anchor, so a table of contents entry silently fails. Where the heading text
matches the link, the auto-generated slug works without an explicit anchor at
all. Worth a sweep across the widget pages.

---

<a name="pygubu-designer"></a>
### Pygubu Designer

**Four upstream reports are written and ready to file.** Plus the preview
image issue.

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

* **The meters.** `cp_`, `al_` (S-meter) and `vm_` (power and SWR) are
  unwired, so both meters are empty. Wiring them also lets the scanner stop
  on a signal, which it cannot do today.
* **The CW tab** -- key type (`ck_`), speed (`vs_`), sidetone, the two delays
  (`vy_`, `ve_`) and the offset switch (`ch_`). Mostly WIRING: every setter
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
* **The RX tab** -- ATT (`vf_`) and IFS (`ci_`, `vi_`), the same way.
* **Lock, mute and TX-stop are handled as toggles.** RIT and split turned out
  to report their state (`1`/`0`); these probably do too. Press each and read
  the console. Mute matters most: choosing SDR++ as the receiver silences the
  rig by toggling it, judged by `model.muted`, which starts out assuming the
  speaker is on.
* **The CW offset switch (`ch_`).** The old code offset the transmit readout
  only when it was on; the new code always does. Right for this rig, wrong
  for one with it off.
* **Log QSO, the Setup tab, EEPROM backup and restore.** Setup's fields do
  not yet read or save the configuration -- including the MCU headroom, which
  the link hardcodes as 0.04 while the settings file holds its own value.
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
  entries in `~/.ubitx_cec_desktop_sdr_programs.json` are merged over the
  shipped ones entry by entry. SDRangel is ONE entry, driven over REST; its
  rigctl entry was removed (see `ARCHITECTURE.md`), and a saved setting
  naming it resolves to the REST one.

  Still to do there: a way to ask for a command line a program cannot guess
  at (rigctld carries the flag; nothing asks yet).

* **One folder for everything this application keeps.** Three dotfiles are
  loose in the home directory now, each found by its own rule:

      ~/.ubitx_cec_desktop.ini             settings
      ~/.ubitx_cec_desktop_channels.json   the channel sets and scan settings
      ~/.ubitx_cec_desktop_geometry.json   the window's size and position

  They should be one folder -- the settings, the channels, the window
  position, and in time the logbook and any decoder output -- so the
  operator can back the station up, copy it to another machine, or delete it,
  by taking one thing. Each platform has a place for this:

      macOS     ~/Library/Application Support/uBITX CEC Desktop/
      Linux     $XDG_CONFIG_HOME, else ~/.config/ubitx-cec-desktop/
      Windows   %APPDATA%\uBITX CEC Desktop\

  A home-directory dotfile is the Linux habit applied everywhere, and on a
  Mac it is invisible in Finder, which makes a backup harder rather than
  easier.

  **Move the existing files on first run**, and leave nothing behind: unlike
  the settings keys, these have no other reader to keep working. One helper
  that answers "where does X live", used by ConfigurationManager,
  ChannelSets and the geometry saver, replacing three separate expanduser
  calls -- so the next thing that needs a file does not invent a fourth rule.
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
   confirmed) is READ-ONLY -- accepted over REST and not applied, an
   SDRangel bug (see the notes and sdrangel_dnrScheme_report.txt); chosen in
   SDRangel's NR dialog, and followed. The middle knob is the scheme's own
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
   SDRangel -- a null pointer in its report code (see the notes; to report
   upstream). Never read it. The S-meter comes instead from a Channel Power
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
9. SDRangel set up BY the application -- LATER. (Step 8, arranging its
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
   change, the device centre goes to band start + bandwidth/2 -- never so far
   that the signal leaves the inner 80 % of the sampled band. The model's
   BANDS are (name, start, end) -- confirmed. *To check:* each step shows in
   SDRangel's spectrum; 20 m opens at 14.000 not below; the WDSP channel
   keeps working at every width; CPU at 1024k. The note below is the
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
*Possible recovery in software:* when the line comes back after being held
low during the boot burst, reboot the rig once more to get the burst again
-- ties in with the item below.

**Ask the rig for values that have not arrived.** *Half done.*

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

What is left: ASK for what has not arrived, rather than print it.

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
IFS, and the CW offset switch -- listed with the rest of the remaining work
under [The uBITX interface](#the-ubitx-interface). Some are deliberately
ignored: `vr_` (its value is a firmware figure, not the RIT base), `c0_`, the
greenbox lines, `cm_`, `vv_` and the spectrum reports.

*The four `comportManager` bugs that were here are superseded.* That module
is not used any more -- `serial_ports.py` replaced it -- so its missing
parentheses, its bare `except:`, its view work and its IPv6 handling are
history. The IPv6 fault outlived it, though, and is noted against the rig
connection above.

---

<a name="much-later"></a>
### Waiting on SDRangel -- workarounds to remove when fixed

Checked against 7.27.2-1315-gc43757c88, the latest build as of 2026-09-27.
After each SDRangel update, run the check; when it passes, remove the
workaround.

- WDSP RECEIVER'S PASSBAND IS WRITE-ONLY over REST
  (sdrangel_wdsp_cutoff_report.txt; notes: "WDSP receiver: the passband is
  write-only"). *Check, app closed:* PATCH `{"rfBandwidth":-3000}` alone to
  the WDSP channel, then GET -- fixed when it reads back -3000 and
  SDRangel's window shows LSB. Also drag the far cut in the window and GET
  -- fixed when the GET follows. *Then remove:* empty
  `rest_sdr.STALE_PASSBAND_CHANNELS` (one line). That restores the
  read-back check, following SDRangel's own filter knobs, and separate
  PATCHes without the passband riding along. Run the USB/LSB/CW switches
  again afterwards.
- SSB DEMODULATOR'S dnrScheme IGNORED over REST
  (sdrangel_dnrScheme_report.txt). *Check:* PATCH `{"dnrScheme":2}`, GET
  -- fixed when it reads 2. *Then remove:* the scheme's `read_only` in
  `rest_sdr.CHANNEL_DSP["SSBDemod"]`, so the NR pop-up's scheme knob turns.
- WDSP RECEIVER'S REPORT CRASHES SDRangel (notes; not yet reported --
  report text still to write). *Check:* ONLY with nothing unsaved in
  SDRangel -- GET .../channel/1/report on the WDSP channel. Fixed when it
  answers. *Then:* remove "WDSPRx" from `rest_sdr.REPORT_UNSAFE`, and the
  S-meter no longer needs a Channel Power channel under WDSP.
- NR DIALOG LEAVES THE SSB DEMODULATOR'S WINDOW IGNORING CLICKS
  (sdrangel_nr_dialog_click_report.txt). Nothing in the app to remove;
  listed so the report is followed up.

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
