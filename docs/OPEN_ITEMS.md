# Open items — ubitx_cec_desktop (2026-11-10)

The short list. Detail for each is in TODO.md.

## The app

- **Power/SWR meter:** waits for the future Pico board's sensor (the switch and factors are in Machine settings, greyed).
- **S-meter calibration:** set the SDR's S9 point from a known signal, and the radio S-meter sensor's eight levels from the SDR's reading (today the levels are typed in EEPROM settings).
- **RX tab ATT/IFS and the SDR "-none-" choice:** built 2026-11-10 (att_ifs_none.zip), to try at the station.
- **Setup, Log QSO:** check what's still not read or saved -- the Appearance choice on Station is still a placeholder.
- **Startup recovery:** a slow-booting rig is no longer called silent, and missing values are fetched by restarting it (confirmed 2026-11-06). Still to watch: the "skipped bytes" at startup -- the hex lines will show if reports run together.
- **The SDR connection can stall the window** for half a second when the SDR stops answering. A thread would fix it.
- **SDRoxide VFO A/B and split:** kept in step with the rig both ways -- A/B, A⇄B, RIT and split -- confirmed at the station 2026-11-10.
- **SDRangel VFO B (later):** needs new REST code -- a second channel kept on the rig's other VFO.
- **SDRoxide vs. SDRoxide Brown on the Mac:** they have the same app name, so the app can start or attach to the wrong one. Pick one of the three options in TODO.
- **Low priority:**
  - `socket://` doesn't take an IPv6 address;
  - there's no way to give a command line for rigctld;
  - watch for the 10 Hz tuning step not reaching the SDR;
  - tidy up once the old app is retired.

## Documentation

- List the settings that stay in SDRoxide's own window (APF lift, NR engine, and so on).
- A step-by-step SDRangel setup guide.

## Waiting on others

- **brown #491 (CW peak):** merged, and working in the pre-release on the station (2026-11-08) -- nothing to file.
- **brown `spectrum_spans`:** then drop the 20 MHz guess.
- **brown's view refit** when the span changes.
- **brown SUB over rigctl:** a second receiver for split listening. Ask in an issue first.
- **Upstream SDRoxide:** port APF and the span, after #491 merges.
- **SDRangel bugs:** remove our workarounds as each gets fixed.

## Needs an antenna

- **CW pitch:** check it's heard at the right pitch through SDRangel.
- **WDSP receiver:** go through its checks on the station.

## Library and Designer

- **The Designer bug:** a button inside a labelled frame fails.
- **Library tidy-ups:**
  - font scaling on the canvas widgets;
  - the triplicated dial scroll code;
  - guards for teardown callbacks;
  - the treeview decision.

## Hardware

- Rewire the USB-TTL monitor adapter: GND and RX only.
- **Brown #469 follow-ups:** PR #641 (the spans in `\dump_caps`) approved by the maintainer, his two small points done (amended a75c9098); waiting on the merge. App side built and checked. Next (tomorrow): PR 2, the waterfall refit (option A, interface only).
- **Frequency calibration:** a WWV routine in the app (master cal from a zero-beat); later, measuring the TX carrier through Brown's TCI IQ.
- **RIT and split testing: DONE 2026-11-10.** A-F pass from the app and from Brown, split now synced both ways with Brown. Decided: in split a VFO transmits on its receive frequency, RIT offset included.
- **TX offset:** key-down lands ~950 Hz above the dial in USB -- tone or calibration? Check master cal.
- **Test upkeep:** the lock test's stand-in lacks `toggle_rit_for_operator` (8/10); one stale case in test_cw_values.py (the restart offer).
