# SDRoxide RIT work: review notes (2026-11-03, continued 2026-11-04/05)

Reviewed: Mark's `rigctl_sdr.py`, `sdr_link.py`, `radio_model.py`, `ubitx_link.py` and the RIT parts of `ubitx_cec_desktop.py`.

## Status

**Step 1 done and tested (2026-11-04)**, delivered as `rit_step1.zip`.
- The zip holds the three fixed files, their diffs, `test_rit.py` (8 cases) and `test_rit_loop.py` (6 cases: the SDR and a simulated rig together).
- Mark's baseline on his originals: 12 fail, 2 pass. On the fixed files all 14 pass.
- Mark then ran it on the Mac with the rig and SDRoxide, and it passed.

The step 1 fixes:
- findings 1–4 and 6;
- the band-framing branch in `follow()`;
- the SQL lamp fix, re-added to `_apply_squelch`;
- an unreadable `j` reply is skipped, not read as 0 (0 means RIT off);
- the toggle wait now times out after 3 s (`RIT_TOGGLE_TIMEOUT_SECONDS`). On timeout the SDR is set to the rig's state, without sending the toggle again (finding 9).

**Step 2 done and confirmed on the rig with SDRoxide (2026-11-04).** Delivered as `rit_step2.zip`: four files, diffs against step 1 (`radio_model.py` diffed against the copy attached on 2026-11-03), `test_rit.py` (9 cases) and `test_rit_step2.py` (44 cases: 22, each with and without a settle window; link + transport + real RadioModel, a fake SDRoxide, and a rig that reports on the next tick or later). All pass.
- **The transport** reports `j` changes through one hook, `on_rit`, and sets the SDR's RIT with `set_rit(hz)`. It no longer reads the model. The four-state machine, the toggle flags and the 5 `model_*` hooks are gone.
- **The link** owns the RIT conversation:
  - `_follow_rit()` (from `follow()`) sends the rig's offset as `J`, including 0. That closes finding 7.
  - `_from_sdr_rit()` asks the rig: it toggles only if the state the rig will end up in differs from the one wanted, then requests base + offset. The request goes once per offset.
  - `RIT_CONFIRM_SECONDS = 3`: past that, the SDR is put back to the rig's state.
- **`ubitx_link.py`:** the seed lines are gone from `cr_UX_RIT_Toggle`, and the flags are gone from `_leave_rit`.
- **`radio_model.py`:** `rit_sdr_seed`, `rit_turn_off_sdr_flag`, both properties and the commented setter are gone.
- **A QSY clears RIT (decided with Mark, 2026-11-04).** RIT is for the station being worked, so a change of the SDR's own frequency with RIT on (a click on the spectrum, its dial) means a new station.
  - The rig has no command to move the held (base) frequency, so keeping the offset would take four commands per step.
  - In order: RIT off; once the rig confirms, the new frequency; then wait until the rig reports it. `_leave_rit` sends receive back to the old base first, so the order matters.
  - Meanwhile `follow()` holds back the frequency, so the SDR doesn't snap back. A move made during the wait replaces the target. Past `RIT_CONFIRM_SECONDS` the QSY is given up and the SDR follows the rig.
  - The poll now reports plain `f` (no offset).
  - The same applies with SDR++ or Gqrx when the app's RIT is on.
- **Found on Mark's Mac:** the settle window. His SDRoxide entry has a settle window (`settle_seconds`); the test machine's had none, so it didn't show here.
  - The bug: the poll compared a reading with the last value before calling `_stale()`. Reading back what was just set never reached `_stale()`, so the window never ended early. Any change made in the SDR within `settle_seconds` of something the app sent was ignored until the window ran out.
  - Fixed for frequency, mode, width, RIT and the DSP switches. Volume, squelch and the RF gain already had the right order.
  - `test_rit_step2.py` now runs every case with no window and with a 3 s one: 44 cases. 27 of 44 pass with the old order.
- Found while testing: with a slow rig, the link asked for the RIT receive frequency on every `follow()`, because `_sent_hz` was overwritten each time. Fixed: the request is tracked in `_rit_rx_asked`.

## SDRoxide's RIT (from its source, crates/sdroxide-rigctld/src/proto.rs)

- Its RIT is a switch plus an offset. `j` reports the offset only while the switch is on (`effective_hz`), and 0 otherwise.
- `J n` sets the offset and turns the switch on; `J 0` turns it off.
- An offset typed into SDRoxide's field while its RIT is off is only stored. SDRoxide doesn't apply it, and `j` stays 0, so the app sees no RIT until RIT is clicked on in SDRoxide. This is by design, not ours to fix.
- SDRoxide's offset field doesn't show changes from rigctl while it has keyboard focus (seen 2026-11-04). Clicking elsewhere in SDRoxide shows the value it already has.

## Rig firmware behaviour (from Mark)

- RIT can be turned on while in split. The rig does not refuse it.
- Turning split on while RIT is on turns RIT off: the rig reports `cr_ 0` then `cs_ 1`. `_leave_rit()` then sets the turn-off flag, and the poll sends SDRoxide `J 0`.
- So the 3 s timeout is a safety net for a lost report, not for a refusal in split.

## What the model and link confirm

- Under RIT, the VFO is the receive frequency and is the one that moves. `rit_base_hz` is where RIT was switched on, which is the transmit frequency out of split. `rit_offset` is derived: `frequency(rx_vfo) - rit_base_hz`.
- SDRoxide: `f` = base (transmit), `j` = offset, receive = `f + j`.
- `ubitx_link.cr_UX_RIT_Toggle` reads the RIT state:
  - On a change to on, it captures the base and reads the seed.
  - On a change to off, it calls `_leave_rit()`, which sets `rit_turn_off_SDR`.

## Findings

1. **Crash without RIT (fixed).** `rit_offset` started as `None`.
2. **One bad reply stopped the poll, or made connect fail (fixed).** Bare `int()` on `j` and `s` replies.
3. **RIT sign (fixed).** The poll reports `f + j`. `set_frequency()` expects the base back.
4. **`J` sent as a query (fixed).** It is now a command.
5. **Turning RIT off in the app gets undone: not a bug.**
6. **The SDR's seed never reached the rig (fixed).** `cr_UX_RIT_Toggle` now asks the rig for base + seed with `_request_frequency`.
7. **Tuning RIT back to exactly 0 in the app leaves SDRoxide on the old offset (open).** The poll only sends `J` when `model_offset != 0`.
8. **The one rule (open; step 2).**
   - `_from_sdr_update_model_offset` writes the model before the rig confirms.
   - The seed and turn-off flags are messages passed through the model, and their getters clear them when read.
   - Proposed: the rig leads.
     - On the rig's confirmed RIT and offset, `follow()` sends `F base` and `J offset` (`J 0` when RIT is off), and marks both with `_set`.
     - When `j` changes in SDRoxide and isn't `_stale`, the link asks the rig: it turns RIT on if needed, then requests base + offset, or turns RIT off at 0.
     - This replaces the four-case state machine, the in-progress flags, the seed and turn-off flags, and three of the five hooks.
9. **The toggle wait had no time limit (fixed).** `Toggle_RIT` is still a toggle, not a set; step 2 should send it only when the rig's confirmed state differs.
10. **Smaller points (open).**
    - Untagged `print`s: put them behind `UBITX_SDR_TRACE`.
    - Remove the `# MJH` notes and commented-out code.
    - `_from_sdr_split` only prints.
    - `_from_sdr_rit_state_changed` calls `self._model.changed()`, marked "looks like unnecessary".

## Found along the way (2026-11-04)

- `ubitx_cec_desktop.py` line 69 had `# import sdr_controls` commented out, so Advanced settings raised `NameError`.
- The SDR Path in Advanced settings launched brown even with SDRoxide selected. This is the existing TODO item about the path overriding the selected program. Workaround: start SDRoxide first, then the app.
