# The span changes as three upstream PRs

**Status (2026-11-20):** PR 1 merged as #888 (with #906, the V4L, the same
day). PR 2 and PR 3 are next, each from its own fresh branch off
`upstream/main`; they don't depend on each other.

**On hold (Mark, 2026-11-21):** submit PR 2 and PR 3 after SDRoxide's next
release (the first after 1.7.3, which will carry #888). Before submitting,
check the patches still apply on the then upstream/main and run the tests.
The help's grid gets SDRoxide's Span ✓ at the same time.

The patches were rebuilt on upstream main d10d3002 so that each applies
alone: the Hamlib-citation comment on the `\dump_caps` code, which used to
ride in PR 3, is now in PR 2, where that code is.

- `span-pr2-dump-caps.patch` -- rigctld only (proto.rs, state.rs)
- `span-pr3-refit.patch` -- sdroxide-ui only (spectrum.rs, mod.rs, frame.rs, top_bar.rs)

For each, in the fork clone:

```
git fetch upstream
git switch -c upstream-span-2 upstream/main
git am ~/Downloads/span-pr2-dump-caps.patch
cargo test -p sdroxide-rigctld
git push -u origin upstream-span-2
```

and the same with `upstream-span-3`, `span-pr3-refit.patch` and
`cargo test -p sdroxide-ui spectrum`. Run the tests on the Mac before
pushing: the rebuild was only checked for applying cleanly (no crates.io
access where it was made).

---

## PR 1 -- merged (#888)

**Title:** rigctl: the sampled span as Hamlib's SPECTRUM_SPAN

Ported from sdroxide-brown, madmedicnl/sdroxide-brown#479. `l SPECTRUM_SPAN`
reports the sampled span in Hz; `L SPECTRUM_SPAN <Hz>` sets a power-of-two
decimation. uBITX CEC Desktop's Spectrum Span slider uses it; it lights up
by itself with an SDRoxide built from main (not in 1.7.3).

---

## PR 2

**Branch:** `upstream-span-2`, from `span-pr2-dump-caps.patch`

**Title:** rigctl: list the spans SPECTRUM_SPAN can give in \dump_caps

Follows #888. A client that moves the span over rigctl otherwise has to guess which widths exist. Hamlib's own place for a scope's spans is the rig's `spectrum_spans`, which `\dump_caps` prints on a `Spectrum spans:` line, narrowest first, each as `%.0f ` (Hamlib's `tests/dumpcaps.c` and `src/sprintflst.c`, cited in the code). `\dump_caps` now carries that line wherever there is a decimation: the device rate over each power of two the front end can carry, exactly the spans `L SPECTRUM_SPAN` sets.

It isn't added to `\dump_state`, because netrigctl parses that line by line and a new line would reach every client. netrigctl never parses `\dump_caps`.

Ported from sdroxide-brown (madmedicnl/sdroxide-brown#641, mine). No wire change, and no interface text.

Tested:
- Unit tests: three. They cover the line in both protocols, that every listed span sets exactly, and that there's no line without a decimation. The first fails with `spectrum_spans` emptied.
- On the station, RTL-SDR at 2.4 MS/s: `+\dump_caps` lists `75000 150000 300000 600000 1200000 2400000`, and each one, set with `L SPECTRUM_SPAN`, reads back exactly.
- From my uBITX desktop app: its bandwidth slider offers exactly those six spans.

---

## PR 3

**Branch:** `upstream-span-3`, from `span-pr3-refit.patch`

**Title:** Refit the view when the span is changed from outside

Follows #888. Before this change, a span changed over rigctl (or by another client's DEC chip) left this screen's view where it was. Narrowing already narrowed the view, but widening kept the old zoom, so the new span couldn't be seen until the operator zoomed out by hand.

The view now opens on the whole new span, wider or narrower, when the decimation changes on the same device and this screen didn't ask for it. This screen's DEC chip keeps the zoom as before:
- the chip notes what it asked for (`DecimAsks`), and a change that answers one of its asks is its own;
- two quick clicks can both be in flight;
- an ask the engine refused is forgotten after 2 s, so it can't claim a later outside change;
- a different device or rate, and the first snapshot, are left to the existing rules.

Ported from sdroxide-brown (madmedicnl/sdroxide-brown#666, mine). Interface only: no wire change, and no interface text. It doesn't depend on PR 2.

Tested:
- Unit tests: seven, in `sdroxide-ui` spectrum (140 passed). The refit test fails with `refit_on_outside_span_change` returning false.
- On the station, RTL-SDR, spans set over `nc` from 75 kHz up to 2.4 MHz: at each step the waterfall showed the whole new span, widening included.
- The DEC chip clicked in SDR Oxide keeps the zoom, as before.
- From my uBITX desktop app over rigctl: its bandwidth slider narrowing and widening SDR Oxide's span, the waterfall refitting each time.

Not tested: a remote (web) client's DEC chip as the outside change.
