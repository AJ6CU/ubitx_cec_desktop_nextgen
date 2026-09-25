## Architecture — the rebuild branch

Three protocols, one model, one view. Written first as the plan for the
rebuild, while the old code was still fresh; now kept as the account of what
was built and why, so the decisions can be checked rather than remembered.
Where the build departed from the plan, the section says so.

---

### Table of Contents
* [The layers](#the-layers)
* [Rules that keep it honest](#rules)
* [Adding a radio command](#adding-a-command)
* [What moves where](#what-moves-where)
* [Things to settle first](#to-settle)
* [The application's own data](#own-data)
* [What not to bring across](#leave-behind)
* [Testing without a rig](#stub)
* [Where it stands](#order)

---

<a name="the-layers"></a>
### The layers

```
    ┌──────────────────────────────────────────────┐
    │  View  (sCTk) -- ubitx_cec_desktop.py        │
    │  reads RadioModel · sends commands           │
    └───────────────┬──────────────────────────────┘
                    │ reads only          ▲ commands only
                    ▼                     │
    ┌──────────────────────────────────────────────┐   ┌──────────────────────┐
    │  RadioModel -- radio_model.py                │   │  The application's   │
    │  what the hardware last reported             │   │  own: ChannelSets,   │
    └───────────────▲──────────────────────────────┘   │  Scanner -- see      │
                    │ writes                           │  below               │
    ┌───────────────┴──────────────────────────────┐   └──────────────────────┘
    │  Transports                                  │
    │  uBITX_Link · SDR_Link · (SDRangel later)    │
    └──────────────────────────────────────────────┘
```

**The view never writes to `RadioModel`.** It sends a command and waits. The
protocol is already request-then-confirm, and the existing `_CB` methods
already honour it -- `split_CB` calls `Toggle_Split()` and changes nothing
locally. That discipline is what makes the rest possible, and it should not
be relaxed for convenience anywhere.

**The transports never touch the view.** They write to `RadioModel` and call
one notification. Today `cs_UX_SPLIT_Toggle` sets a button style *and* calls
`setSplitmode` on a widget; split those and the protocol handling becomes
portable.

**`RadioModel` knows nothing about either.** No widgets, no sockets, no
serial. It holds integers and answers questions.

---

<a name="rules"></a>
### Rules that keep it honest

**Stored once, as integer Hz.** No formatting in the model, no sidetone baked
into a stored value, no rounding. Everything else is derived when asked. The
three-forms problem -- `getIntPrimaryVFO`, `getFormattedPrimaryVFO`, and a
transmit frequency that is sometimes offset and sometimes not -- goes away
because there is one stored form and the rest are functions.

**Never store a consequence.** The RIT offset and the CW sidetone offset are
applied at display time. Storing them is how two values get out of step.

Each derived value needs its INVERSE if anything writes it back.
`role_frequency()` applies the CW offset for display and `role_to_vfo_hz()`
takes it off again for writing; they are a pair and must change together.
The offset's SIGN depends on the sideband -- CWL transmits above the dial,
CWU below -- and lives in one place, `cw_tx_offset()`. The first version
subtracted it for both, which put every CWL transmit readout out by twice
the tone. Without the second, a dial reading the displayed number and
writing the result silently loses the offset every turn.

**A method that cannot fail hides its misuse.** `frequency()` used to return
`vfo_b` for any argument that was not `"a"`, so passing a ROLE -- `"rx"` --
returned VFO B's frequency and the rig was told to tune to it. The symptom
was a dial that jumped somewhere unrelated; the cause took an afternoon. It
now raises, and the traceback names the mistake.

**Roles, not primaries.** Ask which VFO is receiving and which is
transmitting. `theVFO` spends about 228 lines on `_CW`, `_RIT`, `_SPLIT` and
three `ManageLabels` companions deciding what goes where; the question
disappears when receive is always left and transmit always right.

Transmit is **the VFO that is not displayed** when split, not VFO B. Primary
can be either, so with B active and split on, the transmit VFO is A.
Hardcoding B is right half the time, which is the worst kind of wrong.

`cv` reports **which VFO is primary**, 0 for A and 1 for B. It is not an
instruction to exchange the two frequencies -- doing that leaves the active
one always in `vfo_a`, so the model can no longer say which is which, and it
fights the `va`/`vb` handlers that write to a named VFO. Swapping contents is
a separate, deliberate command.

**The rig only writes to the primary VFO.** So writing to the other one --
the transmit frequency in split, a split offset, a copy -- means borrowing
the primary slot: toggle, write, toggle back. See `_begin_borrowed_write`.

**It confirms the TOGGLES, not the write.** A lost toggle leaves the rig on
the wrong VFO for good, so each waits for its `cv` report. A lost write heals
itself -- the rig's own `vb` report says where the VFO really is -- so the
write is sent and not waited on. The plan had the write matched against the
reported value; in practice that echo was unreliable and the wait bought
nothing. Each step also waits `STEP_SETTLE_MS` after its confirmation: the
Nano drops a command that arrives while it is still carrying out the last.

Notifications are **suspended for the whole borrow**, and the ROLES frozen
with them (`_frozen_active`), or the receive panel visibly flickers through
the borrowed VFO -- accurate, and confusing. `set_frequency("p")` still
resolves against the REAL active VFO, which is how a report during the
borrow lands on the right one.

**The two transports are not alike, and should not be made to look alike.**

*The rig is effectively synchronous.* Its RF is analogue and the Nano is idle
between commands, so a mode change is followed by the confirmation and
nothing else -- which is why the memory queue can rely on answers arriving in
order. The real hazard is the opposite one: a laptop can overrun a Nano
easily, which is what the MCU headroom, update period and read-wait settings
exist to prevent. Those values are tuned against real hardware and should be
carried across unchanged and unquestioned.

**Headroom and settle pace different things.** `MCU_COMMAND_HEADROOM`
(40 ms) is the least gap between ANY two commands, enforced inside
`sendCommandToMCU` with a blocking sleep -- it stops the Nano's input being
overrun. `STEP_SETTLE_MS` (150 ms) is waited deliberately, with a
non-blocking `after()`, after a command the Nano takes time to CARRY OUT: a
frequency write, a toggle. Commands 40 ms apart pass the first and are still
lost to the second. A channel's mode sent straight after its frequency was
dropped exactly so, which is why `tune_to()` waits between them.

*The SDR is asynchronous at its end but blocking in ours.*
`SDRPlusPlusController` drives rigctl from the same `after()` loop with
blocking sockets, so a slow or wedged SDR stalls the interface: `settimeout(2.0)`
at connect means a two-second freeze, and the `recv` calls that flush
acknowledgements set no timeout at all. The rig is protected from this by
pacing; the SDR is not protected at all.

The socket now times out after one second rather than never, so a wedged
SDR drops the connection instead of freezing the application for good. A
second's freeze is still possible, and a thread or a non-blocking socket
remains the proper fix -- the one place either earns its keep. Both transports are single-threaded
today -- neither imports `threading` -- so anything introduced there is new,
and its results must reach `RadioModel` through the Tk loop rather than
directly.

**Transport concerns stay in the transport.** Two in particular:

* *Starting from a known point.* The rig is REBOOTED when the link opens,
  with a firmware command. That does two jobs, and the second is easy to
  miss. It produces the burst of 26 values the rig sends as it boots, which
  is the only way this protocol offers to learn where the radio is -- and it
  guarantees the reader starts at a FRAME BOUNDARY. Connect to a rig already
  running and the reader joins a byte stream in progress: a partial frame,
  a checksum against the wrong bytes, and every later value read one
  boundary out. That is the memory-read failure below, arriving by a
  different route.

  It also means the silence of a toggle is an answer. The rig reports
  split, RIT, lock, transmit inhibit, the speaker and the active VFO only
  when they are NOT at their defaults, and a rig that has just started is at
  all of them -- which `RadioModel` matches exactly. On a rig that has been
  running, the same silence means "unknown".

  **Anything that replaces the reboot inherits both jobs.** Asking for values
  -- needed for a Pico or Teensy build, whose reboot differs or cannot be
  commanded, and for any connect that must not interrupt an operator -- has
  to resynchronise on the frame preamble and discard whatever precedes it,
  rather than assuming the first bytes to arrive are the start of a frame.
  And it has to ask about those six toggles rather than assume them.

* *The memory request queue.* Reads are answered in order, with nothing to
  say which slot an answer is for, so replies are matched by position. That
  is fragile: when the Nano dropped two of 38 reads sent on a timer, every
  later reply was filed against the wrong slot -- labels arrived as
  frequencies. So reads go ONE AT A TIME, each waiting for its reply; one
  that never comes is withdrawn from the queue and retried, so a lost reply
  cannot move another slot. Writes are safer: the `vn_` acknowledgement
  names the ADDRESS written, so each is matched to its own write. All in
  `uBITX_Link`; the view sees a model that fills in.
* *`readallvalues`.* A bulk dump at startup with no request or
  acknowledgement. Ugly, but containable: parse it in the transport and write
  the results into `RadioModel` like any other report. The view sees a state
  that fills in, not a protocol quirk.

**One change notification, not one per field.** `RadioModel.changed()` says
something changed without saying what, and the view recomputes. Per-field
observers look tidier and are a trap here: almost everything on screen is
derived, so `role_frequency("tx")` depends on eight separate values and a
view registered for "mode" would not know to redraw when split changed. The
alternatives are a dependency graph or every consumer registering for
everything, and the first person to add a derived value forgets one.

Recomputing cannot be out of step. The cost is handled by coalescing rather
than by making the notification cleverer: pass `RadioModel` a `schedule`
function -- normally a widget's `after` -- and a burst of reports, the
startup dump or an S-meter arriving ten times a second, becomes one redraw on
the next idle pass.

**The view redraws top-down, and is not an observer either.** `refresh()`
walks the components the window owns, calling `update_view(state)` on each
and setting its own labels. The components are passive: none holds a copy of
anything, none is told what changed, and none can disagree with the state
because they all re-read it.

Registering each panel as an observer would be indirection with nothing
gained -- the window builds them, so it already knows what needs telling --
and it would lose the explicit ordering, which matters when one panel's
layout depends on another having been laid out first.

**One bounded exception: a control may draw its own pending value.** A dial
sets its label as you turn it, before any confirmation. Two things make that
safe rather than a lie -- it self-corrects, because the confirmed value
replaces it the moment it arrives, and it expires, so a lost confirmation
shows reality again rather than a number nobody agreed to.

It lives in one place, `RolePanel.show_pending()`, used by the dial and the
split offsets alike. It is necessary because the alternative is a readout
that sits still for several hundred milliseconds after the wheel stops. It has to write the
label DIRECTLY rather than asking for a redraw: during a borrow the
notifications are suspended, so a redraw would not happen, and lifting the
suspension would bring the flicker back.

**The SDR follows the model, not the rig's reports.** `SDR_Link.follow()`
runs on every model change and sends SDR++ the RECEIVE role's frequency and
mode when they differ from what it last sent. Following `vc_` instead would
send the transmit frequency during every split borrow, when the primary VFO
briefly IS the transmit one. Each direction remembers what it last passed on,
so neither echoes the other.

**Preferences come through the observer.** Per-key is right THERE and wrong
for live state: preferences are independent of one another, change rarely,
and have distant consumers. `ConfigurationManager` already
notifies on change, and `channels`, `theVFO` and `piRadio` already use it.
Nothing should reach into the main screen for a preference -- that is how
`channels.py` ends up holding a reference to `mode_Button`.

---

<a name="adding-a-command"></a>
### Adding a radio command

The commonest change, and the one with the most places to forget. Four
questions, in order.

#### 1. Which direction is it?

**The rig tells us something** -- an `xx_UX_` handler. It writes the model
and nothing else. No widgets, no commands back.

**We tell the rig something** -- a command method. It sends and changes
nothing locally. The confirmation does the changing.

Most features need both, and they are written separately. A control that
sends *and* updates the model is the bug this whole arrangement exists to
prevent: the interface then shows what it asked for rather than what
happened, and the two diverge the first time the rig refuses.

#### 2. Does the model need a new field?

Only if the rig reports something that is not already derivable. Before
adding one, check it is not a CONSEQUENCE of what is already there:

* the band is a fact about the frequency -- `band_name()` computes it
* the transmit frequency in CW is the VFO minus the sidetone --
  `role_frequency()` applies it
* which VFO transmits follows from `active` and `split` -- `tx_vfo` says so

Storing a consequence gives you two things that can disagree, and they will,
because the rig reports one and says nothing about the other.

If it genuinely is new state, add it with the others in `__init__`, in the
units the rig uses. Frequencies are integer Hz. No formatting, no offsets
baked in.

#### 3. Does the value carry state, or only news?

**Check the firmware before assuming.** Some reports carry the new value and
some only say that something changed:

* `ct_UX_RX_TX_Mode` carries it -- the handler tests `value == "1"`
* `cs_UX_SPLIT_Toggle` and `cr_UX_RIT_Toggle` carry it too: `1` on, `0` off

**Check against the rig, not the old code.** This section used to give
`cs_` as the example of a report that carries NO state, reasoning that the
old handler flipped its own flag and never read the value. A trace from the
real rig proved that wrong -- turning split on while RIT was on produced
`cr_ 0` then `cs_ 1`. Code that worked had simply never looked. Both now read
the value, and act only on a genuine change.

Getting this backwards gives a control that works until a report is missed,
after which it is inverted forever. Press the control on the rig and read
what the console prints.

A report can also carry a value that is not what its name suggests: `vr_`
looks like the RIT base but reports a firmware figure -- 14.000.000 wherever
the radio is -- and is ignored.

#### 4. Who calls `changed()`?

**The reader does, once per command**, in `_reader` right after
`_delegate_command_processing`. Handlers do not call it themselves.

That is deliberate, and it was learned the hard way: for a while no handler
called it and none of them obviously needed to, so the model updated
correctly and the interface never redrew. Every feature looked individually
broken. One call in the one place that sees every report cannot be forgotten
per-handler.

The exception is anything that changes the model OUTSIDE a report --
`suspend_notifications` / `resume_notifications` around a multi-step
sequence, where the resume issues the redraw.

#### The checklist

| Step | Where |
| :--- | :--- |
| Add the command byte | `toRadioCommandDict` |
| Write the send method | `uBITX_Link`, sends only |
| Write the report handler | the `_input` inner class, writes the model only |
| Register the handler | `_delegate_command_processing` |
| Add model state, if genuinely new | `RadioModel.__init__` |
| Add a derived accessor, if it has one | `RadioModel`, next to its siblings |
| Wire the control | the view, calling the send method |
| Read it back | `refresh()` / `update_view()` |

Nothing in that list calls `changed()`. If you find yourself wanting to, ask
what is changing the model that is not a report.

#### Two traps worth naming

**Two `MODES` lists.** The firmware's is `("DFT","ERR","LSB","USB","CWL","CWU")`
-- default at 0, 1 skipped, then 2 to 5. The view has its own, of just the
four selectable modes. `MODES.index("USB")` is 3 in one and 1 in the other.
**The view passes mode NAMES; the link encodes them.** Never pass an index
across that boundary.

**Displayed is not stored.** `role_frequency()` applies the CW offset for
display; `role_to_vfo_hz()` takes it off before writing. A caller that takes
the displayed number, adds a step, and writes the result loses the offset --
a 1 kHz step moved 400 Hz while the tone was 600. Anything sending a
frequency the operator saw must convert.

---

<a name="what-moves-where"></a>
### What moves where

| Existing | Becomes |
| :--- | :--- |
| `delegate_command_processing` | Unchanged, in the rig transport |
| The 40-odd `xx_UX_` handlers | Same logic, writing `RadioModel` instead of widgets |
| The `_CB` methods | Nearly unchanged — they already only send |
| `theVFO` | Retired. `RolePanel` takes the view half, `RadioModel` the model half |
| `theVFO.primary_vfo_*_CB` | A `<Button-1>` per digit label — a mouse can hit the digit |
| `theVFO` tuning presets | Subsumed: choosing a digit *is* choosing the step |
| `piRadio` and the `mainScreen` handlers | `uBITX_Link` -- commands and reports, writing `RadioModel` |
| `comportManager` | Not yet brought across -- the serial port is still hardcoded |
| `ConfigurationManager`, `globalvars` | Unchanged, as planned. `gv.config` is created first at startup |
| `SDRPlusPlusController` | Gone. `RigctlSDR` drives every rigctl program; `SDR_Link` is still the only thing that talks to it |
| Its SDR++ launching in `mainScreen` | `sdr_launcher.py`, for whichever program is chosen |
| `sdrDashboard` popup | Gone. Volume and mute on Operate; receiver choice on RX; filter on Operate |
| `channels.py` and its window | The Channels tab, `ChannelSets`, and the channel file -- see below |
| The controller's scanning | `Scanner`, run by the application -- see below |
| `delayWarning` | Not needed: reads are paced, and the list is its own progress display |
| `Classic_uBITX_Control` | Left alone — see below |

**The child windows keep working unmodified.** They build their own
`tk.Toplevel`, and an sCTk root is a Tk window. What has to change is the
twenty-one attributes they currently reach into the main screen for: the
benign ones (`theRadio`, `after`, `master`, `delegate_command_processing`)
stay, and the widget references (`mode_Button`, `tone_value_Label`,
`key_speed_value_Label`, `delay_*_Label`, `primary_Mode_VAR`,
`theVFO_Object`) become reads from `RadioModel`. That is fewer lines than
they have now, and it removes the coupling that makes the main screen hard to
change.

---

<a name="to-settle"></a>
### Things to settle first

*Most of these are now settled; each says how.*

**Which VFO reports are authoritative.** The rig sends `vc`/`cc` for the
currently displayed VFO and its mode, *and* `va`/`ca`, `vb`/`cb` for A and B
specifically, *and* `cv` to set which is active. Three sources for two
values. `RadioModel` should take A and B from `va`/`vb`, the active VFO from
`cv`, and treat `vc`/`cc` as confirmation -- but that needs checking against
the firmware: if `va`/`vb` only arrive at startup, the standby readout would
go stale.

**Whether the rounding fix belongs in the transport.** *Settled:* the link
sets the finest tuning preset once, at connect, so no write is ever
truncated and nothing has to save and restore the preset around it. What
the rig would store is still known -- `as_the_rig_would_store()` -- for
matching a confirmation.

**A common backend interface.** *Settled, and it turned out to be two things.*

What a program IS -- its port, where it installs, what it calls its modes,
what it cannot do, how it must be shut down -- is DATA, and lives in
`sdr_programs.json`. None of it is logic, all of it goes stale when somebody
else ships a release, and adding a program should not mean editing Python.
An operator's own entries, in `~/.ubitx_cec_desktop_sdr_programs.json`, are
merged over the shipped ones ENTRY BY ENTRY -- not file over file, which is
how the theme works and what `Theming.md` warns about: a copy made last year
hides every block added since.

How a program is DRIVEN is code, chosen by the `protocol` its entry names.
`RigctlSDR` handles rigctl today; SDRangel's REST will be a second class, not
a variation on the first -- it addresses device sets and channels by index,
needs a discovery step to find the right demodulator, and can push changes
rather than be polled. The entry says WHICH transport; it never describes one.

One entry per WAY OF DRIVING a program, so SDRangel will have two, sharing
install paths and differing in protocol. A program that gains a second
interface gets a second entry, never a flag.

---

<a name="starting-programs"></a>
### Starting an SDR, and whose it is

Autostart makes the application responsible for somebody else's program, and
one rule decides everything about it:

> An SDR that was ALREADY RUNNING is the operator's: attached to, and left
> running. One this application STARTED is its own, and closes with it.

Quitting a control panel should not take down a receiver somebody was
listening to, and leaving a window nobody opened deliberately is as rude the
other way. Only a program held in `SDR_Link._program` is ever closed, so an
instance that was already running cannot be closed by mistake -- there is
nothing to close it with.

**The order on the way out is the part that bites.** Stop its receiver, close
our socket, THEN ask it to quit. Asking while the connection is still open
leaves its remote-control server holding a live client through its own
shutdown, which is how "Gqrx quit unexpectedly" and a configuration that
forgot which SDR device it used were produced, repeatedly.

**Ask, do not kill.** SIGTERM is not handled by a Qt application unless it was
written to, so it dies without writing its settings. Asking means the
system's own quit -- which means the program must have been LAUNCHED as an
application (`open -a`) rather than as a binary, or there is nothing to ask.
Whether it worked is judged by whether the process is gone, never by what the
request returned: Gqrx answers a quit with "User canceled" and quits anyway.
Some programs are marked never to be forced at all; a window left open is a
nuisance, a corrupted configuration is an evening.

**THE DEVICE IS WHERE THE RULE BENDS.** An SDR dongle belongs to one program
at a time, so switching from one program to another is not a matter of
preference: whatever holds the device has to go, or the program just chosen
cannot open it and the switch fails -- quietly, which is how this was missed
at first. Switching away from a program the OPERATOR had started only
disconnected from it, and the new one then found the device busy.

So closing is not always ours to decide, and the question asked depends on
whose the program is:

| | asked |
| :--- | :--- |
| ours, closes when asked | nothing -- it simply closes |
| ours, refuses to close | *force it?* — forcing may cost it its settings |
| theirs | *close it at all?* — they opened it; it is not ours to close |

Quitting is different from switching: nothing is waiting for the device then,
so a stubborn program is left running with its settings intact. Forcing
happens only where the alternative is a switch that cannot work.

**The questions go UPWARD.** `SDR_Link` holds two callbacks and opens no
windows -- the same rule that took the modal dialogs out of the rig's
transport. With nobody to ask, nothing is closed and the switch fails
honestly rather than taking a liberty.

---

<a name="own-data"></a>
### The application's own data

Not everything belongs to the radio. Two pieces sit beside the model rather
than in it, because the model's rule is that it holds what the hardware
reported.

**`ChannelSets` -- the operator's channel sets.** Named lists of channels,
any length, kept in their own file in the user's home,
`~/.ubitx_cec_desktop_channels.json`, beside the settings file and found by
the same rule. JSON because the sets are nested lists. The file is written
whole or not at all -- a temporary file swapped into place -- and a damaged
one is kept aside, never overwritten. It also holds the scan settings.

They used to live in the settings file and belong to the SDR++ controller,
which kept its own copy and saved it back on any change -- two copies, the
stale one liable to be written over an edit. Now the application owns them,
the controller keeps none, and the settings file entries are read once, to
move the sets over, and left for the old application.

The rig's twenty EEPROM slots are different: reported by the rig, so they
are in the MODEL (`channels`), and edited through a DRAFT that needs Write
to radio, because EEPROM wears out. Both kinds appear in the Channels tab as
SETS -- one word throughout, on screen and in the code.

**`Scanner` -- scanning, run by the application.** Some SDRs cannot scan, so
the application does: it tunes the RIG to each channel of the set on show,
through the same `tune_to()` a double-click uses, and the SDR follows the rig
as ever. It stops itself when the operator transmits or tunes away, telling
the second from its own retuning by waiting for the rig to report the
frequency asked for. The old "scan set" -- a separate list of channels to
scan -- is gone: you scan a set.

---

<a name="leave-behind"></a>
### What not to bring across

**`Classic_uBITX_Control`.** It reproduces the rig's 2x20 LCD, and almost
everything on it is better set elsewhere in the interface. The exceptions are
calibration, WSPR and the autokeyer, which were never in the Nextion
interface and have no protocol -- and each has a better home: calibration in
the uBITX System Editor, the autokeyer done properly from the laptop, WSPR
apparently unloved. So it stays a ttk `Toplevel` launched from Setup,
unchanged and untouched, and is a candidate for removal rather than a thing
to modernise.

**Spectrum and band scan.** Obsolete beside an SDR waterfall.

**The virtual keyboard and touch optimisation.** Nextion inheritance. There
is a real keyboard, and digit-click tuning replaces whatever touch
optimisation meant.

**The simulated signal strength.** `SDRPlusPlusController` reports
`random.uniform` because SDR++'s rigctl server does not expose it. A meter
showing plausible noise is worse than one showing nothing, because you cannot
tell it is lying. *Done:* `SDR_Link` does not connect that callback, so the
meter shows nothing until a real source -- the rig's own S-meter reports --
is wired.

**The "scan set" settings** in the settings file -- "Scan Set Settings", and
the controller's own channel and scan methods. Scanning is by set now, run by
the application. The settings entries stay only for the old application.

---

<a name="stub"></a>
### Testing without a rig

*The plan was a stub that stood in for the rig. It no longer does.* Once
`uBITX_Link` existed, thirteen of the stub's fifteen methods went uncalled,
drifted from the link twice, and ended up with different method names --
it could no longer have been swapped in. It was cut to what is still used:
the "simulate transmit" button and a placeholder for the SDR filter. A real
no-rig mode would need an interface both implement, designed as such.

What has taken its place is testing each piece against STAND-INS in a short
script: a model, a fake rig that answers after a delay or drops a command,
a clock that can be stepped. The channel reads, the writes, the borrow and
the scanner were all proven that way before reaching the rig -- including
reproducing a bug before fixing it, which is the only way a fix is shown to
work. A test that cannot fail proves nothing.

The original reasoning for the stub still stands, for any future no-rig mode:

**Wiring a mockup straight to its state object would be quicker and would
teach the wrong habit.** A control that sets `state.split = True` looks fine
until the rig refuses the command, and then the interface is showing
something the radio is not doing.

The 40 ms delay is deliberate. Answering instantly would hide any place the
interface assumes its command has already taken effect, and those are exactly
the bugs that appear when a real rig turns out to be slower than expected.

The test that matters: **no view code writes to the model.** Grep for it.
The exceptions are the two stub methods above, and they go when their real
sources are wired.

---

<a name="order"></a>
### Where it stands

The plan's order was: the model, then the rig transport with no view, then
the view, then the child windows, then the SDR. That is how it went, and the
risky part -- the protocol -- was proven first.

**Built:**

* `RadioModel`, with roles, split, RIT (the VFO moves; the base is held), the
  sideband-signed CW offset, and the rig's memory channels.
* `uBITX_Link` -- the handlers that matter, split and the borrow, RIT, mode
  on both VFOs in split, split offsets, paced channel reads, address-matched
  writes, and `tune_to()`.
* `SDR_Link` over `SDRPlusPlusController` -- both directions, the filter,
  and volume and mute behind it.
* The desktop: Operate, RX, Channels. Channels reads, edits and writes the
  rig's memories, edits the operator's own sets, copies between them, and
  scans.
* `ChannelSets` and `Scanner`, above.

**Still to do** -- the list is in `TODO.md`. The two that matter most: the
rig connection dialog, since the serial port is still hardcoded; and the
meters, which would also let the scanner stop on a signal.
