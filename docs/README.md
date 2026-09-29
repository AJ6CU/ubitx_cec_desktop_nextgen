## uBITX CEC Desktop

A desktop interface for uBITX radios running KD8CEC firmware, with an SDR
program alongside it showing the band as a waterfall. The rig and the SDR are
kept in step both ways: tune the rig and the SDR follows; click a signal in
the SDR's waterfall and the rig tunes to it.

By Mark Hatch, AJ6CU. GPL v3.

### Running it

```bash
python3 ubitx_cec_desktop.py
```

It needs `customtkinter`, `scustomtkinter` (the themed widget library it is
built on) and `pyserial`. A widget whose theme block is missing fails
loudly when it is built, and the error names it.

On the first start there is no rig port yet, so the application opens on the
**Setup** tab: choose the rig's serial port there, or give a network rig as
`socket://host:port`. Every control still works without a radio — it just
has nothing to talk to.

### What is on screen

* **Operate** — the two frequencies, with receive always on the left and
  transmit always on the right, so nothing moves when split is turned on.
  Click a digit to choose the tuning step, then turn the dial. Under the
  frequencies are RIT, Lock and TX off. Below them are the meters, then the
  controls you reach for while operating:
  * the listening-aid lamps (AGC, NR, Notch, SQL, NB, CW, DEC). Click a lamp
    to switch its function; the ▾ beside it opens that function's controls,
    in the SDR's own terms. A pop-up can be pinned so it stays open. DEC
    decodes CW (with SDRangel's Morse Decoder) into a strip along the bottom
    of the tab, setting the filter, AGC and CW peak for decoding while it is
    on and putting them back after.
  * the filter;
  * band, mode, and the SDR's bandwidth (how much of the band its waterfall
    shows);
  * RF gain and volume (double-click the volume knob to mute);
  * split, the transmit offsets, and Log QSO.
* **RX** — which receiver you are listening through, the rig or the SDR, and
  the rig's own receive settings.
* **Channels** — the rig's memories and your own channel sets, with
  scanning.
* **CW** — keyer settings.
* **Setup** — the rig's port, the SDR program, the logbook, and the SDR's
  finer settings.

A control the rig or the SDR cannot serve is greyed rather than hidden, and
where it matters the reason is shown beside it.

### The SDR programs it drives

| Program | How | What to set up in it |
| :--- | :--- | :--- |
| SDRangel | its REST API, port 8091 | A device set with a WDSP Receiver (preferred) or an SSB Demodulator — not both, if you want DEC: SDRangel's Morse Decoder listens to the first channel. Add a Channel Power channel for the S-meter, and the Morse Decoder feature for DEC. |
| Gqrx | rigctl, port 7356 | Turn on remote control. |
| SDR++ | rigctl, port 4532 | Turn on the rigctl server module. |
| rigctld (Hamlib) | rigctl, port 4532 | Give the whole command line under Setup's SDR settings. |
| SDRoxide (trial) | rigctl, port 4532 | Turn on its Hamlib (rigctl) server, in Settings ▸ Servers. NB, NR and Notch lamps switch; squelch, AGC, NR strength, RF gain and DEC arrive with SDRoxide's pending fixes — see `SDROXIDE_UPGRADE.md`. |

Choose the program on the Setup tab. The application can start it for you,
and closes only a program it started itself; one you started is yours and
is left running.

What each program is — its port, where it is installed, what it calls its
modes, what it cannot do — is in `sdr_programs.json`. What its controls are
— the knobs behind each lamp, their ranges, labels and units — is in
`sdr_controls.json`. Both are data, not code: adding a program or a
demodulator is an entry in a file, plus new code only if the program speaks
a protocol not yet supported — `ADDING_AN_SDR.md` says how. SDRangel bugs that the application works
around, and how to check whether a newer SDRangel has fixed them, are listed
in `TODO.md` under "Waiting on SDRangel".

### Keeping SDRangel's CPU down

On the station (an RTL-SDR dongle at 1024 kS/s, macOS), SDRangel runs at
about 50 % CPU. The Bandwidth slider barely changes that: the dongle samples
at its full rate whatever the decimation, and decimation only thins what is
passed on. DEC adds up to about 10 %.

Most of the load is likely SDRangel drawing its spectrum and waterfall.
These have not been measured one by one, but they are the settings to try,
all in SDRangel:

* **A lower spectrum refresh rate** (the FPS setting on the spectrum) —
  usually the biggest saving, and a waterfall at 10–15 frames a second still
  reads well.
* **A smaller FFT size** on the spectrum — less work per frame, coarser
  detail.
* **A lower sample rate on the device itself** — the only one that cuts the
  processing underneath, but it also lowers the widest bandwidth the slider
  offers.
* **Only the spectra you look at** — the device's main spectrum and the WDSP
  receiver's own each cost drawing time.

### Where it keeps its files

Everything the application saves is in one folder in your home directory,
the same on macOS, Linux and Windows:

```
~/.ubitx_cec_desktop/
```

| File | What it holds |
| :--- | :--- |
| `settings.json` | The settings — rig port, SDR program and address, filter defaults, logbook, and the rest |
| `channels.json` | Your channel sets, and how long a scan stays on each channel |
| `geometry.json` | The window's size and position |
| `pinned_aids.json` | Which listening-aid pop-ups were left pinned, and where |
| `sdr_programs.json` | *Optional.* Your own SDR program entries, merged over the shipped `sdr_programs.json` |
| `sdr_controls.json` | *Optional.* Your own ranges and labels for the SDR's controls, merged over the shipped `sdr_controls.json` |

The folder is hidden (its name starts with a dot). To see it in Finder,
press Cmd-Shift-. in your home folder; on Linux, `ls -a ~`. To back up the
station or move it to another machine, copy the whole folder. To start
afresh, quit the application and delete it.

The `sdr_programs.json` and `sdr_controls.json` beside the code are replaced
when the application is updated, so put your own changes in the copies in
the folder, not in those.

### The code

| File | What it is |
| :--- | :--- |
| `ubitx_cec_desktop.py` | The window. Reads the model, sends commands, and knows no SDR by name. |
| `radio_model.py` | The model: what the rig last reported, in one form. |
| `ubitx_link.py` | The rig's protocol — the one the Nextion display used. |
| `serial_ports.py` | Finding and opening the rig's port, serial or network. |
| `sdr_link.py` | Keeps the SDR in step with the rig, and describes every SDR's functions the same way for the window. |
| `rigctl_sdr.py`, `rigctl_client.py` | Driving SDR++, Gqrx, SDRoxide and rigctld over rigctl. |
| `rest_sdr.py` | Driving SDRangel over its REST API. |
| `sdr_programs.py` + `.json` | What each SDR program is. |
| `sdr_controls.py` + `.json` | What each SDR program's controls are. |
| `sdr_launcher.py` | Starting and closing SDR programs. |
| `system_audio.py` | The computer's volume, for an SDR with no level of its own. |
| `scanner.py` | Scanning a channel set, by tuning the rig. |
| `channel_sets.py` | Your channel sets. |
| `configuration.py` | The settings. |
| `app_paths.py` | Where the application's files live. |
| `ARCHITECTURE.md` | The layering, the rules, and why things are the way they are. Read first. |
| `ADDING_AN_SDR.md` | How to add an SDR program, an SDRangel demodulator or device, or a new protocol — and the fields of `sdr_programs.json` and `sdr_controls.json`. |
| `TODO.md` | Outstanding work and what to check at the station. |
| `SDROXIDE_UPGRADE.md` | SDRoxide's workarounds, the switch for each, and what to change as its rigctl fixes are released. |
| `SDRANGEL_REST_NOTES.md` | What was found out about SDRangel's REST API, with the captures. |

### The one rule

**No view code writes to the model.** A control sends a command; the rig
confirms; the confirmation updates the model; the model asks for one redraw.
Grep for `self.model.<something> =` outside the transports — the only hits
should be seeding values at startup.

That is what makes the display trustworthy: it always shows what the rig
reported, never what a control asked for. It is the rule worth checking as
the code grows.

### Where it stands

The rig side and the SDR side both work day to day. Still to come, among
other things: the rig's own S-meter, power and SWR readings; the CW and RX
tabs' rig settings; and a question about whether the rig reports VFOs A and
B continuously or only at startup. `TODO.md` has the full list, and
`ARCHITECTURE.md` the open questions.
