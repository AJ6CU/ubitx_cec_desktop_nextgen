# Open items — ubitx_cec_desktop (2026-11-17)

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
- **Brown's CPU on the Pi -- SOLVED (2026-11-12):** the CW skimmer's Neural decoder took ~2 cores; on Timing Brown is ~57 %, skimmers off ~25 % (upstream ~30 %). Brown #714 (upstream's #784 RTL-SDR fix) saves another ~45 %. Brown PR written: skimmers only in their own mode (sdroxide/brown/brown-skim-only-in-mode.patch) -- test on the Mac and Pi, then push. Optional: post the note (brown_issue_performance.md).
- **Windows test:** the X1 Carbon (2014, 2-core) couldn't run Brown smoothly on Windows 11 (see TODO, "Field-laptop floor"); RE-TESTED 2026-11-12: workable with the CW skimmer on Timing (30-35 %, no dropped samples at 2.048 Msps). With the app: Brown 60-70 % (rigctl polling?), and the app's window does not resize live -- fix written (resize_freeze.zip), to try on the X1. See TODO. Finish the Windows wheel test on the desktop. Add the minimum spec and the slow-laptop settings to the help page.
- **Low priority:**
  - changing Windows' display scale WHILE the app runs (150 % -> 200 %) leaves the window too narrow, content cut off; starting at either scale is fine. Workaround: restart the app. A refit on the change works in tests here but not on the X1 -- log a live change there first (TODO, "Changing Windows' display scale");
  - the app's processor use (~10 % of a Pi 5 core): trim S-meter redraws and polling, measured first;
  - `socket://` doesn't take an IPv6 address;
  - there's no way to give a command line for rigctld;
  - watch for the 10 Hz tuning step not reaching the SDR;
  - tidy up once the old app is retired.

- **SDR window layout (to experiment, 2026-11-15):** show only the SDR's waterfall under the app. Undock Controls + panel in Brown/upstream (kept in config.toml at start-up; no command-line option). Idea: an "Arrange SDR windows" step in Setup using a separate SDR profile (SDROXIDE_CONFIG_DIR). See TODO.
- **Upstream SDRoxide ports:** span PR 1 open as upstream #888; app test of the span build, then APF branch build; PRs 2-3 after #888. See TODO and sdroxide/UPSTREAM_PORT.md.
- **RTL-SDR Blog V4L in SDRoxide (upstream #602; 2026-11-17):** patches written for upstream and Brown, porting librtlsdr's V4L commit (osmocom 0204c9c): named by its "Blog V4L" strings, confirmed by its R820T-reading tuner, upconverts below 28.8 MHz, two inputs, no direct sampling. TESTED 2026-11-16 on Brown v2.3.0.4.3 (Mac): 17+59+12 tests pass; V4L works (WWV 10 MHz, NOAA 162.550, input switch, direct sampling refused); V4 and a plain R820T/V3 unchanged. BROWN PR #751 OPEN (branch brown-rtlsdr-blog-v4l on AJ6CU/sdroxide). UPSTREAM PR #906 OPEN (branch rtlsdr-blog-v4l on AJ6CU/sdroxide; tested on v1.7.3 a9d6516f: 18+54+12 tests; V4L, V4, V3 on air; direct sampling refused). Next: a pointer comment on #602; watch both PRs. Not pursued: the ppm estimate jumping after a direct-sampling switch (Mark: not worth it). Over rtl_tcp a V4L still gets direct sampling on HF (protocol carries the chip only). See sdroxide/V4L_PR.md.

## Documentation

- List the settings that stay in SDRoxide's own window (APF lift, NR engine, and so on).
- A step-by-step SDRangel setup guide.

## Waiting on others

- **Brown #641 in a release:** then drop the 20 MHz span guess in the app.
- **brown SUB over rigctl:** a second receiver for split listening. Ask in an issue first.
- **Upstream SDRoxide:** port #463, #479, #641, #666, #491. UNBLOCKED: Brown merged #666 (2026-11-11). Post the heads-up to Brown first (sdroxide/brown/brown_ask_backport.md), then the upstream issue (sdroxide/issue_port_from_brown.md), trimmed to what he is happy with.
- **SDRangel:** report the frozen `channelPowerDB` in the WDSP receiver's report (34.89 dB whatever the signal, 8.1.0).

## Needs an antenna

- **CW pitch:** check it's heard at the right pitch through SDRangel.
- **WDSP receiver:** go through its checks on the station.

## Library and Designer

- **sCustomTkinter 0.2.1 is on PyPI** (2026-11-12): `pip install scustomtkinter`, `[designer]` for Pygubu. Treeview left out, meter fonts scale, one dial handler, deferred-call teardown guard, labelled-frame fixes (Designer collapse, refit on title, fit before the Designer measures). Validation test passes; tested from TestPyPI and PyPI.
- **The app's wheel now depends on `scustomtkinter>=0.2.1` from PyPI** (packaging/build_wheel.py) -- no git needed to install it. Rebuild the wheel and retest on Windows.

## Hardware

- Rewire the USB-TTL monitor adapter: GND and RX only.
