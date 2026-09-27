# Adding an SDR

How to teach the application a new SDR program, a new SDRangel demodulator or
device, or a new way of talking to an SDR — and which of those needs code.

Most of it is data. What a program IS lives in `sdr_programs.json`; what its
CONTROLS are lives in `sdr_controls.json`. Code is needed only for a program
that speaks a protocol the application does not know yet.

---

## Contents

* [Which of these do you need?](#which)
* [The six listening aids, and the capability names](#vocabulary)
* [1. A program that speaks rigctl](#rigctl)
* [2. An SDRangel demodulator or device](#sdrangel)
* [3. A program with a protocol of its own](#protocol)
* [Where to put your own entries](#where)
* [Checking it](#checking)

---

<a name="which"></a>
## Which of these do you need?

| You want to add | Edit | Code? |
| :--- | :--- | :--- |
| A program with a rigctl (Hamlib) server — like Gqrx, SDR++ or rigctld | `sdr_programs.json` | No |
| Another demodulator inside SDRangel, or another ranges/labels for one | `sdr_controls.json` | Usually no |
| RF gain for another SDRangel device (Airspy, SDRplay, HackRF...) | `sdr_controls.json` | No |
| A program with its own API — like SDRangel's REST | a new transport class | Yes |

<a name="vocabulary"></a>
## The six listening aids, and the capability names

The window knows seven listening aids by name — one lamp each on the Operate
tab — and nothing about any SDR. An SDR offers whichever of them it has:

| Lamp | Function name | Capability (switched) |
| :--- | :--- | :--- |
| AGC | `agc` | `agc` |
| NR | `nr` | `nr` |
| Notch | `notch` | `notch` |
| SQL | `squelch` | `squelch_switch` — or `squelch`, a threshold with no switch (Gqrx) |
| NB | `nb` | `nb` |
| CW | `cw` | `cw_peak` |
| DEC | `decode` | `decoder` — a CW decoder whose text reaches the application (SDRangel's Morse Decoder, over UDP). Handled by `SDR_Link` itself, not described in `sdr_controls.json`. |

The other capability names, for everything else an SDR can do:
`frequency`, `mode`, `filter`, `signal` (a signal reading, for the S-meter),
`volume`, `mute`, `rf_gain`, `bandwidth` (the sampled band's width). The full
list is `CAPABILITIES` in `sdr_programs.py`; a name not on it is refused.

A function outside the seven has no lamp and is not shown. Adding an eighth is
a change to the window (`AIDS_LAMPS`) and to `SDR_Link.DSP_CAPABILITY`.

<a name="rigctl"></a>
## 1. A program that speaks rigctl

One entry in `sdr_programs.json`, keyed by a short name of your choosing —
the name the Setup tab's setting stores. This is Gqrx's, as shipped:

```json
"gqrx": {
    "name": "Gqrx",
    "app_name": "Gqrx",
    "launch_as_application": true,
    "never_force_quit": true,
    "protocol": "rigctl",
    "port": 7356,
    "modes": {"LSB": "LSB", "USB": "USB", "CWL": "CWL", "CWU": "CWU"},
    "ambiguous_modes": {"CW": "cw"},
    "start": "U DSP 1",
    "stop": "U DSP 0",
    "self_describing": true,
    "known_present": ["filter"],
    "volume_range": [-80.0, 50.0],
    "squelch_range": [-150.0, 0.0],
    "squelch_unit": "dBFS",
    "process_names": ["gqrx", "gqrx.exe"],
    "paths": {
        "darwin": ["/Applications/Gqrx.app/Contents/MacOS/gqrx"],
        "win32": ["C:\\Program Files\\gqrx\\gqrx.exe"],
        "linux": ["gqrx"]
    }
}
```

### The fields

**Required:**

| Field | What it is |
| :--- | :--- |
| `name` | Shown on screen. |
| `protocol` | Which transport drives it: `"rigctl"` or `"rest"`. It NAMES the transport; it does not describe it. |
| `port` | Its usual port, offered on the Setup tab. |
| `modes` | The program's name for each of the rig's four modes, `LSB`, `USB`, `CWL`, `CWU` — all four. Two may share a name (SDR++ has one `CW`). |

**What it can do** — the transport asks the program itself at connect, so
these are only for what it cannot find out, or gets wrong:

| Field | What it is |
| :--- | :--- |
| `self_describing` | `true` if it answers rigctl's `l ?` and `L ?` with what it can read and set (Gqrx, rigctld). Otherwise each level is tried. |
| `known_missing` | Capabilities it is known NOT to have, so they are not tried — some servers answer wrongly rather than refusing. |
| `known_present` | Capabilities it has but cannot be seen to have — Gqrx's filter width. |
| `ambiguous_modes` | A mode of its own that could be either of the rig's, and what it means: `{"CW": "cw"}` is a CW with no sideband, and the rig's current CW side is kept. |
| `start`, `stop` | The rigctl commands that start and stop its receiver, if it has any. |
| `volume_range` | Its audio level's range in its own units, spread over the volume knob's 0–100 (Gqrx: −80 to +50 dB). Without it, 0 to 100 is assumed. A program with no audio level of its own gets the computer's volume instead. |
| `squelch_range`, `squelch_unit` | Its squelch threshold's range and unit. Fully open is its "off"; the SQL pop-up shows one knob in these units, with A (just above what is heard now — needs a `signal` reading in dBFS) and R (fully open). A range narrower than 10 is divided into hundredths on the knob. |

**Starting and closing it** — optional; without them it is attached to when
running and never started:

| Field | What it is |
| :--- | :--- |
| `process_names` | What its process is called, to see whether it is running. |
| `paths` | Where it is installed, per platform: `darwin`, `win32`, `linux`. The first found is used. Overridden by Setup's "Where the program is". |
| `arguments` | Command-line arguments to start it with, per platform. |
| `app_name` | What the operating system calls the application, for asking it to quit politely. |
| `launch_as_application` | macOS: start it as an application (`open -a`), so it can be asked to quit. |
| `never_force_quit` | Never kill it — for a program that damages its own settings when not shut down its own way (Gqrx). |
| `needs_command_line` | It cannot be started from a guess; the operator gives the whole command (rigctld). |

A malformed entry is refused with its name and the reason in the console, and
the rest of the file still loads.

<a name="sdrangel"></a>
## 2. An SDRangel demodulator or device

`sdr_controls.json` describes, per SDRangel channel type, which listening
aids a demodulator has and what their knobs are; and per device type, its RF
gain. It is read by `sdr_controls.py` and used by `rest_sdr.py`. The window
builds its pop-ups from whatever is here.

### Finding the field names

SDRangel's REST field names are not documented in a way worth trusting; find
them by capture, as everything in `SDRANGEL_REST_NOTES.md` was:

```bash
S=http://127.0.0.1:8091/sdrangel
curl -s $S/deviceset/0/channel/1/settings | python3 -m json.tool > before.json
# change ONE thing in SDRangel's own window
curl -s $S/deviceset/0/channel/1/settings | python3 -m json.tool > after.json
diff before.json after.json
```

Then send it back and read it again — **a PATCH can be accepted and not
applied**, so a field only belongs in the file once it has been seen to
work:

```bash
curl -s -X PATCH -H "Content-Type: application/json" \
  -d '{"channelType":"WDSPRx","direction":0,"WDSPRxSettings":{"agcMode":3}}' \
  $S/deviceset/0/channel/1/settings >/dev/null
curl -s $S/deviceset/0/channel/1/settings | python3 -m json.tool | grep agcMode
```

Dial ranges are what SDRangel's own dialog allows; its `.ui` files in the
SDRangel source give them exactly.

### A channel's functions

Under `"sdrangel" → "channels" → <channelType>`, one block per listening
aid. This is the WDSP receiver's AGC, as shipped:

```json
"WDSPRx": {
    "agc": {
        "switch": "agc",
        "capability": "agc",
        "settings": {
            "mode":  {"field": "agcMode", "caption": "Mode", "low": 0, "high": 3,
                      "kind": "choice",
                      "labels": ["Long", "Slow", "Medium", "Fast"],
                      "short": ["L", "S", "M", "F"]},
            "top":   {"field": "agcGain", "caption": "Top", "low": -20, "high": 120,
                      "kind": "range", "unit": "dB"},
            "slope": {"field": "agcSlope", "caption": "Slope", "low": 0, "high": 20,
                      "kind": "range", "unit": "dB", "convert": "tenths"},
            "hang":  {"field": "agcHangThreshold", "caption": "Hang", "low": 0,
                      "high": 100, "kind": "range"}
        }
    }
}
```

**A function:**

| Field | What it is |
| :--- | :--- |
| `switch` | The field that turns it on and off (0/1). A function is offered only where the channel's settings have this field. |
| `capability` | Which capability it gives — see the table above. |
| `settings` | Its knobs, in the order shown. May be empty — the WDSP notch is a switch only. |
| `knobs` | *Optional.* Which settings to show, when that depends on another setting — see below. |

**A setting (a knob):**

| Field | What it is |
| :--- | :--- |
| `field` | SDRangel's name for it. |
| `caption` | Above the knob. Keep it short — four or five letters. |
| `low`, `high` | Its range, in **dial units**: the whole number the operator reads, or a choice's position. |
| `kind` | `range` — end stops, its ends labelled; `choice` — one position per label; `step` — a flywheel, for a value stored as something other than what is read (a power of two). |
| `unit` | Shown after the value: `"dB"`, `"Hz"`, `"%"`. |
| `labels`, `short` | A choice's names in full (shown beneath) and round the dial (short, or they collide). |
| `convert` | How a dial position is stored, where it is not simply the number: `int` (the default), `float`, `tenths` (dial 10 stored as 100), `alpha_db` (the SSB demodulator's NR alpha, 1 − 10^(−n/10)). |
| `text` | A value shown its own way: `power_of_two_ms` (dial 7 shows "128 ms"). |
| `read_only` | Shown but not turnable — for a field SDRangel accepts and does not apply. |
| `default` | *Optional.* Its value when SDRangel is reset (its `resetToDefaults()` in the source), in dial units. A pop-up with any shows a **Defaults** button that puts them all back in one go, leaving the switch as it is. It may fall between whole steps (WDSP's slope, 3.5): it is stored exactly, though the knob shows the nearest step. |

**Choosing knobs by another setting.** The SSB demodulator's NR has three
methods, each with its own number; the middle knob is whichever the method
uses:

```json
"knobs": ["scheme", {"by": "scheme", "choose": ["avg", "sigma", "peaks"]}, "alpha"]
```

**A conversion or text that is not there yet** is a few lines of Python,
added once to `CONVERSIONS` or `TEXTS` in `sdr_controls.py` and then used by
name. That is deliberate: the file stays data.

### A device's RF gain

Under `"sdrangel" → "devices" → <deviceHwType>`:

```json
"RTLSDR": {
    "rf_gain": {
        "field": "gain",
        "per_db": 10,
        "auto": "agc",
        "steps": [0, 9, 14, 27, 37, 77, 87, 125, ...]
    }
}
```

`field` is in the device's settings block; `per_db` how many of its units
make a dB (the RTL-SDR stores tenths); `auto` the field of the hardware's own
AGC, if it has one (the knob is greyed while it is on); `steps` the gains the
hardware takes, in its own units — a knob move goes to the next step that way.

### What still lives in `rest_sdr.py`

A new demodulator is usually data only, but check these, near the top of
`rest_sdr.py`:

| Constant | Why it may need your channel |
| :--- | :--- |
| `DEMODULATOR_PREFERENCE` | Which demodulator is driven when a device set has several. A type not listed is used only when nothing listed is present. |
| `METER_CHANNEL` | The channel read for the S-meter (`ChannelPower`). |
| `REPORT_UNSAFE` | Channel types whose report must never be read — the WDSP receiver's crashes SDRangel. |
| `STALE_PASSBAND_CHANNELS` | Channel types whose passband is write-only over REST. |

Mode and filter need the channel to have SDRangel's usual passband fields —
`rfBandwidth`, `lowCutoff`, `spanLog2`. The automatic CW behaviour
(`_automate_mode`) is the WDSP receiver's only.

<a name="protocol"></a>
## 3. A program with a protocol of its own

A new transport class, beside `RigctlSDR` (`rigctl_sdr.py`) and `RestSDR`
(`rest_sdr.py`), chosen by the `protocol` its entry names. Register it in one
place, `SDR_Link._transport_for()` in `sdr_link.py`; nothing above the link
changes.

What `SDR_Link` asks of a transport:

**Always**

* `is_connected`, `capabilities` (a frozenset of capability names)
* `connect(host, port)`, `disconnect()`, `start()`, `stop()`, `discover()`
* `set_frequency(hz)`, `set_mode(sdr_mode, width)`, `set_filter_width(hz)`,
  `default_filter_width(sdr_mode)`
* `frequency`, `mode`, `filter_width`
* the callbacks it calls when the program changes by itself: `on_frequency`,
  `on_mode`, `on_filter`, `on_volume`, `on_mute`, `on_squelch`, `on_signal`,
  `on_dsp`, `on_rf_gain`, `on_disconnect`

**For the capabilities it offers**

* `signal`: a `signal` attribute in dBFS; `get_level("STRENGTH")`
* `volume`: `volume`, and `set_level("AF", value)`
* `mute`: `muted`, `set_mute(on)`
* `squelch` (threshold): `squelch`, `set_level("SQL", value)`
* switched functions: `dsp_on` and `dsp_settings` dicts; `set_dsp(function,
  on)`, `dsp_knob_names`, `dsp_info`, `dsp_range`, `dsp_adjustable`,
  `dsp_setting_text`, `set_dsp_setting`
* `rf_gain`: `rf_gain`, `rf_gain_auto`, `rf_gain_range()`, `rf_gain_steps()`,
  `snap_rf_gain(db)`, `set_rf_gain(db)`
* `bandwidth`: `bandwidth`, `bandwidth_choices()`, `set_bandwidth(hz)`, and
  `set_frequency(hz, band=(start, end))`

**Rules that already bit this code, and will again:** record what you set at
once, so the next poll does not report your own change back; poll on the Tk
timer, never in a loop; keep every request short, because it blocks the
interface; never open a window from a transport — ask upward through a
callback; and a program still starting answers badly about itself, so
`discover()` is called again three seconds after connecting.

<a name="where"></a>
## Where to put your own entries

Not in the files beside the code — those are replaced when the application is
updated. Put them in the application's folder:

```
~/.ubitx_cec_desktop/sdr_programs.json
~/.ubitx_cec_desktop/sdr_controls.json
```

Same shape as the shipped files, holding only what you add or change. They
are merged over the shipped ones — `sdr_programs.json` entry by entry,
`sdr_controls.json` function by function — so an entry of yours replaces that
one entry, and everything added to the shipped files later still reaches you.

For example, to widen the WDSP receiver's AGC top range and nothing else:

```json
{
    "sdrangel": {
        "channels": {
            "WDSPRx": {
                "agc": { ...the whole agc block, with your change... }
            }
        }
    }
}
```

A function is replaced whole, so copy its complete block from the shipped
file and change what you need.

<a name="checking"></a>
## Checking it

* **Start the application from a terminal.** A refused entry is named in the
  console with the reason, and connecting says what the SDR can do: `[sdr]
  connected to Gqrx at 127.0.0.1:7356; it can do: filter, frequency, ...`.
* **Open each lamp's pop-up.** Captions, ranges and values should match
  SDRangel's or the program's own dialog. A greyed lamp's pop-up says why.
* **Turn each knob, then look in the SDR's own window** — and for SDRangel,
  read the setting back with `curl` as above. A change the SDR accepted and
  did not apply looks exactly like one that worked until you check.
* **Change it in the SDR itself** and see the knob follow.
