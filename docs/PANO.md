# Scans started in the SDR (SDRoxide's PANO and the like) and uBITX CEC Desktop

Written 2026-11-20. **Decision for 1.0: don't use them.** The help (Connecting
uBITX CEC Desktop to the SDR) tells users not to run the SDR program's own
scanner while uBITX CEC Desktop is connected, and to scan with uBITX CEC
Desktop's own Channels instead, where the uBITX leads and the SDR follows.

## Not only PANO

PANO is where it was found, but any scanner inside the SDR program does the
same: to step, it moves the program's frequency, which uBITX CEC Desktop reads
over rigctl and can't tell from the operator tuning.

| Program | Its scanner | Same problem? |
| :--- | :--- | :--- |
| SDRoxide | SCAN: MEM, RANGE, PANO | yes, seen at the station |
| Brown | SCAN: MEM, RANGE (no PANO yet) | yes: same `stop_scan_for_operator` in its engine |
| SDR++ | Scanner module | very likely: it tunes the VFO rigctl reports |
| SDRangel | Frequency Scanner channel | probably; depends on which frequency it moves. Not checked |
| Gqrx | none built in; external scanners use its remote control | yes, and they compete for the same port |

The rest of this note is about PANO, where it was studied.

## What PANO is

New in SDRoxide 1.7.3: a third kind of SCAN, beside MEM and RANGE. It sweeps a
range slice by slice and stitches the slices into one row of the full-band strip
(WIDE) per sweep, so an RTL-SDR, which sees only a couple of MHz at once, gets a
band-wide waterfall. It's in the scanner window: SCAN on the display strip, then
PANO, then a Band or From/to.

Slice geometry (`crates/sdroxide-radio/src/scanner.rs`, `slice_centers_with` and
`panorama_geometry`), with span = the receiver's span after decimation and the
Slice width u (0.5–0.95, 0.8 by default):

- first dial position: From + (u/2) × span
- each next one: + (u − 0.1) × span (neighbors overlap by a tenth of the span)
- last: To − (u/2) × span, so the top slice ends exactly on To
- then back to the first

Brown doesn't have PANO yet.

## What happens with uBITX CEC Desktop connected

`scan_next_slice` in `engine.rs` parks the dial (VFO A or B) on each slice
center. Over rigctl that looks exactly like the operator tuning, so uBITX CEC
Desktop follows it and retunes the uBITX.

Seen at the station (Mark, 2026-11-19/20, RTL-SDR Blog V3):

- 28–35 MHz on the normal tuner: the uBITX was dragged along, a jump at each
  slice, and the scan carried on.
- 10–30 MHz in direct sampling: the scan stopped after the first step or so,
  around 10.33 MHz, at a slightly different place each time.
- Without uBITX CEC Desktop running, PANO swept 10–30 MHz fine.
- On the RTL-SDR Blog V4 (no direct sampling) it did not get below its first
  stop with direct sampling on Auto. Not retried with direct sampling off.

## Why it stops: a race in `sdr_link.py`

1. SDRoxide moves to slice 1. `_from_sdr_frequency` records it as `_sent_hz` and
   asks the uBITX for it.
2. Before the uBITX confirms, SDRoxide moves to slice 2: `_sent_hz` = slice 2,
   and the uBITX is asked again.
3. The uBITX's late report of slice 1 arrives. `follow()` sees a receive
   frequency that differs from `_sent_hz` and takes it for a move made at the
   rig, so it sends slice 1 to SDRoxide.
4. In SDRoxide, any SetVfo calls `stop_scan_for_operator`: the scan stops.

Faster slices (direct sampling) make the race likelier, hence the varying stop
point. The same race can bounce the SDR back after two quick clicks on the
waterfall, closer together than the uBITX takes to answer -- with any SDR
program, not only SDRoxide.

## Fix 1: the follow race (uBITX CEC Desktop)

Remember the frequencies asked of the uBITX in the last ~1.5 s. A report of one
of them that isn't the latest is a late confirmation: wait, don't send it back.
Clear the list when the latest is confirmed. About ten lines in `sdr_link.py`.

With it, PANO is no longer stopped -- it drags the uBITX along on every slice,
which is still not wanted. So on its own it fixes the double-click bounce, not
PANO.

Side effects (it can only ever hold a frequency back, never send a wrong one):

1. **The uBITX never reaches the latest** (refused, band limit): it would sit on
   an older listed frequency and the two would disagree. Guard: a time limit,
   after which the rig leads, as `_qsy_waiting` does with RIT_CONFIRM_SECONDS.
2. **A real move onto a listed frequency** within the window (the knob back to a
   frequency just clicked; A/B or a memory landing on one): the SDR misses that
   one move until the next change or the time limit. Guard: short window,
   cleared on confirmation.
3. **RIT, split and VFO switches**: the follow code's three special cases
   (`_qsy`, `_vfo_pending`, VFO_RIT_QUIET_SECONDS). Store exactly what's
   compared (`role_frequency("rx")`) and leave those paths alone. This is the
   real risk; RIT after a QSY broke before.
4. **The uBITX rounds** what it's asked: never matches the list, so the same as
   today.
5. **Shared by every program** (SDR++, Gqrx, Brown, SDRangel): case 2's delay is
   the only change any could see.

Tests: one that fails without the fix (slow rig; two quick clicks), recovery
after the time limit, the window limit, the whole suite before and after
(`test_rit_vfo` stays at 10/13). At the station: PANO, double-clicks, RIT with a
QSY, an A/B switch.

## Fix 2: ask SDRoxide whether a scan is running

SDRoxide's rigctl server (`crates/sdroxide-rigctld/src/proto.rs`) has no scan
commands: no `g`/`\scan`, nothing that says a scan is running. Hamlib itself
has `g`/`\scan` to start and stop one (DELTA, MEM, PROG, VFO, … STOP) but no
standard way to ask whether one is running.

Hamlib's manual says nothing about how third-party servers should extend the
protocol, but its own mechanism is named extras behind the standard commands:
each backend can declare ext levels, funcs and parms, reached through `l`/`L`,
`u`/`U`, `p`/`P` (`rig_ext_lookup` in `rigctl_parse.c`), and listed by `l ?`,
`u ?`.

So the request to SDRoxide would be a read-only func:

- `u SCANNING` → `1` while any scan (MEM, RANGE, PANO) runs, else `0`
- listed in `u ?`
- SDRoxide already answers `RPRT -11` for an unknown func, so uBITX CEC Desktop
  can probe it at connect (`discover()`) and carry on as now without it.

uBITX CEC Desktop would then stop following while it reads `1`, and PANO would
run without touching the uBITX. Limit: programs going through Hamlib's
`netrigctl` (WSJT-X, fldigi) won't see it, since netrigctl doesn't pass ext
funcs through; uBITX CEC Desktop talks to the port directly, so that doesn't
matter here.

Not filed. The issue text would go in the project as
`ubitx_cec_desktop/sdroxide/issue_scan_status.md`.

## Resolution plan

1. 1.0: don't use (the help says so). No code change.
2. After 1.0: Fix 1, with its tests and the station checks above.
3. File the SDRoxide issue for `u SCANNING`; ask Brown for the same (it has
   MEM and RANGE scans already).
4. When SDRoxide has it: probe and pause following; then change the help from
   "don't use" to "works, uBITX stays put" for that program; the others stay
   "don't use".
