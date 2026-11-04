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

**Step 2 not started:** the rig-leads redesign (finding 8), which also closes finding 7.

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
