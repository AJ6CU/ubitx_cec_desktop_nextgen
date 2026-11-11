# Open items — ubitx_cec_desktop (2026-11-11)

The short list. Detail for each is in TODO.md.

## The app

- **Power/SWR meter:** waits for the future Pico board's sensor (the switch and factors are in Machine settings, greyed).
- **Help page:** built (help_page.zip): getting started, firmware, the four tabs and Setup. Needs your screenshots and photos (help/SHOTLIST.md), the USB-TTL wiring, and the "To fill in" parts. "Keep on top" is now in Setup > Station.
- **Startup flood (2026-11-10):** an unrecoverable start-up, looping on "Tuning Preset 1". Mark to catch the console next time. If it is the rig flooding (as with the USB-TTL adapter): restart the rig once when the repeat warning fires, a second time at most, then say to power-cycle or unplug the adapter.
- **Startup:** watch the "skipped bytes" at startup -- the hex lines will show if reports run together.
- **The SDR connection can stall the window** for half a second when the SDR stops answering. A thread would fix it.
- **SDRoxide vs. SDRoxide Brown on the Mac:** they have the same app name, so the app can start or attach to the wrong one. Pick one of the three options in TODO.
- **Frequency calibration:** a WWV routine in the app (master cal from a zero-beat); later, measuring the TX carrier through Brown's TCI IQ.
- **Install scripts for Mac, Linux and Windows (later):** the wheel works (packaging/build_wheel.py, CONFIRMED 2026-11-10 once Tk was installed). The scripts should check for Tk and install it where they can (Homebrew `python-tk@3.x`, apt `python3-tk`), git for sCTk, and a venv. Revisit the launcher's Tk message then.
- **Low priority:**
  - `socket://` doesn't take an IPv6 address;
  - there's no way to give a command line for rigctld;
  - watch for the 10 Hz tuning step not reaching the SDR;
  - tidy up once the old app is retired.

## Documentation

- List the settings that stay in SDRoxide's own window (APF lift, NR engine, and so on).
- A step-by-step SDRangel setup guide.

## Waiting on others

- **Brown #666 (the waterfall refit):** F4NRM's review (2026-11-11) answered: the DEC chip's asks are now a list (two quick clicks keep the zoom), a refused ask expires after 2 s, the sim goes through the real calls, TODO carries #666. 34 tests pass and checked on the Mac at the station. Amend, force-push and post brown_666_reply.md; then waiting on re-review.
- **Brown #641 in a release:** then drop the 20 MHz span guess in the app.
- **brown SUB over rigctl:** a second receiver for split listening. Ask in an issue first.
- **Upstream SDRoxide:** port #463, #479, #641, #666, #491. ON HOLD until Brown merges #666: then post the heads-up to Brown (sdroxide/brown/brown_ask_backport.md), then the upstream issue (sdroxide/issue_port_from_brown.md), trimmed to what he is happy with.
- **SDRangel:** report the frozen `channelPowerDB` in the WDSP receiver's report (34.89 dB whatever the signal, 8.1.0).

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
