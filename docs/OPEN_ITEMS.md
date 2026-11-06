# Open items — ubitx_cec_desktop (2026-11-05)

The short list. Detail for each is in TODO.md.

## The app

- **CW tab wiring:**
  - the keyer type (set from EEPROM), speed, sidetone and the two delays;
  - three of them need a rig reboot, which the tab should offer, not do silently.
- **Meters:** the S-meter and the power/SWR meter aren't wired to the rig's reports, so the scanner can't stop on a signal.
- **RX tab:** ATT and IFS aren't wired.
- **Lock, mute and TX off:** check on the rig that these report on/off and aren't just toggles.
- **Setup, Log QSO, EEPROM backup and restore:** check what's still not read or saved. The MCU headroom is hard-coded in the link.
- **Values that don't arrive at connect:** the app prints which ones are missing but doesn't ask the rig for them yet.
- **The SDR connection can stall the window** for half a second when the SDR stops answering. A thread would fix it.
- **SDRoxide VFO A/B:**
  - read which VFO is active in SDRoxide, and B's frequency, so a change made there is known;
  - split itself probably deferred.
- **SDRoxide vs. SDRoxide Brown on the Mac:** they have the same app name, so the app can start or attach to the wrong one. Pick one of the three options in TODO.
- **Small station checks:**
  - the decode strip when the window is resized.
- **Low priority:**
  - `socket://` doesn't take an IPv6 address;
  - there's no way to give a command line for rigctld;
  - watch for the 10 Hz tuning step not reaching the SDR;
  - tidy up once the old app is retired.

## Documentation

- List the settings that stay in SDRoxide's own window (APF lift, NR engine, and so on).
- A step-by-step SDRangel setup guide.

## Waiting on others

- **brown #491 (CW peak): merged.** Try the next pre-release on the station; if APF is missing or wrong, open a ticket (brown asks for a revert if it fails).
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
