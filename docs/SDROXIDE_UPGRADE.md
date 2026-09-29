# SDRoxide: what to switch in the app when a fix is released

The app works around three things SDRoxide's rigctl (Hamlib) server does today, SDRoxide can't yet send its decoded CW anywhere, and its RF gain can't be reached over rigctl. Pull requests add these upstream (see `SDROXIDE_PR_INSTRUCTIONS.md`). Each has its own switch in the app, so you can turn them on one at a time, whichever order they're released in.

All the switches are in **SDRoxide's entry** in `sdr_programs.json`:

```json
"sdroxide": {
    ...
    "settle_seconds": 3.0,
    "width_needs_mode_change": true,
    "rigctl_agc": true,
    "rigctl_nr_strength": true,
    "rigctl_rf_gain": true,
    "decoder_udp_port": null,
    ...
}
```

It's best to put your changes in `~/.ubitx_cec_desktop/sdr_programs.json` rather than the copy beside the code. That file is merged over the shipped one setting by setting, and survives an update of the app. It needs only the settings you change, for example:

```json
{
    "sdroxide": {
        "width_needs_mode_change": false,
        "settle_seconds": 1.5
    }
}
```

This needs the app files from 2026-09-29 or later. Before that, the file was merged a whole program at a time, and a partial `"sdroxide"` entry was ignored, with a console line saying it "does not say which protocol drives it".

First, find out which SDRoxide you're running: **Help ▸ About** in SDRoxide, or its window title. Check the release notes at github.com/dividebysandwich/sdroxide/releases for "rigctl".

---

## Fix 1: the filter width in the same mode (PR 1)

**Today:** `M USB 2400` while in USB is ignored. The app gets around it by switching briefly to the other sideband (or, from CW, to LSB) and back (`width_needs_mode_change: true`). You may hear a short blip, and filter changes take a second or two.

**Is it fixed?** With SDRoxide in USB at 2700 and the app closed:

```bash
printf 'M USB 2400\n' | nc -w 1 127.0.0.1 4532; sleep 2; printf 'm\n' | nc -w 1 127.0.0.1 4532
```

It's fixed if it reads `USB` / `2400`. Afterwards, set it back: `printf 'M USB 2700\n' | nc -w 1 127.0.0.1 4532`.

**Then switch:**

```json
"width_needs_mode_change": false,
"settle_seconds": 1.5,
```

`settle_seconds` was raised to 3 only because the mode switch-and-back takes long. With the fix, 1.5 should do. If the filter or frequency ever "bounces back", raise it again.

**Check in the app:** filter buttons in USB, LSB and CW take effect with no blip, and the rig never changes mode.

---

## Fix 2: squelch, AGC and NR strength (PR 2)

**Today:** SDRoxide answers `RPRT -11` to squelch, AGC and NR level, so the SQL and AGC lamps are greyed and NR is an on/off switch only. Also, turning NR on from the app always gives SDRoxide's plain spectral NR at medium, whatever engine you'd picked.

**Is it fixed?**

```bash
printf 'l SQL\nl AGC\nl NR\n' | nc -w 1 127.0.0.1 4532
```

It's fixed if you get three numbers (for example `0.000000`, `5`, `0.666667`) instead of `RPRT -11`.

**Then switch:** nothing. The app already has the code, and it looks for all three every time it connects:

- **SQL lamp:** squelch with its threshold knob and A/R, like rigctld. The scale is 0 (open) to 1 (closed).
- **AGC lamp:** switches AGC off and back on at its speed. Its pop-up has a Fast/Medium/Slow knob.
- **NR lamp's pop-up:** a Low/Med/High strength knob. The engine (RNN, DFNR, SPEC, NR2, NR) is still chosen in SDRoxide's NR panel.

**To turn any one of them off** (if it misbehaves):

| To turn off | Put in SDRoxide's entry |
| :--- | :--- |
| AGC lamp and knob | `"rigctl_agc": false` |
| NR strength knob | `"rigctl_nr_strength": false` |
| Squelch | `"known_missing": ["squelch"]` |

**Check in the app:**
1. Click each lamp, and check SDRoxide's own control follows.
2. Change each one in SDRoxide, and check the lamp or knob follows.
3. With the notch, NR and AGC on in LSB, press a filter button. Nothing should change except the width.

The last check matters because SDRoxide keeps these settings per mode, and until Fix 1 is released the app's switch-and-back could disturb them. The app saves and restores them around that, and this confirms it works.

---

## Fix 3: decoded CW for the DEC strip (PR 3)

**Today:** SDRoxide's CW decoder shows its copy only in its own CW panel, so the DEC lamp is greyed for SDRoxide.

**Is it in your SDRoxide?** Look in Settings ▸ Servers for a section called **Decoded CW over UDP**. If it's there, tick **Enable**, leave it at `127.0.0.1` and port `9999`, and click **APPLY**. Then, with the app closed, SDRoxide in CW and a CW signal tuned in:

```bash
nc -ul 9999
```

It works if the copy appears as SDRoxide decodes it. Only the CW panel's copy is sent, not the skimmer's labels on the waterfall, so the panel must be on the signal. Stop `nc` (Ctrl-C) before starting the app, because only one program can listen on the port.

**No CW on the air?** `make_cw_iq.py` writes a practice recording: a keyed signal at 7.030 MHz in noise, which SDRoxide plays over and over. Run `python3 make_cw_iq.py` (it needs numpy), then `sdroxide --file cw_practice.iq --rate 250000 --freq 7025000`, and put the rig on 7.030.00 CW. `--wpm`, `--text` and `--snr` change it.

**Then switch:** in SDRoxide's entry, `"decoder_udp_port": 9999` (it's `null` until then).

**Check in the app:**
1. In CW, the DEC lamp is available. Press it: the strip appears at the bottom and fills with the copy, and the console says `[sdr] listening for SDRoxide's decoded CW on 127.0.0.1:9999`.
2. While DEC is on, the filter narrows to 250 Hz, and AGC switches off if Fix 2 is in. Pressing DEC off puts them back.
3. Leaving CW turns DEC off.

If the console says it cannot listen because the port is in use, something else holds 9999 (an `nc` left running, or SDRangel's decoder listener). Close it, or pick another port in both SDRoxide and the entry.

**With PR 4 released too,** untick Settings ▸ UI ▸ **Control strip** and **CW panel** in SDRoxide. SDRoxide then shows just its waterfall, with the frequency, mode and filter in our app and the copy in our DEC strip. A **STRIP** chip in SDRoxide's top-right corner brings the strip back. Nothing changes in our app for this. They're settings in SDRoxide only. Also set Settings ▸ UI ▸ **Layout** to **Desktop** (not Auto): below 600 wide or 440 tall, Auto switches to SDRoxide's phone layout, which drops the spectrum trace and leaves only the waterfall. With the strip hidden, the window can now get that small.

Unlike SDRangel's, SDRoxide's decoder isn't switched on and off by DEC. It runs whenever SDRoxide is in CW, and DEC only decides whether the app listens.

---

## Fix 5: the RF gain (PR 5)

**Today:** SDRoxide answers `RPRT -11` to `l RF`, so the app's RF GAIN knob is greyed with "not available with SDRoxide". The gain can only be set with SDRoxide's own **Gain** slider.

**Is it fixed?**

```bash
printf 'l RF\n' | nc -w 1 127.0.0.1 4532
```

It's fixed if you get a number from 0 to 1 that follows SDRoxide's Gain slider (half way along is about `0.5`) instead of `RPRT -11`.

**Then switch:** nothing. The app already has the code (`"rigctl_rf_gain": true`) and looks for the level every time it connects.

**Check in the app:**
1. The RF GAIN knob is live, and reads 0–100 %. It's a share of the dongle's gain range, not dB: rigctl doesn't say what the stage counts in. Each click is 2 %.
2. Turn the knob, and SDRoxide's Gain slider follows. Move the slider, and the knob follows.

To turn it off if it misbehaves: `"rigctl_rf_gain": false` in SDRoxide's entry.

---

## If something goes wrong

Start the app with its rigctl trace, and keep the lines around the problem:

```bash
UBITX_SDR_TRACE=1 python3 ubitx_cec_desktop.py
```

`[sdr] -> …` is every command sent to SDRoxide, and `[sdr] <- changed in the SDR: …` is anything the app took as a change made in SDRoxide. `[sdr] SDRoxide not back from a filter change` means the switch-and-back was slow, which can only happen while `width_needs_mode_change` is `true`.

To go back to how it was, put the switches back to the values at the top of this page.

## Already done and tested at the station (2026-09-28)

- Tuning both ways, USB/LSB/CW, volume, mute and the S-meter in dBm.
- NB, NR and Notch lamps (on/off).
- The filter switch-and-back, including keeping the notch.

On 2026-09-29, with local builds of the PRs:
- the DEC strip with PR 3: the strip showed exactly what SDRoxide's CW panel copied;
- the RF GAIN knob with PR 5: `l RF` and `L RF` answered correctly, and the knob worked in the app;
- PR 4's hidden strip and CW panel, with the window shrinking once the strip is hidden (set Layout to Desktop to keep the spectrum trace).

Not yet seen at the station:
- the two-step switch-and-back (the fix for CWL ending in LSB);
- the AGC and NR-strength knobs in the app (PR 2's levels answered correctly with `nc`).
