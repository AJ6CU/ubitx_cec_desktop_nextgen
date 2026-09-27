# SDRangel over REST — what is known

Everything here was established against a running SDRangel
(7.27.2-1315-gc43757c88, macOS, an RTL-SDR dongle), by capture and by reading
SDRangel's source where a behaviour needed explaining — not from its
documentation. Read this before changing `rest_sdr.py`, or before trusting
anything SDRangel's REST API appears to say.

What the application BUILT on these findings is in `rest_sdr.py` (the
transport) and `sdr_controls.json` (the controls' fields and ranges). How to
add another demodulator, device or program is in `ADDING_AN_SDR.md`.

---

## Contents

* [Why REST, not rigctl](#why-rest)
* [The API in brief](#api)
* [Discovery: which channel is the demodulator](#discovery)
* [Tuning is a pair](#tuning)
* [The sampled band: decimation and band framing](#band)
* [The passband: mode and filter](#passband)
* [The SSB demodulator's functions](#ssbdemod)
* [The WDSP receiver's functions](#wdsp)
* [The S-meter: Channel Power](#meter)
* [RF gain](#rfgain)
* [The Morse decoder](#morse)
* [SDRangel's windows](#windows)
* [SDRangel bugs, and the workarounds](#bugs)
* [The hardware used](#hardware)

---

<a name="why-rest"></a>
## Why REST, not rigctl

SDRangel's rigctl server was tried first and is a dead end:

* It answers `f` and `m` only. Everything else — `l ?`, `L ?`, `u ?`,
  `l STRENGTH` — returns `RPRT -4`, Hamlib's "not implemented".
* It is a FEATURE added by hand, and neither the feature nor its run state
  survives a restart of SDRangel.

REST needs nothing added, and reaches AGC, noise reduction, squelch, volume,
mute and signal strength. The `sdrangel-rigctl` entry was removed from
`sdr_programs.json`; a saved setting naming it resolves to `sdrangel`.

<a name="api"></a>
## The API in brief

Base: `http://127.0.0.1:8091/sdrangel`. `GET` reads; `PATCH` changes part of a
settings block; `POST` adds.

| Request | Answers |
| :--- | :--- |
| `GET /sdrangel` | The instance, including the device-set list |
| `GET /sdrangel/devicesets` | The device sets and their channels — polled for tuning |
| `GET .../deviceset/{n}/device/settings` | The device's settings |
| `GET .../deviceset/{n}/channel/{c}/settings` | A channel's settings |
| `GET .../deviceset/{n}/channel/{c}/report` | A channel's measurements — **never for WDSPRx**: it crashes SDRangel (see the bugs) |

**Settings blocks are named after the hardware or channel type** —
`rtlSdrSettings`, `SSBDemodSettings`, `WDSPRxSettings`, `ChannelPowerSettings`
— with `deviceHwType` or `channelType` beside them. The transport FINDS the
block (the one key ending in `Settings`) rather than looking it up, and
refuses a reply with none or several.

**PATCH bodies**, accepted as written:

    device:   {"deviceHwType": "RTLSDR", "direction": 0, "rtlSdrSettings": {...}}
    channel:  {"channelType": "WDSPRx", "direction": 0, "WDSPRxSettings": {...}}

**Some PATCHes are accepted without error and not applied.** A reply of 200
proves nothing; read back what matters. See the bugs below.

The device-set listing, as captured:

    "deviceSets": [{
        "channelcount": 3,
        "channels": [{"id": "SSBDemod", "index": 0, "direction": 0,
                      "title": "SSB Demodulator", "deltaFrequency": 0}, ...],
        "samplingDevice": {"hwType": "RTLSDR", "index": 0, "direction": 0,
                           "centerFrequency": 7000000, "bandwidth": 64000,
                           "state": "running"}
    }]

<a name="discovery"></a>
## Discovery: which channel is the demodulator

The first RECEIVING device set with a demodulator in it; in that set, the
demodulator most wanted by `DEMODULATOR_PREFERENCE` — the WDSP receiver
(`WDSPRx`) over the SSB demodulator (`SSBDemod`). A Channel Power channel is
never the demodulator; it is the S-meter's source.

A missing channel costs what that channel gives, never the connection:
without Channel Power there is no S-meter under WDSP, and nothing else is
lost. Discovery runs again when the listing changes — a channel added or
removed in SDRangel — and three seconds after connecting, because a program
still starting answers badly about itself.

<a name="tuning"></a>
## Tuning is a pair

What is heard is the device's `centerFrequency` plus the channel's
`inputFrequencyOffset`. Confirmed:

* **The listing's `deltaFrequency` IS the channel's `inputFrequencyOffset`**,
  so one `GET /devicesets` per poll gives both halves. Discovery checks the
  two agree and refuses to connect if not.
* **The listing's `bandwidth` is the sampled band**, `devSampleRate /
  2^log2Decim`: 64000 at 1.024 MS/s ÷ 16. Read on every poll, so a change in
  SDRangel is followed.
* **SDRangel's device dial shows the centre in kHz**, so a centre of
  11,000,115 reads "11000" and the 115 Hz looks lost. A retuned centre is
  rounded down to a whole kHz and the offset takes the remainder.
* **Frequency follows with the device stopped.** Nothing has to be streaming.
* The channel marker's `centerFrequency` mirrors the offset; not used.

The rule as built: the offset alone moves while the signal stays within 40%
of the band either side of the centre; beyond that the centre is retuned to
put the signal an eighth of the band above it, clear of the dongle's DC spike.

<a name="band"></a>
## The sampled band: decimation and band framing

**The band's width is the device's `log2Decim`**: width = `devSampleRate /
2^log2Decim`. A PATCH of `log2Decim` applies, and the listing's `bandwidth`
follows. This is what SDRangel's main spectrum and waterfall show — the
"Bandwidth" slider under the modes. The choices offered are the sample rate
over each power of two down to 48 kHz (the demodulators run at 48 kHz, and a
narrower band starves them): 64k, 128k, 256k, 512k and 1024k at 1.024 MS/s.

Decimation changes what the DISPLAY shows, not what is heard: the channel
filters and decimates to 48 kHz itself either way. Narrower gives a lower
noise floor in the spectrum (about 3 dB per halving), finer bins and less
CPU; wider shows more of the band.

**Band framing.** After a band change, and after a bandwidth change, the
centre goes to band start + width/2, so on 20 m the view opens at 14.000
rather than below it — never so far that the signal leaves the inner 80% of
the sampled band.

**Not the channel's span.** The channel's own spectrum is `spanLog2` (below),
a close-up of the passband; it also caps the filter, so it is left with the
filter rather than offered as a zoom.

<a name="passband"></a>
## The passband: mode and filter

There is no CW demodulator and no mode field: an SSB channel with a narrow
passband placed round the CW pitch is how CW is received, and all four of the
rig's modes live in one channel.

The passband is two fields, in Hz from the tuned frequency: `rfBandwidth`
(the "high cut"; the WDSP window calls it "far cut") and `lowCutoff` ("low
cut" / "near cut"). **The sign is the sideband**, and both carry it: USB
300–2700 is lowCutoff 300, rfBandwidth 2700; LSB is −300 and −2700. A high cut
of 0 is no passband at all. `filterIndex` 0, no filter bank.

* **On a 100 Hz grid.** The sliders step by 100 and SDRangel keeps what the
  slider can show: sent 250, it held 200; −750, −700.
* **Inside the span.** `spanLog2` sets the channel's span, 48000 / 2^spanLog2
  (6 kHz at 3) — the same for both demodulators — and the high-cut slider
  runs to the full span. Over REST SDRangel accepts a high cut beyond it
  (10.1k in a 6k span) and did not take a `spanLog2` sent to widen it, so the
  span is left to the operator and the passband kept inside it.
* **SSB demodulator: edges one at a time, then verified.** Both edges in one
  PATCH could be clamped against the OLD high cut (−250 against +2700 when
  USB becomes CWL). So the high cut goes first and the low cut after, the next
  read checks both were kept, and a change of side goes through a low cut of
  0 so that no state in between has its edges on opposite sides of zero.
* **WDSP receiver: both edges in ONE PATCH, never read back** — see its bug
  below.

<a name="ssbdemod"></a>
## The SSB demodulator's functions

The fields, ranges and conversions are in `sdr_controls.json`
(sdrangel / SSBDemod). The facts behind them:

* **AGC:** `agc` 0/1; `agcTimeLog2` 4–11, shown 16–2048 ms, stored as the
  power of two; `agcPowerThreshold` −119..0 dB; `agcThresholdGate` 0–500.
* **FFT noise reduction** (right-click NR in its window): `dnr` 0/1;
  `dnrScheme` 0 Average, 1 Avg Std Dev, 2 Peaks — **read-only over REST**, see
  the bugs. Each scheme uses one number: `dnrAboveAvgFactor` 20–99,
  `dnrSigmaFactor` 2–16, `dnrNbPeaks` 1–40, all confirmed. `dnrAlpha` is
  smoothing, NOT the dial's number: dial n (0–40) is stored as
  1 − 10^(−n/10) — the captured 0.2056717... is exactly n = 1. Tau is derived
  and shown only.
* **Volume:** `volume` is a factor, 10·log10 of it in dB; `audioMute` 0/1.
* **No notch, no squelch switch, no noise blanker, no CW peak.**

<a name="wdsp"></a>
## The WDSP receiver's functions

`WDSPRxSettings`, found by the same rule. PATCH applies to every field tried
— except the passband (below). The fields, ranges and conversions are in
`sdr_controls.json` (sdrangel / WDSPRx). Captured, by function:

    passband   rfBandwidth, lowCutoff, spanLog2, dsb -- same names as SSBDemod
    mode       demod 0 = SSB (order SSB, AM, SAM, FM)
    tuning     inputFrequencyOffset; rit, ritFrequency (-1000..1000)
    audio      volume (factor, as SSBDemod), audioMute
    AGC        agc, agcMode, agcGain ("top"), agcSlope, agcHangThreshold
    NR         dnr, nrScheme, nr2Gain, nr2NPE, nrPosition, nr2ArtifactReduction
    NB         dnb, nbScheme, nb2Mode, nbSlewTime, nbLeadTime, nbLagTime,
               nbAvgTime, nbThreshold
    notch      anf -- a switch only ("ANF")
    squelch    squelch, squelchMode, squelchThreshold, ssqlTauMute,
               ssqlTauUnmute, amsqMaxTail
    CW peak    cwPeaking, cwPeakFrequency, cwBandwidth, cwGain
    also       equalizer, eqF, eqG, fm* fields, amFadeLevel, profileIndex

**Numbering follows the dialogs' order.** Confirmed both ways — set in the
dialogs and read back, and sent by PATCH and seen in the dialogs — for:

    agcMode      0 Long, 1 Slow, 2 Medium, 3 Fast
    nrScheme     0 NR, 1 NR2
    squelchMode  0 Voice, 1 AM, 2 FM

`nbScheme` (0 NB, 1 NB2) is taken from the dialog's order, not separately
confirmed.

**Ranges**, read off the station and from SDRangel's dialog definitions:
`agcGain` −20..120; `agcSlope` dial 0–20, **stored in tenths** (dial 10 reads
back 100); `agcHangThreshold` 0–100; `squelchThreshold` 0–100 %;
`nbThreshold` 2–50; `cwPeakFrequency` 300–1000 Hz; `cwBandwidth` 20–200 Hz;
`cwGain` 1.0–10.0, a float.

`squelchThreshold` over REST confirmed on the station (61 read back 50 after
a PATCH of 50, the window's dial with it). The squelch SETTINGS dialog
(right-click SQ) holds each type's timings -- Voice: `ssqlTauMute`,
`ssqlTauUnmute` (0.1 s); AM: `amsqMaxTail` (1.50 s); FM: none -- and which
type is on, which the application sets itself by mode. The timings are left
to SDRangel's dialog: set once, not ridden.

**Automatic behaviour in CW**, done by the transport with no control: RIT
minus the CW pitch in CWU (plus in CWL), so the signal lands on the marker;
squelch type AM; ANF off (it would notch out the signal); the CW peak on the
rig's tone, clamped to 300–1000; demod SSB. Back in SSB: RIT off, squelch
type Voice.

<a name="meter"></a>
## The S-meter: Channel Power

The WDSP receiver's report cannot be read (it crashes SDRangel), so the
signal comes from a **Channel Power** channel (`ChannelPower`) in the same
device set — it only measures power, and its report is written correctly:

    GET .../channel/2/report ->
        {"ChannelPowerReport": {"channelPowerDB": -76.5, "channelPowerMaxDB": -61.7,
         "channelPowerMinDB": -150, ..., "channelSampleRate": 64000},
         "channelType": "ChannelPower"}

    ChannelPowerSettings: inputFrequencyOffset, rfBandwidth (CENTRED on the
    offset), frequencyMode 0 (offset, "delta f"), averagePeriodUS, ...

To measure what is heard it is kept on the passband: offset = demodulator
offset + RIT + sign × (low cut + high cut) / 2, bandwidth = high cut − low
cut, sign by sideband — rewritten whenever the frequency, mode or filter
changes.

**The fallback order:** Channel Power when there is one, for either
demodulator (one source, one calibration); else the SSB demodulator's own
report (`SSBDemodReport.channelPowerDB`, the same shape); else, under WDSP,
no reading. Said once in the console; never required.

<a name="rfgain"></a>
## RF gain

The device's, so described per `deviceHwType` in `sdr_controls.json`. RTLSDR,
confirmed: `rtlSdrSettings.gain` in tenths of a dB (328 = 32.8 dB, top 496 =
49.6 dB), in the R820T tuner's fixed steps; `rtlSdrSettings.agc` is the
dongle's own AGC, and while it is on the gain field does nothing — the knob is
greyed with a note saying so. A device not described has no RF gain here.

<a name="morse"></a>
## The Morse decoder

A FEATURE, not a channel (`GET /sdrangel/featureset` lists it: `"id":
"MorseDecoder"`, with its `index`), decoding a demodulator's audio with the
GGMorse library -- present in the station's build (7.27.2-1315, macOS). The
current source accepts the WDSP receiver as its audio source, as well as the
SSB, AM, NFM and WFM demodulators; it was decoding from the WDSP channel on
the station. Pitch and speed are detected automatically.

**The text reaches the application over UDP, not REST.** The feature has
settings over REST but no report: pitch, speed and its confidence ("cost")
are in its own window only. Its decoded text goes, as plain UTF-8, to
`udpAddress`:`udpPort` (default 127.0.0.1:9999) as each chunk is decoded --
about every 3 seconds -- when `udpEnabled` is on, which it is not by default.
Confirmed on the station, 2026-09-27: UDP turned on by PATCH, and the text
arrived at a listener on 127.0.0.1:9999.

    GET   /sdrangel/featureset/feature/{index}/settings
    PATCH /sdrangel/featureset/feature/{index}/settings
          {"featureType": "MorseDecoder",
           "MorseDecoderSettings": {"udpEnabled": 1}}

Other settings over REST: `udpAddress`, `udpPort`, `logEnabled`,
`logFilename`, `auto` (pitch and speed detection), `showThreshold`.

**Its audio source is an ACTION, not a setting** -- the channel chosen in
its window is not among its settings, so a PATCH cannot set it. It is chosen
by posting the channel's device set and index:

    POST /sdrangel/featureset/feature/{index}/actions
         {"featureType": "MorseDecoder",
          "MorseDecoderActions": {"deviceId": 0, "channelId": 1}}

(In the source, `webapiActionsPost` → `MsgSelectChannel`; 404 when there is
no such channel.)

**Started and stopped like a device** -- the Start button in its window:

    GET    /sdrangel/featureset/feature/{index}/run   {"state": "idle" | "running" ...}
    POST   /sdrangel/featureset/feature/{index}/run   start
    DELETE /sdrangel/featureset/feature/{index}/run   stop

Built on this: the DEC lamp (see `SDR_Link._set_decoding`,
`RestSDR.set_decoder`). On: UDP pointed at the application's own socket (a
port the system picks each time -- so the decoder's window shows a changing
port, not 9999), the source set to the demodulator the application drives,
and the feature started if it was not running. Each step is checked by
reading back, and said in one console line beginning `[sdr] CW decoder:`.
Off: its UDP settings put back, and stopped only if it was stopped before.
Confirmed at the station, 2026-09-27: decoding from the WDSP receiver, text
in the strip.

**Its window does not show what REST did.** Source, UDP box and Start button
all stay as the window last set them, though the decoder is running, sending
UDP and reading the channel chosen. (In the source, the window keeps its own
`m_selectedChannel` and nothing reports a REST choice back to it.) Worse for
the source: whenever the window rebuilds its channel list -- a channel added
or removed -- it re-applies ITS choice, which defaults to the FIRST channel
in the list. The source is not among the saved settings either, so every
SDRangel start begins on the first channel.

**So the WDSP receiver should be the first channel.** On the station it came
after an SSB demodulator, and the decoder read the SSB demodulator; with the
SSB demodulator removed, it read WDSP. The application uses WDSP when both
are present, so the SSB demodulator is not needed with it.

<a name="windows"></a>
## SDRangel's windows

Tried, and dropped in favour of documentation (2026-09-27); kept so it is not
rediscovered.

* **Possible over REST:** rolling a channel's window up to its title bar,
  through the `rollupState` in its settings — `{"version": 0,
  "childrenStates": [{"objectName": "settingsContainer", "isHidden": 1},
  ...]}`. Sections: `settingsContainer` + `spectrumContainer` (SSBDemod,
  WDSPRx); `settingsContainer` + `dataContainer` (ChannelPower). The window
  restores it whenever settings arrive, so a stale rolled-up state comes back
  on every PATCH until it is set unrolled and saved. Moving a window to
  another workspace: `PUT .../channel/{c}/workspace {"index": n}`, and
  `POST /sdrangel/workspace` to add one.
* **Not possible:** a window's hide (eye) button — Qt's plain `hide()`,
  recorded nowhere; stacking order; a window's position or size.

<a name="bugs"></a>
## SDRangel bugs, and the workarounds

All seen on 7.27.2-1315-gc43757c88, the latest build as of 2026-09-27. The
check to run after each SDRangel update, and what to remove from the
application when it passes, are in `TODO.md` under "Waiting on SDRangel".

### The WDSP receiver's report crashes SDRangel

`GET .../channel/{c}/report` on a `WDSPRx` channel crashed SDRangel outright,
losing its unsaved configuration. The cause, from its source
(plugins/channelrx/wdsprx/wdsprx.cpp): `webapiReportGet()` creates a WDSPRx
report object, but `webapiFormatChannelReport()` writes into
`response.getSsbDemodReport()` — the SSB demodulator's report, never created
for this channel. A null pointer. A copy-paste slip: `getSsbDemodReport`
should be `getWdspRxReport`.
**Workaround:** never read it (`REPORT_UNSAFE`); the S-meter comes from
Channel Power. *Not yet reported upstream.*

### The WDSP receiver's passband is write-only over REST

USB ↔ LSB never reached the WDSP receiver: every read-back showed
rfBandwidth 3000, lowCutoff 600, whatever was sent or set at SDRangel's own
knobs — even with LSB dragged in its window. SDRangel's debug log shows why. A
PATCH is built from the channel's STORED settings plus the fields sent, and
the stored copy's cutoffs never take a change (`WDSPRx::applySettings` logs an
empty string for both). One field per PATCH, each undid the other:

    PATCH rfBandwidth -3000  ->  WDSPRxGUI::applyBandwidths  bw: -30  lw: 6
    PATCH lowCutoff    -600  ->  WDSPRxGUI::applyBandwidths  bw:  30  lw: -6

A positive passband only seemed to work because the stale copy was USB
already. **Workaround** (`STALE_PASSBAND_CHANNELS`): both cutoffs in one
PATCH; no read-back check, and the poll reads no passband from a WDSP channel
(it would report a mode change nobody made); every other PATCH to the channel
carries the passband last written, or the window reverts on any AGC, RIT or
volume change. Confirmed on the station, 2026-09-27: USB ↔ LSB moves the far
cut, wide and narrow keep the sideband, and AGC or RIT no longer make the
window's filter jump. Cost: moves of SDRangel's own filter knobs cannot be followed.
The same log shows the far cut allowed to 6000 Hz at spanLog2 3 (`bwMax 60`),
which is how the WDSP span was found to be the same as the SSB demodulator's
— an earlier "3400 sent, 3000 held" was this stale read-back, not a limit.
*Report text: sdrangel_wdsp_cutoff_report.txt.*

### The SSB demodulator's noise-reduction scheme is ignored over REST

A PATCH of `dnrScheme` 2 is accepted, reads back 0, and the NR dialog stays
on Average. The log:

    WebAPIRequestMapper::getChannelSettings: ... channelSettingsKeys: QList("dnrScheme")
    SSBDemod::webapiSettingsPutPatch: forward to GUI
    SSBDemod::applySettings: " m_dnrScheme: 0"
    SSBDemodGUI::handleMessage: SSBDemod::MsgConfigureSSBDemod

The key is recognised, but the value sent never reaches the settings — most
likely a missing line where REST fields are copied in.
**Workaround:** the scheme is shown, not set (`"read_only": true` in
`sdr_controls.json`). *Report text: sdrangel_dnrScheme_report.txt.*

### The SSB demodulator's window ignores clicks after the NR dialog (GUI only)

Right-click NR, close the dialog, and the window then ignores ordinary clicks,
checkboxes and scrolling, though its knobs still turn. Another right click,
released outside the demodulator, restores it. No REST involved, and changes
this application sends still apply. Nothing in the application to change.
*Report text: sdrangel_nr_dialog_click_report.txt.*

<a name="hardware"></a>
## The hardware used

A generic Realtek dongle (`RTL2838UHIDIR`, R820T tuner), not an RTL-SDR Blog
V3, at 1.024 MS/s. The API behaves the same whether it hears anything or not,
and `channelPowerDB` −150 is a perfectly good test value. Findings that need a
real signal — the CW pitch landing on the marker, the S-meter's calibration —
are marked as such in `TODO.md`.
