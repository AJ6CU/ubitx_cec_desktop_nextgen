## Architecture — the rebuild branch

Three protocols, one model, one view. This is the shape the rebuild should
take and the reasoning behind it, written while the existing code is still
fresh so the decisions can be checked rather than remembered.

---

### Table of Contents
* [The layers](#the-layers)
* [Rules that keep it honest](#rules)
* [Adding a radio command](#adding-a-command)
* [What moves where](#what-moves-where)
* [Things to settle first](#to-settle)
* [What not to bring across](#leave-behind)
* [Testing without a rig](#stub)
* [Suggested order](#order)

---

<a name="the-layers"></a>
### The layers

```
    ┌──────────────────────────────────────────────┐
    │  View  (sCTk)                                │
    │  reads RadioState · sends commands           │
    └───────────────┬──────────────────────────────┘
                    │ reads only          ▲ commands only
                    ▼                     │
    ┌──────────────────────────────────────────────┐
    │  RadioState                                  │
    │  what the hardware last reported             │
    └───────────────▲──────────────────────────────┘
                    │ writes
    ┌───────────────┴──────────────────────────────┐
    │  Transports                                  │
    │  piRadio · SDRController · (SDRangel later)  │
    └──────────────────────────────────────────────┘
```

**The view never writes to `RadioState`.** It sends a command and waits. The
protocol is already request-then-confirm, and the existing `_CB` methods
already honour it -- `split_CB` calls `Toggle_Split()` and changes nothing
locally. That discipline is what makes the rest possible, and it should not
be relaxed for convenience anywhere.

**The transports never touch the view.** They write to `RadioState` and call
one notification. Today `cs_UX_SPLIT_Toggle` sets a button style *and* calls
`setSplitmode` on a widget; split those and the protocol handling becomes
portable.

**`RadioState` knows nothing about either.** No widgets, no sockets, no
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
`role_frequency()` subtracts the sidetone for display and
`role_to_vfo_hz()` adds it again for writing; they are a pair and must
change together. Without the second, a dial reading the displayed number and
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

**The rig only writes to the primary VFO.** So setting a transmit frequency
in split means borrowing the primary slot: toggle, write, toggle back. That
sequence waits for each confirmation rather than firing three commands at
once -- the write can otherwise reach the rig before the toggle has taken
effect and land on the wrong VFO. See `_begin_tx_write`.

Two details it needs. The write step **matches the reported value**, because
toggling makes the rig report the newly-primary VFO's existing frequency and
that echo is not the confirmation. And notifications are **suspended for the
whole borrow**, or the receive panel visibly flickers through the borrowed
VFO -- accurate, and confusing.

**The two transports are not alike, and should not be made to look alike.**

*The rig is effectively synchronous.* Its RF is analogue and the Nano is idle
between commands, so a mode change is followed by the confirmation and
nothing else -- which is why the memory queue can rely on answers arriving in
order. The real hazard is the opposite one: a laptop can overrun a Nano
easily, which is what the MCU headroom, update period and read-wait settings
exist to prevent. Those values are tuned against real hardware and should be
carried across unchanged and unquestioned.

*The SDR is asynchronous at its end but blocking in ours.*
`SDRPlusPlusController` drives rigctl from the same `after()` loop with
blocking sockets, so a slow or wedged SDR stalls the interface: `settimeout(2.0)`
at connect means a two-second freeze, and the `recv` calls that flush
acknowledgements set no timeout at all. The rig is protected from this by
pacing; the SDR is not protected at all.

That is worth fixing during the rebuild, and it is the one place a thread or
a non-blocking socket earns its keep. Both transports are single-threaded
today -- neither imports `threading` -- so anything introduced there is new,
and its results must reach `RadioState` through the Tk loop rather than
directly.

**Transport concerns stay in the transport.** Two in particular:

* *The memory request queue.* Requests are answered in order, and the byte
  count for each is known in advance. That is a protocol detail -- a pending
  queue in `piRadio`, with the results arriving as ordinary state updates.
  Nothing above it should know that memory reads are asynchronous.
* *`readallvalues`.* A bulk dump at startup with no request or
  acknowledgement. Ugly, but containable: parse it in the transport and write
  the results into `RadioState` like any other report. The view sees a state
  that fills in, not a protocol quirk.

**One change notification, not one per field.** `RadioState.changed()` says
something changed without saying what, and the view recomputes. Per-field
observers look tidier and are a trap here: almost everything on screen is
derived, so `role_frequency("tx")` depends on eight separate values and a
view registered for "mode" would not know to redraw when split changed. The
alternatives are a dependency graph or every consumer registering for
everything, and the first person to add a derived value forgets one.

Recomputing cannot be out of step. The cost is handled by coalescing rather
than by making the notification cleverer: pass `RadioState` a `schedule`
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

It is necessary because the alternative is a readout that sits still for
several hundred milliseconds after the wheel stops. It has to write the
label DIRECTLY rather than asking for a redraw: during a borrow the
notifications are suspended, so a redraw would not happen, and lifting the
suspension would bring the flicker back.

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
* `cs_UX_SPLIT_Toggle` does not -- the code that worked against the real rig
  flipped its own flag and never read `value` at all

Getting this backwards gives a control that works until a report is missed,
after which it is inverted forever. The safest check is what the old
`mainScreen` handler did with the value: if it ignored it, the report is
news.

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

**Displayed is not stored.** `role_frequency()` subtracts the CW sidetone for
display; `role_to_vfo_hz()` adds it back before writing. A caller that takes
the displayed number, adds a step, and writes the result loses the offset --
a 1 kHz step moved 400 Hz while the tone was 600. Anything sending a
frequency the operator saw must convert.

---

<a name="what-moves-where"></a>
### What moves where

| Existing | Becomes |
| :--- | :--- |
| `delegate_command_processing` | Unchanged, in the rig transport |
| The 40-odd `xx_UX_` handlers | Same logic, writing `RadioState` instead of widgets |
| The `_CB` methods | Nearly unchanged — they already only send |
| `theVFO` | Retired. `RolePanel` takes the view half, `RadioState` the model half |
| `theVFO.primary_vfo_*_CB` | A `<Button-1>` per digit label — a mouse can hit the digit |
| `theVFO` tuning presets | Subsumed: choosing a digit *is* choosing the step |
| `comportManager` | Unchanged. Serial and network are already abstracted |
| `ConfigurationManager` | Unchanged. Boilerplate, but explicit and working |
| `SDRPlusPlusController` | Becomes one backend behind a common interface |
| `sdrDashboard` popup | Folds into the RX and Channels tabs |
| `Classic_uBITX_Control` | Left alone — see below |

**The child windows keep working unmodified.** They build their own
`tk.Toplevel`, and an sCTk root is a Tk window. What has to change is the
twenty-one attributes they currently reach into the main screen for: the
benign ones (`theRadio`, `after`, `master`, `delegate_command_processing`)
stay, and the widget references (`mode_Button`, `tone_value_Label`,
`key_speed_value_Label`, `delay_*_Label`, `primary_Mode_VAR`,
`theVFO_Object`) become reads from `RadioState`. That is fewer lines than
they have now, and it removes the coupling that makes the main screen hard to
change.

---

<a name="to-settle"></a>
### Things to settle first

**Which VFO reports are authoritative.** The rig sends `vc`/`cc` for the
currently displayed VFO and its mode, *and* `va`/`ca`, `vb`/`cb` for A and B
specifically, *and* `cv` to set which is active. Three sources for two
values. `RadioState` should take A and B from `va`/`vb`, the active VFO from
`cv`, and treat `vc`/`cc` as confirmation -- but that needs checking against
the firmware: if `va`/`vb` only arrive at startup, the standby readout would
go stale.

**Whether the rounding fix belongs in `piRadio`.** Setting the finest tuning
preset around every frequency write, and restoring it, would let
`channels.py` drop `savePresetState` / `restorePresetState` entirely. Its own
comment says why they exist: *"Channels could have been created using any
frequency. Need to use the smallest preset to avoid frequency being
truncated."* One place, every caller.

**A common backend interface.** `SDRPlusPlusController` already has roughly
the right shape -- `set_frequency_hz`, `set_mode`, `set_filter_width_hz`,
`widen`, `narrow`, `mute`, scan and channel methods. Formalising it lets each
backend declare what it supports, so the interface can grey what a backend
cannot do rather than pretending. See the capability table in `TODO.md`.

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
tell it is lying. Either leave the meter empty until a backend can fill it,
or say on screen that it is unavailable.

---

<a name="stub"></a>
### Testing without a rig

`stub_radio.py` stands in for `piRadio`. It accepts the same commands and
confirms them a moment later, so a control wired against it is wired
correctly for the real thing -- the only difference is that the confirmation
comes from a timer rather than a serial port.

**Wiring a mockup straight to its state object would be quicker and would
teach the wrong habit.** A control that sets `state.split = True` looks fine
until the rig refuses the command, and then the interface is showing
something the radio is not doing.

The 40 ms delay is deliberate. Answering instantly would hide any place the
interface assumes its command has already taken effect, and those are exactly
the bugs that appear when a real rig turns out to be slower than expected.

The test that matters: **no view code writes to the state.** Grep for it. The
only exception should be seeding initial values before a transport exists.

---

<a name="order"></a>
### Suggested order

The point of this order is that something runs at every step, and the risky
part -- the protocol -- is never in question.

1. `RadioState`, with the model tests it already has.
2. The rig transport: `piRadio` plus `delegate_command_processing` and the
   `xx_UX_` handlers, writing state, with no view at all. Verified by
   printing the state as the rig reports.
3. The view from `ubitx_mockup.py`, reading state, with commands wired to
   the existing `_CB` bodies.
4. The child windows, one at a time, swapping widget reads for state reads.
5. The SDR backend behind whatever common interface step 3 revealed it needs.

Steps 1 and 2 together are the whole risk. If the rig drives a state object
correctly with no interface attached, everything after it is presentation.
