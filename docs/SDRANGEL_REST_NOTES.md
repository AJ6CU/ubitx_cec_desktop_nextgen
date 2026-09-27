# SDRangel over REST — starting notes

Everything below was established by hand against a running SDRangel, not read
from documentation. Start here rather than rediscovering it.

## The task

A second SDR transport, beside `RigctlSDR`, speaking SDRangel's REST API.
**First step: frequency, both ways** — the rig moves, SDRangel follows; a
click in SDRangel moves the rig. Everything else after that.

## Why REST at all

SDRangel's rigctl server was tried first and is a dead end:

* It answers `f` and `m`. Everything else — `l ?`, `L ?`, `u ?`,
  `l STRENGTH` — returns `RPRT -4`, Hamlib's "not implemented", twice per
  command.
* Its rigctl server is a FEATURE that must be added by hand, and **neither
  the feature nor its run state is restored when SDRangel restarts** — so it
  cannot be relied on at all. (Starting it automatically would need the REST
  API, which makes rigctl pointless.)
* The entry `sdrangel-rigctl` was removed from `sdr_programs.json` once REST
  worked -- a second, lesser way in that cannot be relied on is not worth
  offering. A saved setting naming it resolves to `sdrangel`.

REST needs no feature added, and reaches AGC, noise reduction, squelch,
volume, mute and signal strength.

## What the API actually returns

Base: `http://127.0.0.1:8091/sdrangel`

**`GET /sdrangel`** — instance summary, including `devicesetlist`. This is
DISCOVERY: it lists device sets, and the channels in each, with `id`,
`index`, `title`. Observed:

    "deviceSets": [{
        "channelcount": 1,
        "channels": [{"id": "SSBDemod", "index": 0, "direction": 0,
                      "title": "SSB Demodulator", "deltaFrequency": 0}],
        "samplingDevice": {"hwType": "RTLSDR", "index": 0, "direction": 0,
                           "centerFrequency": 435000000, "bandwidth": 64000,
                           "state": "running"}
    }]

**`GET /sdrangel/devicesets`** — the same list on its own.

**`GET /sdrangel/deviceset/0/channel/0/settings`** — everything about the
demodulator. The interesting keys, all under a block named after the channel
type (`SSBDemodSettings`):

    agc, agcPowerThreshold, agcClamping, agcTimeLog2, agcThresholdGate
    dnr, dnrScheme, dnrAboveAvgFactor, dnrAlpha, dnrNbPeaks, dnrSigmaFactor
    audioMute, volume
    rfBandwidth, lowCutoff, filterIndex, dsb
    inputFrequencyOffset
    title, streamIndex, useReverseAPI, reverseAPIAddress, reverseAPIPort

**`GET /sdrangel/deviceset/0/channel/0/report`** —

    {"SSBDemodReport": {"channelPowerDB": -150}, "channelType": "SSBDemod"}

`channelPowerDB` is the S-meter and the scanner's stop-on-signal.

**`GET /sdrangel/deviceset/0/device/settings`** — the device. NOTE THE KEY IS
NAMED AFTER THE HARDWARE (`rtlSdrSettings`), with `deviceHwType` alongside
saying which:

    "deviceHwType": "RTLSDR",
    "rtlSdrSettings": {"centerFrequency": 435000000, "devSampleRate": 1024000,
                       "log2Decim": 4, "gain": 0, "agc": 0, "biasTee": 0,
                       "noModMode": 0, "offsetTuning": 0,
                       "transverterMode": 0, "transverterDeltaFrequency": 0,
                       "rfBandwidth": 2500000, "dcBlock": 1, ...}

`PATCH` is the verb for a partial settings change; `POST` adds a channel.

## The three problems to solve

**1. Tuning is a pair.** What you hear is the device's `centerFrequency` plus
the channel's `inputFrequencyOffset`. A small move should nudge the offset; a
larger one must retune the centre. The limit is the sampled band --
`devSampleRate` divided by `2^log2Decim` here gives 64 kHz of usable width --
so the sample rate decides the rule. SDRangel's own rigctl server does the
same thing with a "maximum frequency offset", 10 kHz by default.

**2. The device settings block is hardware-specific.** `rtlSdrSettings` for
this dongle, something else for another. Read `deviceHwType` and use the
matching key; do not hardcode one shape.

**3. Mode is the channel TYPE, not a field.** There is no CW demodulator:
`SSBDemod` with a narrow, sign-carrying `rfBandwidth` is how CW is received
(negative for lower sideband). So "set CWL" means SSB, negative bandwidth,
narrow -- and if the channel present is the wrong type (an AM demodulator,
say) it means adding or replacing a channel. Nothing like rigctl's
`M USB 2400`.

## Where it fits in the existing code

* `sdr_programs.json` — add an entry, `sdrangel`, with `"protocol": "rest"`
  and port 8091, beside the existing `sdrangel-rigctl`. One entry per WAY of
  driving a program.
* `sdr_link.py` — `_transport_for()` already chooses the transport class by
  that protocol and refuses politely for one it cannot drive. That is the
  only place that needs to know the new class exists.
* The new transport must offer what `SDR_Link` already calls on
  `RigctlSDR`: `is_connected`, `capabilities`, `connect`, `disconnect`,
  `start`, `stop`, `set_frequency`, `set_mode`, `set_filter_width`,
  `set_level`, `get_level`, `set_mute`, `default_filter_width`, the
  `frequency`/`mode`/`filter_width`/`signal`/`volume`/`muted`/`squelch`
  attributes, and the `on_*` callbacks. Match that shape and nothing above
  changes.
* Capability names come from `sdr_programs.py`: frequency, mode, filter,
  signal, volume, squelch, mute.

## Rules that already bit us, and will again

* **Nothing in a transport opens a window.** Questions go upward through
  callbacks -- `SDR_Link` has two for closing programs.
* **Blocking waits are on the interface thread.** `RigctlClient` waits half a
  second; HTTP will be slower and needs deciding before, not after.
* **A program still starting answers badly about itself.** Discovery is asked
  again three seconds after connecting, for that reason.
* **Ask, do not kill** — and launch as an application, or there is nothing to
  ask. See `ARCHITECTURE.md`, "Starting an SDR, and whose it is".

## Confirmed against the running SDRangel -- step 1, frequency

* **The listing's `deltaFrequency` IS the channel's `inputFrequencyOffset`.**
  So one `GET /sdrangel/devicesets` per poll gives both halves of the tuning
  pair. Discovery still checks the two agree, and refuses to connect if not.
* **The PATCH bodies are accepted as written:**
  `{"deviceHwType", "direction", "<hwKey>": {"centerFrequency"}}` for the
  device, `{"channelType", "direction", "SSBDemodSettings":
  {"inputFrequencyOffset"}}` for the channel. The settings key is FOUND --
  the one key ending in `Settings` -- not looked up in a table.
* **The listing's `bandwidth` is the decimated band,** `devSampleRate / 2^log2Decim`:
  64000 at 1.024 MS/s, 125000 at 2 MS/s. The tuning rule reads it on every
  poll, so changing the sample rate in SDRangel is followed.
* **SDRangel's device dial shows the centre in kHz.** A centre of 11,000,115
  reads "11000" and the 115 Hz looks lost. So a retuned centre is rounded
  down to a whole kHz and the offset takes the remainder, and a centre left
  off a whole kHz is retuned once. Dial plus offset then reads true.
* **The tuning rule as built:** the offset alone moves within 40% of the band
  either side of the centre; beyond that the centre is retuned to put the
  signal an eighth of the band above it, clear of the DC spike. Offsets go
  negative, and that is expected.
* **Frequency follows with the device stopped** (`"state": "idle"`). Nothing
  has to be streaming for the pair to be set and read.
* **The channel's `channelMarker.centerFrequency` mirrors the offset.** Not
  used; noted so it is not mistaken for something else.

Found on the way, and NOT an SDR problem: a fast dial spin overran the
Nano and the rig tuned itself to 4.29 GHz. Fixed in `ubitx_link.py` -- see
`ARCHITECTURE.md`, "Receive writes are paced by the rig's own report".

## The hardware, for context

The dongle in use reports as a generic Realtek (`RTL2838UHIDIR`, R820T), not
an RTL-SDR Blog V3, and has no forced direct sampling in its EEPROM -- so it
probably cannot hear HF. That does not matter for building any of this: the
API behaves the same whether the dongle hears anything or not, and
`channelPowerDB` of -150 is a perfectly good test value. A known-good V3 can
confirm at the end that rig and SDR land on the same signal.

## Files to bring

`sdr_link.py`, `rigctl_sdr.py`, `sdr_programs.py`, `sdr_programs.json`,
`sdr_launcher.py`, `ubitx_cec_desktop.py`, `ARCHITECTURE.md`, `TODO.md`.

### Mode and filter (captured on the station)

The SSB demodulator's passband is two fields, in Hz from the tuned frequency:
`rfBandwidth` (the "high cut" knob, scale LSB to 0 to USB) and `lowCutoff`
("low cut"). The SIGN is the sideband, and both carry it: USB 0-3000 is
lowCutoff 0, rfBandwidth 3000; LSB is lowCutoff -300, rfBandwidth -2700 for
300-2700. Dragging the high cut to 0 gives rfBandwidth 0 -- no passband --
and the spectrum's `usb` flag reads 0 there. `filterIndex` 0, no filter bank.

`spanLog2` is separate and unchanged by the passband: span = 48000 / 2^spanLog2
(6k at 3, read off the knob). The high-cut slider runs to the FULL span (it
stops at 6k in a 6k span) -- not half, as first assumed.

Over REST SDRangel does not enforce that: a high cut of 10.1k was accepted in
a 6k span, the slider simply pinned at its end. And a `spanLog2` sent to widen
the span did not take (sent with the high cut, in one PATCH; not tried alone).
So RestSDR leaves the span to the operator and keeps the passband inside it.

The cuts are on a 100 Hz grid: the sliders step by 100, and what the slider
can show is what SDRangel keeps -- sent 250, it held 200; -750, -700.

### AGC and noise reduction (read off the station)

Demodulator AGC: `agc` 0/1; `agcTimeLog2` 4-11 (dial 16-2048 ms, stored as
the power of two); `agcPowerThreshold` -119..0 dB; `agcThresholdGate` 0-500.

FFT noise reduction, opened by right click on NR in the SSB demodulator:
`dnr` 0/1; `dnrScheme` picks the method -- READ-ONLY over REST: a PATCH to 2
is accepted without error, reads back 0, and the NR dialog stays on Average.
It is chosen in the dialog only. SDRangel's log (7.27.2-1315-gc43757c88) shows
why -- an SDRangel bug, not the window overwriting it:

    WebAPIRequestMapper::getChannelSettings: ... channelSettingsKeys: QList("dnrScheme")
    SSBDemod::webapiSettingsPutPatch: forward to GUI
    SSBDemod::applySettings: " m_dnrScheme: 0"
    SSBDemodGUI::handleMessage: SSBDemod::MsgConfigureSSBDemod

The key is recognised as changed, but the value sent (2) is never copied into
the settings: applySettings runs with the old 0, before the GUI hears of it.
Most likely a missing dnrScheme line where the SSB demodulator copies REST
fields into its settings. Worth reporting upstream. The method -- 0 Average uses
`dnrAboveAvgFactor` (20-99), 1 Avg Std Dev uses `dnrSigmaFactor` (2-16), and
2 Peaks `dnrNbPeaks` (1-40); all three numbers confirmed on the station. `dnrAlpha` is the
smoothing factor, NOT the dial's number: dial position n (0-40; 0 is no
smoothing, shown with Tau 0.000) is stored as
1 - 10^(-n/10) -- captured 0.2056717... is exactly n = 1. Tau (0.027-426.575)
is derived from it and shown only.

The SSB demodulator has no notch.

### Gotcha: SDRangel's own window after the NR dialog (not REST)

Right-click NR in the SSB demodulator to open its noise reduction dialog,
close the dialog, and the demodulator's window then ignores ordinary clicks,
checkboxes and scrolling -- AGC and NR do not change state -- though its
knobs still turn. Another right click, released outside the demodulator,
restores it. Seen on 7.27.2-1315-gc43757c88.

Pure SDRangel GUI behaviour: no REST involved, and changes this application
sends still apply while the window is stuck. Looks like the window still
waiting for the release of the right click that opened the dialog (the
release went to the dialog). Reported separately from the dnrScheme bug.

### WDSP receiver: reading its report CRASHES SDRangel

`GET /sdrangel/deviceset/0/channel/1/report` on a WDSP receiver (`WDSPRx`)
channel crashed SDRangel outright, losing its unsaved configuration -- seen on
7.27.2-1315-gc43757c88, 2026-09-27. The same read on the SSB demodulator is
safe; this application makes it five times a second for the S-meter.

So a WDSPRx channel must NOT have its report polled until this is understood:
the signal level has to come from somewhere else, or the crash has to be
fixed upstream. Not yet reported to SDRangel.

### WDSP receiver: its settings (first capture, 2026-09-27)

`GET .../channel/1/settings` -- safe -- answers a `WDSPRxSettings` block,
`channelType` "WDSPRx". Found by the same "...Settings" key rule as the SSB
demodulator. Fields by function (values as captured, defaults untouched):

    passband   rfBandwidth 3000, lowCutoff 300, spanLog2 3, dsb 0 --
               SAME NAMES as the SSB demodulator (sign = sideband, per readme)
    mode       demod 0 (SSB; readme order SSB, AM, SAM, FM -- unconfirmed)
    tuning     inputFrequencyOffset 0; rit 0, ritFrequency 0
    audio      volume 25.118864 (= 14 dB on 10 log10, as SSBDemod), audioMute 0
    AGC        agc 0, agcMode 2, agcGain 80 ("top"), agcSlope 35,
               agcHangThreshold 0
    NR         dnr 0, nrScheme 0, nr2Gain 2, nr2NPE 0, nrPosition 0,
               nr2ArtifactReduction 1
    NB         dnb 0, nbScheme 0, nb2Mode 0, nbSlewTime, nbLeadTime,
               nbLagTime, nbAvgTime 50, nbThreshold 30
    notch      anf 0 -- a switch only
    squelch    squelch 0, squelchMode 0, squelchThreshold 3, ssqlTauMute,
               ssqlTauUnmute, amsqMaxTail 1.5
    CW peak    cwPeaking 0, cwPeakFrequency 600, cwBandwidth 100, cwGain 2
    also       equalizer/eqF/eqG, fm* fields, amFadeLevel, profileIndex

In the device-set listing it is `"id": "WDSPRx"` beside `"SSBDemod"`, each
with its own `index` and `deltaFrequency` -- no signal level there, so the
listing is no substitute for the report. Discovery (`_locate`) takes the FIRST
receiving channel, so with the SSB demodulator at index 0 the application
keeps driving it; supporting WDSP means choosing between the two by `id`.

PATCH APPLIES -- unlike the SSB demodulator's dnrScheme. On the station
(2026-09-27), one PATCH of agcMode 3, nrScheme 1, squelchMode 2 and anf 1
read back exactly as sent, and the WDSP window followed: AGC Fast, NR2,
squelch FM, ANF on. So the numbering follows the dialogs' order:

    agcMode      0 Long, 1 Slow, 2 Medium, 3 Fast    (0 and 3 confirmed)
    nrScheme     0 NR (LMS), 1 NR2 (spectral)        (1 confirmed)
    squelchMode  0 Voice, 1 AM, 2 FM                 (1 and 2 confirmed)

Confirmed from both directions: set in the dialogs (Long, NR2, AM) and read
back as 0, 1, 1; sent by PATCH (3, 1, 2) and shown in the dialogs as Fast,
NR2, FM. The rest follow from the dialogs' order.

Dial ranges, read off on the station:

    agcGain            -20 .. 120      (captured 80)
    agcSlope           dial 0 .. 20, STORED IN TENTHS: 0 .. 200 (dial 10
                                        read back 100, on the station; the
                                        captured 35 is 3.5 on the dial)
    agcHangThreshold   0 .. 100        (captured 0)
    squelchThreshold   0 .. 100        (captured 3 -- a percentage)

Still wanted: a signal-level source that is not the report.

### Why the WDSP report crashes -- and the Channel Power workaround

THE CAUSE, from SDRangel's source (plugins/channelrx/wdsprx/wdsprx.cpp, still
so on master, 2026-09-27): webapiReportGet() creates a WDSPRx report object,
but webapiFormatChannelReport() writes the power, squelch and sample rates
into response.getSsbDemodReport() -- the SSB DEMODULATOR's report, never
created for this channel. A null pointer; the first write crashes SDRangel.
A copy-paste slip: getSsbDemodReport should be getWdspRxReport on each line.
The measurement itself (getMagSqLevels) is there. To report upstream.

THE WORKAROUND: SDRangel's Channel Power channel (`ChannelPower`), which only
measures power, and whose report code is written correctly. Added as channel
2 on the station; both reads safe:

    GET .../channel/2/report ->
        {"ChannelPowerReport": {"channelPowerDB": -76.5, "channelPowerMaxDB":
         -61.7, "channelPowerMinDB": -150, "channelPowerPulseDB": -150,
         "channelSampleRate": 64000}, "channelType": "ChannelPower"}

    GET .../channel/2/settings -> "ChannelPowerSettings":
        inputFrequencyOffset 0, rfBandwidth 10000, frequencyMode 0 (offset,
        "delta f"), frequency 0, averagePeriodUS 100000, pulseThreshold -50

`channelPowerDB` in a block ending "Report" -- the same shape the SSB
demodulator's report has, so the application's existing report reader takes
it unchanged. To measure what is heard, it must cover the WDSP passband: its
bandwidth is CENTRED on its offset, so offset = WDSP offset + sign x
(low cut + high cut) / 2 and bandwidth = high cut - low cut, sign by
sideband. Kept in step whenever the WDSP receiver is tuned or its filter
changes. Unneeded once the WDSP report is fixed.

### Built on this (2026-09-27)

rest_sdr.py now holds a DSP table per channel type (`CHANNEL_DSP`): each
function's switch field and each adjustment's field, range, knob kind and
conversion, all from the captures and dial ranges above. Discovery prefers
`WDSPRx` over `SSBDemod` (`DEMODULATOR_PREFERENCE`), never picks
`ChannelPower` as the demodulator, and never reads a report of a channel in
`REPORT_UNSAFE`. In CW on the WDSP receiver it sets rit/ritFrequency (minus
the pitch in CWU, plus in CWL), squelchMode 1, anf 0, cwPeakFrequency (the
rig's tone, 300-1000) and demod 0; in SSB, rit 0 and squelchMode 0. Channel
Power is kept at offset + RIT + sign x (low + high) / 2, rfBandwidth = high
- low, frequencyMode 0.

WDSP SPAN (station, 2026-09-27): its SSB span is 24000 / 2^spanLog2 -- HALF
the SSB demodulator's -- so 3 kHz at spanLog2 3: a high cut of 3400 sent was
held at 3000. rest_sdr.SPAN_BASE_BY_CHANNEL. Widen the span in SDRangel's
WDSP window for a wider SSB filter.

## WDSP receiver: the passband is write-only over REST (2026-09-27)

SDRangel 7.27.2-1315. USB <-> LSB never reached the WDSP receiver: every
read-back showed rfBandwidth 3000, lowCutoff 600, whatever was sent or set at
SDRangel's own knobs -- even with LSB dragged in its window, where only the
spectrum's "usb" flag changed.

The debug log shows why. A PATCH is built from the channel's STORED settings
plus the fields sent, and the stored copy's cutoffs never take a change --
"WDSPRx::applySettings" logs an empty string for lowCutoff and rfBandwidth
patches. So, one field per PATCH:

    PATCH rfBandwidth -3000  ->  WDSPRxGUI::applyBandwidths  bw: -30  lw: 6
    PATCH lowCutoff    -600  ->  WDSPRxGUI::applyBandwidths  bw:  30  lw: -6

each undoing the last. A positive passband (LSB to USB) seemed to work only
because the stale copy was USB already.

Built on this (rest_sdr.STALE_PASSBAND_CHANNELS):
- both cutoffs in ONE PATCH;
- no read-back check, and the poll reads no passband from a WDSP channel;
- every other PATCH to it carries the passband last written, or SDRangel's
  window reverts to the stale one on any AGC, RIT or volume change;
- SDRangel's own filter knobs cannot be followed.

The same log shows the WDSP far cut allowed to 6000 Hz at spanLog2 3
(bwMax 60): its span base is 48 kHz, like the SSB demodulator's. The earlier
"3400 sent, 3000 held" was this stale read-back, not a limit.

Present in the latest build (7.27.2-1315, checked 2026-09-27). Report text:
sdrangel_wdsp_cutoff_report.txt; the check to run after each update, and
what to remove when it passes, are in TODO.md under "Waiting on SDRangel".

## WDSP receiver: changing sideband (2026-09-27) -- SUPERSEDED by the above

At the station, USB <-> LSB left the WDSP receiver's high cut -- "far cut" in
its dialog -- where it was. With high cut first, low cut second, the first
PATCH asks for a passband with its edges on opposite sides of zero (-2900
against a low cut still at +300), which SDRangel corrects. A change of side
now goes through a low cut of 0: lowCutoff 0, then rfBandwidth, then
lowCutoff -- every state in between has both edges on one side. Tested
against a stand-in that puts the far cut back and clamps the near cut to 0,
which reproduces the fault with the old order. *To confirm at the station.*

