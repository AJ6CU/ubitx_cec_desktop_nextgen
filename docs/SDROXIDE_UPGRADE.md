# SDRoxide and SDRoxide Brown: what to switch in the app as fixes are released

Four fixes to SDRoxide's rigctl (Hamlib) server and decoded-CW output came from our pull requests. Each has its own switch in the program's entry in `sdr_programs.json`, so they can be turned on one at a time.

| Fix | SDRoxide (dividebysandwich) | SDRoxide Brown (madmedicnl) |
| :--- | :--- | :--- |
| 1. Filter width in the same mode | merged, in v1.6.11 | PR submitted 2026-11-04 |
| 2. Squelch, AGC and NR strength | merged, in v1.6.11 | PR submitted 2026-11-04 |
| 3. Decoded CW over UDP | merged, in v1.6.11 (port 9999) | PR submitted 2026-11-04 (port 9998) |
| 5. RF gain | merged, in v1.6.11 | PR submitted 2026-11-04 |
| 4. Hide the control strip and CW panel | not merged; to be rethought | not submitted |

**SDRoxide:** the shipped `"sdroxide"` entry was switched over on 2026-11-04, for v1.6.11 and later. Nothing more to do. Running an older SDRoxide, put the old values back in your own file (below).

**SDRoxide Brown:** the shipped `"sdroxide-brown"` entry still has the workarounds, for brown as released. Switch each one as brown releases the matching fix. The sections below say how to check first, and what to switch.

The two entries today:

```json
"sdroxide": {
    ...
    "settle_seconds": 1.5,
    "width_needs_mode_change": false,
    "rigctl_agc": true,
    "rigctl_nr_strength": true,
    "rigctl_rf_gain": true,
    "decoder_udp_port": 9999,
    ...
},
"sdroxide-brown": {
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

For a build ahead of a release (the station's `local-test` build of brown, with all four PRs merged), put the changes in `~/.ubitx_cec_desktop/sdr_programs.json` rather than the copy beside the code. That file is merged over the shipped one setting by setting, survives an update of the app, and needs only the settings you change:

```json
{
    "sdroxide-brown": {
        "width_needs_mode_change": false,
        "settle_seconds": 1.5,
        "decoder_udp_port": 9998
    }
}
```

The key must match the program chosen on the Setup tab exactly. Settings under `"sdroxide"` don't reach `"sdroxide-brown"`.

To find out which version you're running: **Help ▸ About**, or the window title. SDRoxide's releases are at github.com/dividebysandwich/sdroxide/releases, brown's at github.com/madmedicnl/sdroxide-brown/releases.

---

## Fix 1: the filter width in the same mode (PR 1)

**Without it:** `M USB 2400` while in USB is ignored. The app gets around it by switching briefly to the other sideband (or, from CW, to LSB) and back (`width_needs_mode_change: true`). You may hear a short blip, and filter changes take a second or two.

**Is it in your version?** With the program in USB at 2700 and the app closed:

```bash
printf 'M USB 2400\n' | nc -w 1 127.0.0.1 4532; sleep 2; printf 'm\n' | nc -w 1 127.0.0.1 4532
```

It's there if it reads `USB` / `2400`. Afterwards, set it back: `printf 'M USB 2700\n' | nc -w 1 127.0.0.1 4532`.

**Then switch:**

```json
"width_needs_mode_change": false,
"settle_seconds": 1.5,
```

`settle_seconds` was 3 only because the mode switch-and-back takes long. With the fix, 1.5 does. The programs still apply a change a moment after accepting it, so don't set it to 0. If the filter or frequency ever "bounces back", raise it a little.

**Check in the app:** filter buttons in USB, LSB and CW take effect with no blip, and the rig never changes mode. With `UBITX_SDR_TRACE=1`, a filter change shows one `M USB <width>`, not a hop through LSB.

---

## Fix 2: squelch, AGC and NR strength (PR 2)

**Without it:** the program answers `RPRT -11` to squelch, AGC and NR level, so the SQL and AGC lamps are greyed and NR is an on/off switch only. Turning NR on from the app also always gives the plain spectral NR at medium, whatever engine you'd picked.

**Is it in your version?**

```bash
printf 'l SQL\nl AGC\nl NR\n' | nc -w 1 127.0.0.1 4532
```

It's there if you get three numbers (for example `0.000000`, `5`, `0.666667`) instead of `RPRT -11`.

**Then switch:** nothing. The app looks for all three every time it connects:

- **SQL lamp:** squelch with its threshold knob, 0 (open) to 1 (closed). Clicking a lit lamp opens it fully. A dark lamp doesn't close it with a click: the app can only set an automatic threshold when the S-meter is in dBFS, and this program reports it relative to S9. Use the knob.
- **AGC lamp:** switches AGC off and back on at its speed. Its pop-up has a Fast/Medium/Slow knob.
- **NR lamp's pop-up:** a Low/Med/High strength knob. The engine (RNN, DFNR, SPEC, NR2, NR) is still chosen in the program's NR panel.

**To turn any one of them off** (if it misbehaves):

| To turn off | Put in the program's entry |
| :--- | :--- |
| AGC lamp and knob | `"rigctl_agc": false` |
| NR strength knob | `"rigctl_nr_strength": false` |
| Squelch | `"known_missing": ["squelch"]` |

**Check in the app:**
1. Click each lamp, and check the program's own control follows.
2. Change each one in the program, and check the lamp or knob follows.
3. With the notch, NR and AGC on in LSB, press a filter button. Nothing should change except the width.

The last check matters most without Fix 1: the program keeps these settings per mode, and the app's switch-and-back could disturb them. The app saves and restores them around that.

---

## Fix 3: decoded CW for the DEC strip (PR 3)

**Without it:** the CW decoder's copy is only in the program's own CW panel, so the DEC lamp is greyed.

**Brown's JSON feed is not this.** Brown's Settings ▸ Servers has its own **Decoded text over UDP**, which sends JSON lines. It sends a keyboard mode's line only once it ends, and CW's copy has no line ends, so it never sends CW. The DEC strip needs **Decoded CW over UDP**.

**The ports:** SDRoxide's default is **9999**. Brown's is **9998**, because brown's settings already suggest 9999 for the JSON feed, and a listener on one port must not be handed the other's datagrams. Whatever port is set in the program, `decoder_udp_port` in its entry must match.

**Is it in your version?** Look in Settings ▸ Servers for a section called **Decoded CW over UDP**. If it's there, tick **Enable**, leave it at `127.0.0.1` and its port, and click **APPLY**. Then, with the app closed, the program in CW and a CW signal tuned in (9999 for SDRoxide, 9998 for brown):

```bash
nc -ul 9999
```

It works if the copy appears as the program decodes it. Only the CW panel's copy is sent, not the skimmer's labels on the waterfall, so the panel must be on the signal. Stop `nc` (Ctrl-C) before starting the app, because only one program can listen on the port.

**Expect it a few seconds behind the panel.** Only text the decoder has settled on is sent, so nothing sent is ever taken back. It settles at a word gap at least 1.25 s back from the newest audio, in pieces of at least 2 s, so the strip normally runs 3 to 5 s, about a word or two at 20 wpm, behind the panel's copy.

**No CW on the air?** `make_cw_iq.py` writes a practice recording: a keyed signal at 7.030 MHz in noise, which the program plays over and over. Run `python3 make_cw_iq.py` (it needs numpy), then `sdroxide --file cw_practice.iq --rate 250000 --freq 7025000`, and put the rig on 7.030.00 CW. `--wpm`, `--text` and `--snr` change it.

**Then switch:** in the program's entry, `"decoder_udp_port"` to its port (9999 for SDRoxide, 9998 for brown; `null` turns DEC off).

**Check in the app:**
1. In CW, the DEC lamp is available. Press it: the strip appears at the bottom and fills with the copy, and the console says `[sdr] listening for … decoded CW on 127.0.0.1:<port>`.
2. While DEC is on, the filter narrows to 250 Hz, and AGC switches off if Fix 2 is in. Pressing DEC off puts them back.
3. Leaving CW turns DEC off.

If the console says it cannot listen because the port is in use, something else holds it (an `nc` left running, or SDRangel's decoder listener). Close it, or pick another port in both the program and the entry.

Unlike SDRangel's, this decoder isn't switched on and off by DEC. It runs whenever the program is in CW, and DEC only decides whether the app listens.

---

## PR 4: hide the control strip and the CW panel -- not merged

Not taken into SDRoxide, and not sent to brown. To be rethought: the switches worked, but the window's minimum size had to follow them, and below 600 × 440 the program's Auto layout switches to its phone layout, which drops the spectrum trace. If it comes back, set Settings ▸ UI ▸ **Layout** to **Desktop** to keep the trace.

---

## Fix 5: the RF gain (PR 5)

**Without it:** the program answers `RPRT -11` to `l RF`, so the app's RF GAIN knob is greyed with "not available". The gain can only be set with the program's own **Gain** slider.

**Is it in your version?**

```bash
printf 'l RF\n' | nc -w 1 127.0.0.1 4532
```

It's there if you get a number from 0 to 1 that follows the program's Gain slider (half way along is about `0.5`) instead of `RPRT -11`.

**Then switch:** nothing. The app looks for the level every time it connects (`"rigctl_rf_gain": true`).

**Check in the app:**
1. The RF GAIN knob is live, and reads 0–100 %. It's a share of the dongle's gain range, not dB: rigctl doesn't say what the stage counts in. Each click is 2 %.
2. Turn the knob, and the program's Gain slider follows. Move the slider, and the knob follows.

To turn it off if it misbehaves: `"rigctl_rf_gain": false` in the program's entry.

---

## If something goes wrong

Start the app with its rigctl trace, and keep the lines around the problem:

```bash
UBITX_SDR_TRACE=1 python3 ubitx_cec_desktop.py
```

`[sdr] -> …` is every command sent to the program, and `[sdr] <- changed in the SDR: …` is anything the app took as a change made in the program. `[sdr] … not back from a filter change` means the switch-and-back was slow, which can only happen while `width_needs_mode_change` is `true`.

To go back to how it was, put the switches back to the workaround values: `"settle_seconds": 3.0`, `"width_needs_mode_change": true`, `"decoder_udp_port": null`.

## Tested at the station

2026-09-28, SDRoxide v1.6.8:
- Tuning both ways, USB/LSB/CW, volume, mute and the S-meter in dBm.
- NB, NR and Notch lamps (on/off).
- The filter switch-and-back, including keeping the notch.

2026-09-29, with local builds of the upstream PRs:
- the DEC strip with PR 3: the strip showed exactly what the CW panel copied;
- the RF GAIN knob with PR 5: `l RF` and `L RF` answered correctly, and the knob worked in the app;
- PR 4's hidden strip and CW panel, with the window shrinking once the strip is hidden.

2026-11-03/04, brown's `local-test` build with all four brown PRs:
- PR 1 with `nc` (USB 2700 → 2400 in the same mode), and filter changes in the app;
- PR 2's SQL, AGC and NR-strength controls in the app, with the SQL lamp fix (it now lights as the knob sets the threshold);
- PR 3 with `nc -ul 9998` and the DEC strip, a few seconds behind the panel as expected;
- PR 5 with `l RF` / `L RF` and the RF GAIN knob.

Not yet seen at the station: the two-step switch-and-back (the fix for CWL ending in LSB), which now only matters for brown until its PR 1 is released.
