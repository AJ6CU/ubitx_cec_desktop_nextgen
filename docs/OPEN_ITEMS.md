# Open items — ubitx_cec_desktop (2026-11-11)

The short list. Detail for each is in TODO.md.

## The app

- **Power/SWR meter:** waits for the future Pico board's sensor (the switch and factors are in Machine settings, greyed).
- **S-meter calibration:** set the SDR's S9 point from a known signal, and the radio S-meter sensor's eight levels from the SDR's reading (today the levels are typed in EEPROM settings).
- **SDR "-none-" choice:** built, to check at the station.
- **Help page:** built (help_page.zip): getting started, firmware, the four tabs and Setup. Needs your screenshots and photos (help/SHOTLIST.md), the USB-TTL wiring, and the "To fill in" parts. "Keep on top" is now in Setup > Station.
- **Log QSO:** test the button still works, and check what Setup and Log QSO still don't read or save. The Appearance choice on Station is still a placeholder.
- **Startup flood (2026-11-10):** an unrecoverable start-up, looping on "Tuning Preset 1". Mark to catch the console next time. If it is the rig flooding (as with the USB-TTL adapter): restart the rig once when the repeat warning fires, a second time at most, then say to power-cycle or unplug the adapter.
- **Startup:** watch the "skipped bytes" at startup -- the hex lines will show if reports run together.
- **The SDR connection can stall the window** for half a second when the SDR stops answering. A thread would fix it.
- **SDRangel VFO B (later):** needs new REST code -- a second channel kept on the rig's other VFO.
- **SDRoxide vs. SDRoxide Brown on the Mac:** they have the same app name, so the app can start or attach to the wrong one. Pick one of the three options in TODO.
- **Frequency calibration:** a WWV routine in the app (master cal from a zero-beat); later, measuring the TX carrier through Brown's TCI IQ.
- **TX offset:** key-down lands ~950 Hz above the dial in USB -- tone or calibration? Check master cal.
- **Test upkeep:** the lock test's stand-in lacks `toggle_rit_for_operator` (8/10); one stale case in test_cw_values.py (the restart offer).
- **Low priority:**
  - `socket://` doesn't take an IPv6 address;
  - there's no way to give a command line for rigctld;
  - watch for the 10 Hz tuning step not reaching the SDR;
  - tidy up once the old app is retired.

## Documentation

- List the settings that stay in SDRoxide's own window (APF lift, NR engine, and so on).
- A step-by-step SDRangel setup guide.

## Waiting on others

- **Brown #666 (the waterfall refit):** waiting on review. It also carries #641's two review fixes, which missed that merge.
- **Brown #641 in a release:** then drop the 20 MHz span guess in the app.
- **brown SUB over rigctl:** a second receiver for split listening. Ask in an issue first.
- **Upstream SDRoxide:** port APF and the span.
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
