# SDRoxide RIT work: review notes (2026-11-03, to continue 2026-11-04)

Reviewed: Mark's `rigctl_sdr.py` and `sdr_link.py` with the RIT changes. Still needed: `radio_model.py` and the RIT parts of `ubitx_cec_desktop.py`.

Done already: the SQL lamp fix. `SDR_Link._apply_squelch` now calls `self._audio_changed()` after `set_level("SQL", ...)`, so the lamp redraws when the squelch knob sets the threshold. Applied to Mark's own `sdr_link.py` (the one with the RIT work).

## Findings, most serious first

1. **Crash without RIT.** `self.rit_offset` starts as `None` and only gets a number when `discover()` reads `j`. `set_frequency()` and the poll both do `self.frequency - self.rit_offset`, so Gqrx, SDR++, rigctld (and an SDRoxide whose `j` doesn't answer) raise `TypeError` on every frequency change. Fix: start at 0, reset to 0 in `disconnect()`, use only when `RIT in self.capabilities`.
2. **One bad reply stops the poll.** `int(reply.values[0].strip() ...)` in the RIT code, and `int(values[0])` / `values[1]` in `_split_and_vfo`, raise on `RPRT -11`, a decimal or a single line. The poll catches only `ConnectionLost`, so it never reschedules: nothing follows any more. The same in `discover()` makes connect fail. Fix: read through `_number()`, check lengths.
3. **RIT sign when tuning in SDRoxide.** `follow()` sends SDRoxide `rx - offset` (the base). SDRoxide's `f` returns the VFO (base); RIT is `j`. Going back, rx = VFO + offset, but the poll reports `self.frequency - self.rit_offset`: off by twice the offset. (Assumes rx = base + offset, as `_from_sdr_update_model_offset` has it; check `radio_model.py`.) Also `set_frequency()` records `self.frequency - self.rit_offset` as the value to expect back, but SDRoxide reads back `self.frequency`, so every reading is ignored for the 3 s settle window.
4. **`J` sent as a query.** `self._client.query("J 0")` and `query("J " + ...)` should be `self._command(...)`.
5. **The one rule.** `_from_sdr_update_model_offset` writes the model's frequency, and `_from_sdr_rit_state_changed` writes `rit_sdr_seed`, before the rig confirms. The window sets `rit_turn_off_SDR` on the model for the transport. Proposed instead: the rig leads; on its confirmed RIT and offset, `follow()` sends `F base` and `J offset` and marks both with `_set`. When `j` changes in SDRoxide and isn't `_stale`, the link asks the rig for that offset (or RIT off at 0); the model changes on the rig's confirmation. This replaces `rit_toggle_in_process`, `last_rit_mode_change` and the four-case state machine.
6. **Smaller points.**
   - In `follow()`, the band-framing branch sends `hz` without subtracting the RIT offset.
   - About a dozen `print`s without the `[sdr]` prefix: put them behind `UBITX_SDR_TRACE`.
   - Remove the `# MJH` notes and the commented-out code.
   - `_call` now returns a value, which is fine, but with trace on it logs the RIT getters as "changed in the SDR".
   - `_from_sdr_split` only prints.