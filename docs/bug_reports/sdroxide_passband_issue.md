**Title:** Hamlib server: let `M` change the passband when the mode stays the same (and add SQL/AGC)

**Version:** v1.6.8 (macOS .dmg), and the same code on `main` at 807b0fc. Hamlib server on port 4532.

**What happens**

`set_mode` in `crates/sdroxide-rigctld/src/proto.rs` treats a request for the mode already reported as a no-op, so WSJT-X re-sending `PKTUSB` doesn't restart a decoder. That makes sense, but the passband is dropped with it. `M USB 2400` while in USB replies `RPRT 0` and leaves the filter at 2700. The same happens in CW: `M CW 500` while in CW keeps the old width.

So a controlling program can only change the filter by going through another mode, `M LSB 2400` then `M USB 2400`. That in turn runs into two other behaviours:
- SDRoxide's per-mode memory loads the other mode's NB/NR/notch on the way through.
- Set commands are queued, so the second `M` can arrive while the reported mode is still the first. It is then dropped as a no-op, and the rig is left in the other mode.

**Request:** in `set_mode`, when the mode matches but a passband greater than 0 is given and differs from the current one, push `SetFilter` alone. WSJT-X re-sends the passband it read, so it would still be a no-op for WSJT-X.

Something like:

```rust
if name.eq_ignore_ascii_case(to_hamlib_mode(st.mode)) {
    if let Some(w) = args.get(1).and_then(|s| s.parse::<i32>().ok())
        && w > 0 && w != st.passband_hz()
    {
        let (lo, hi) = filter_for(st.mode, w);
        cmds.push(Command::SetFilter { rx: RxId::Main, lo, hi });
    }
    return out.finish(OK, false);
}
```

**To reproduce** (in USB, 2700):

```
$ printf 'M USB 2400\n' | nc -w 1 127.0.0.1 4532 ; sleep 2 ; printf 'm\n' | nc -w 1 127.0.0.1 4532
RPRT 0
USB
2700
```

**Also requested:** `SQL` and `AGC` levels. Both are in SDRoxide's window, and the engine already has `SetSquelch` and `SetAgc`, but `get_level`/`set_level` answer `RPRT -11` for them. Hamlib's `SQL` (0–1) and `AGC` (0 off, 2 fast, 3 slow, 5 medium) in `LEVEL_GET`/`LEVEL_SET` would let a controlling program show and set them.

**Use case:** a desktop controller that keeps SDRoxide in step with a uBITX transceiver over rigctl. Frequency, mode, AF, MUTE, NB/NR/ANF and STRENGTH all work well. Thanks for SDRoxide.
