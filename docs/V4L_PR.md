# RTL-SDR Blog V4L support: testing and PR texts

**Status 2026-11-16:** tested on Brown v2.3.0.4.3 on macOS with a V4L, a V4 and a plain R820T (V3): all pass. **Brown PR #751** opened from `AJ6CU/sdroxide:brown-rtlsdr-blog-v4l`. **Upstream PR #906** opened from `AJ6CU/sdroxide:rtlsdr-blog-v4l`, tested on v1.7.3 (`a9d6516f`): 18 + 54 + 12 tests; V4L (incl. direct sampling refused), V4 and V3 on air.

Two patches with the same change:

- `upstream-0001-RTL-SDR-support-the-RTL-SDR-Blog-V4L.patch`, against upstream `a9d6516f` (2026-11-14)
- `brown-0001-RTL-SDR-support-the-RTL-SDR-Blog-V4L.patch`, against Brown `8f1b44e8` (2026-11-15). This one also adds the TODO.md line and the rollback text.

**What's been checked so far:** `rustfmt --check` on every changed Rust file, in both forks.

**What hasn't been checked:** it hasn't been compiled. Crates.io was unreachable from my workspace, so the first `cargo test` is yours.

---

## 1. Build and unit tests (Mac)

### Upstream

```
cd ~/Documents/GitHub/sdroxide
git fetch upstream
git checkout -b rtlsdr-blog-v4l upstream/main
git am ~/Downloads/upstream-0001-RTL-SDR-support-the-RTL-SDR-Blog-V4L.patch
cargo test -p sdroxide-r82xx -p sdroxide-rtlsdr
cargo check --workspace --all-targets
```

If `upstream/main` has moved past `a9d6516f` and `git am` stops, send me the output.

### Brown

Do the same in your Brown clone, against Brown's `main`:

```
git checkout -b rtlsdr-blog-v4l origin/main
git am ~/Downloads/brown-0001-RTL-SDR-support-the-RTL-SDR-Blog-V4L.patch
```

Then run the same two cargo commands.

### New tests to look for

In `sdroxide-r82xx`:
- `a_board_is_confirmed_only_by_its_own_tuner`
- `a_blog_v4l_upconverts_below_the_crossover`
- `a_blog_v4l_switches_between_its_two_inputs`
- `a_blog_v4l_leaves_r23_to_the_frequency_table`
- `a_blog_v4l_bypasses_the_tracking_filter_on_every_hf_tune`
- `a_blog_v4l_takes_the_r828d_vco_power_reference`

In `sdroxide-rtlsdr`:
- `detects_a_v4l_from_a_truncated_read`
- the two string tables in `identifies_a_v4_without_a_manufacturer_string` and `does_not_mistake_other_dongles_for_a_v4`

The existing V4 and R828D tests must still pass, especially `the_r828d_bring_up_writes_exactly_what_it_always_has`.

---

## 2. On the V4L

Start it with the driver's log on:

```
RUST_LOG=sdroxide_rtlsdr=debug cargo run --release
```

Use the same `cargo run` you normally use, with this prefix.

### Opening

- [ ] The log says `tuner: R820T/R820T2 (RTL-SDR Blog V4L)`.
- [ ] Before the patch, the log said `switching to direct sampling (Q branch)` on HF. That line must not appear.
- [ ] The radio's label reads `... (R820T/R820T2, Blog V4L)`.

### HF, through the upconverter

Settings → Radio → HF reception: **Automatic**.

- [ ] 10.000 MHz (WWV) or 15.000 MHz: the carrier sits on the dial.
- [ ] 14.074 or 7.074 MHz: FT8 signals sit in the right place and decode.
- [ ] Across 28.8 MHz: tune from 28.0 to 29.5 MHz. The band is continuous and the noise floor doesn't jump.
- [ ] Choose **Direct sampling (Q branch)**: it's refused with "a Blog V4 or V4L upconverts HF in hardware…".

### Above HF, on air-in

- [ ] Broadcast FM around 88–108 MHz.
- [ ] 2 m (144–148 MHz), or NOAA/APRS.
- [ ] 70 cm, or ADS-B at 1090 MHz.
- [ ] Back to HF afterwards: it still works, which shows the input switches back.

### Also worth seeing

- [ ] Bias tee on and off still works.
- [ ] ppm correction moves a known carrier.

If you have a Blog V4 or a plain R820T stick to hand, a quick check that HF still behaves as before on it is worth a lot: the V4 should be unchanged, and a plain stick should still use direct sampling.

---

## 3. Before the PR: a comment on #602

madmedicnl said the V4L was "ours to add". Say on the issue that you have a patch, so nobody writes it twice:

> I have a patch for this: it ports librtlsdr's V4L commit (osmocom 0204c9c) to sdroxide-r82xx/sdroxide-rtlsdr. A V4L is named by its "RTLSDRBlog"/"Blog V4L" strings and confirmed by its R820T-reading tuner, then upconverts below 28.8 MHz with two-input switching, like librtlsdr. Unit tests pass; I'm testing it on my V4L now and will open a PR here (and one on sdroxide-brown) once it works on air. Shout if you'd rather do it differently.

---

## 4. Upstream PR text

**Title:** RTL-SDR: support the RTL-SDR Blog V4L (#602)

Fixes #602.

The RTL-SDR Blog V4L ("V4 Lite") uses an R828S, because the V4's R828D is out of production. The R828S answers on I2C as an R820T, so the driver opened a V4L as a plain R820T stick and sent HF to direct sampling, which the board isn't wired for. The log in #602 shows "Blog V4L … R820T/R820T2 … direct sampling (Q branch)", and HF came out about 100 MHz off.

This ports osmocom librtlsdr `0204c9c` ("Add RTL-SDR Blog V4L Support", RTL-SDR Blog). That's the commit after `84195f1`, the one `sdroxide-r82xx` was transcribed from:

- A V4L is recognised by its strings, `RTLSDRBlog` / `Blog V4L`.
  - They come from the USB descriptors. When the OS gives no product string, they come from the EEPROM.
  - Matches are whole-string, like librtlsdr's `strcmp`, so a V4L is never taken for a V4.
  - The tuner has to agree: a V4 must be an R828D, and a V4L an R820T.
- Below 28.8 MHz it upconverts, like the V4, and never direct-samples.
- It has two inputs: HF on cable 1, and everything above on air-in.
  - The input only changes on a band change.
  - The GPIO 5 upconverter gate works as on the V4.
  - There's no third input and no notches.
- The tracking filter is bypassed on every HF tune, as was already done for the V4.
- It uses the R828D's VCO power reference, even though the chip reads as an R820T.

**Code:**
- `sdroxide-r82xx::Board` (`Plain`, `BlogV4`, `BlogV4L`) replaces the V4 flag.
- `is_blog_v4()` now means "V4 or V4L", which is what its callers (direct sampling, receive ranges) need.
- RX-888 callers pass `Board::Plain`.

**Interface and docs:**
- Two tooltips now say "Blog V4/V4L", in all eleven languages.
- §6.2.5 and §6.2.11 of the manual mention the V4L, and so does the README.

**Not covered:**
- Over rtl_tcp, a V4L still reads as an R820T, because the protocol carries only the tuner chip. So Automatic direct-samples it below 24 MHz.
- The manual says so: for now, HF on a V4L needs USB.
- Fixing that would need a new HF choice. That's a separate change if wanted.

No wire change.

**Tested:**
- Unit tests in `sdroxide-r82xx` and `sdroxide-rtlsdr`, covering the strings, the tuner veto, the upconversion, the two-input switching with GPIO 5, R23, the tracking-filter bypass and the VCO power reference.
- `cargo check --workspace --all-targets` on macOS.
- On my V4L on macOS: *fill in from section 2.*

**Not tested:** Windows, Linux, and the EEPROM fallback (a host that hides the product string).

---

## 5. Brown PR text

Use the same text as section 4, with these changes:

- Title: **RTL-SDR: support the RTL-SDR Blog V4L (upstream #602)**.
- Replace "Fixes #602." with "Upstream issue: dividebysandwich/sdroxide#602 (the same change is offered upstream)."
- Add:

> TODO.md: one line under Now.
>
> Rollback: revert the commit. Nothing is stored or sent on the wire, so going back just opens a V4L as a plain R820T again.
