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

* **The rig connection dialog.** The serial port is hardcoded. `comportManager`
  handled serial or network, retries and saving the choice; it needs to come
  back, with its bugs fixed (see below).
* **The meters.** `cp_`, `al_` (S-meter) and `vm_` (power and SWR) are
  unwired, so both meters are empty. Wiring them also lets the scanner stop
  on a signal, which it cannot do today.
* **The CW tab** -- key type (`ck_`), speed (`vs_`), the two delays (`vy_`,
  `ve_`): each needs its report stored and a command to change it.
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
* **Launching SDR++ at startup** when autostart is set.
* **Tidying once the old application is retired:** the settings file's scan
  and channel entries, the SDR++ controller's dormant channel and scan
  methods, `globalvars`' Nextion leftovers, and the "simulate transmit"
  button, now that the rig reports transmit itself.

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
| Gqrx     | rigctl socket  | `l STRENGTH`           | via `M`      | no       | not yet known |
| SDRangel | REST           | expected               | expected     | expected | its own audio gain, expected |

The boundary is ready for this. Only `SDR_Link` talks to the controller, and
volume already goes through it, so SDR++ answers with the system volume and
another backend can answer with its own -- without the Operate tab changing.

---

<a name="the-application"></a>
### The application — bugs worth fixing in the current code

These affect what is running today, not just the rebuild.

**The SDR connection blocks the interface.** `SDRPlusPlusController` drives
rigctl from the Tk `after()` loop with blocking sockets. *Partly fixed:* the
socket now times out after one second instead of never, so an unresponsive
SDR drops the connection rather than freezing the application for good. A
one-second freeze on a stalled read is still possible.

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

**`comportManager.py` line 225 is missing its parentheses.**

```python
if port != gv.config.getRadioPort:      # a bound method, not a string
```

Every other call site writes `getRadioPort()`. This one compares a string to
a method object, so the condition is always true and `setRadioPort` runs on
every open. Harmless in effect, which is why it has survived, but the comment
beside it describes a check that is not happening.

**The bare `except:` in `openSelectedComPort`.** It has `# FileNotFoundError:`
left beside it, showing the intent was narrower. As written it swallows
everything -- a typo in the serial parameters, a permissions problem, a
keyboard interrupt -- and reports them all as "the port did not open". That
is why a connection failure gives the operator nothing to act on.

**`openSelectedComPort` does view work.** It disables option menus, calls
`pack_forget` on two frames and writes configuration, all inside a method
about opening a port. That coupling is why the file feels delicate: the
opening logic cannot be changed without thinking about the interface, and the
interface cannot be changed without reading the transport.

**IPv6 is accepted and then rejected.** `validateWiFiSocket` validates with
`ipaddress.ip_address`, which accepts IPv6 -- but the `split(":")` above it
requires exactly two parts, and an IPv6 address is full of colons. So the
check that would accept it can never be reached. Either reject IPv6
deliberately and say so, or parse the address properly.

---

<a name="much-later"></a>
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
