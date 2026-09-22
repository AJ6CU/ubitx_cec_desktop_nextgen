#!/usr/bin/python3
"""
Profiles of the rigctl-speaking programs this application can drive.

WHY PROFILES AND DISCOVERY BOTH

What a server can do is found out at connect time where it is safe to ask
-- see RigctlSDR.discover(). But asking has limits: only READING can be tried
freely (trying to set the volume would set it), and a server can answer a
read with a value it does not really measure. So each program also has a
profile of what is KNOWN about it: how it names modes, how it is started and
stopped, and what it is known not to do, so that is never asked at all.

Discovery then refines the profile for the version actually running. It
matters: in some SDR++ versions setting a mode together with a filter width
always fails, through a parsing bug, while in others it works.

ADDING A PROGRAM

A new Profile below, and an entry in PROFILES. If it answers "l ?" with the
levels it supports, as Gqrx and a standard rigctld do, say so and discovery
takes its word for them; otherwise each level is tried once.
"""

# What an SDR can be asked to do. The interface greys out what is missing.
FREQUENCY = "frequency"
MODE = "mode"
FILTER = "filter"        # a filter width alongside the mode
SIGNAL = "signal"        # signal strength, for the S-meter and the scanner
VOLUME = "volume"        # its own audio level
SQUELCH = "squelch"
MUTE = "mute"

# A "CW" from an SDR with no sideband of its own: the application has to
# choose one -- see SDR_Link._from_sdr_mode.
CW_EITHER = object()


class Profile:
    """What is known about one rigctl-speaking program."""

    def __init__(self, key, name, default_port, to_sdr, from_sdr,
                 start=None, stop=None, known_missing=(), known_present=(),
                 self_describing=False, volume_range=None,
                 squelch_range=None, squelch_unit=""):
        """
        Args:
            key: How the "SDR Software" setting names it.
            name: For display.
            default_port: Where it usually listens.
            to_sdr: rig mode -> the program's mode name.
            from_sdr: the program's mode name -> rig mode, or CW_EITHER.
                Modes left out -- AM, FM and the rest -- are ones the rig
                cannot use, and are not passed on.
            start, stop: commands that start and stop its receiver, if any.
            known_missing: capabilities it is known NOT to have. They are
                never probed: asking cannot show them, and could mislead.
            known_present: capabilities its documentation says it HAS. Taken
                on trust, not probed -- a probe can fail for reasons that
                have nothing to do with whether the feature exists. Gqrx
                reports a filter width of 0 until its filter has been set,
                so the filter test, which sends back the reported width, had
                nothing to send and marked a working filter as missing.
            self_describing: answers "l ?" and "L ?" with the levels it can
                read and set.
            volume_range: (bottom, top) of its audio level "AF", which the
                application's 0-100 slider is spread across evenly. Programs
                differ: Gqrx's is in decibels, -80 to +50, measured against a
                running Gqrx; a standard rigctld's is 0 to 1.
            squelch_range, squelch_unit: the same for its squelch threshold
                "SQL", which the slider shows in the program's own units --
                dBFS for Gqrx, so the setting reads as Gqrx shows it.
        """
        self.key = key
        self.name = name
        self.default_port = default_port
        self.to_sdr = dict(to_sdr)
        self.from_sdr = dict(from_sdr)
        self.start = start
        self.stop = stop
        self.known_missing = frozenset(known_missing)
        self.known_present = frozenset(known_present)
        self.self_describing = self_describing
        self.volume_range = volume_range
        self.squelch_range = squelch_range
        self.squelch_unit = squelch_unit


SDRPP = Profile(
    "sdr++", "SDR++", 4532,
    # SDR++ has a single CW mode.
    to_sdr={"LSB": "LSB", "USB": "USB", "CWL": "CW", "CWU": "CW"},
    from_sdr={"LSB": "LSB", "USB": "USB", "CW": CW_EITHER},
    start="\\start", stop="\\stop",
    # Confirmed against a running SDR++: "l ?" and "l STRENGTH" are refused.
    # Its rigctl server has no audio level, squelch or mute either.
    known_missing=(SIGNAL, VOLUME, SQUELCH, MUTE),
    self_describing=False,
)

GQRX = Profile(
    "gqrx", "Gqrx", 7356,
    # Gqrx has a CW mode for each sideband, so the rig's is passed as it is.
    to_sdr={"LSB": "LSB", "USB": "USB", "CWL": "CWL", "CWU": "CWU"},
    from_sdr={"LSB": "LSB", "USB": "USB", "CWL": "CWL", "CWU": "CWU",
              "CW": CW_EITHER},
    # Starts and stops its DSP -- the receiver itself.
    start="U DSP 1", stop="U DSP 0",
    # Documented: M takes a filter width ("M USB 2400"). Not probed -- see
    # known_present.
    known_present=(FILTER,),
    self_describing=True,
    volume_range=(-80.0, 50.0),
    # Believed to match Gqrx's own squelch control; to be confirmed by
    # reading "l SQL" at both ends of it, as the audio range was.
    squelch_range=(-150.0, 0.0), squelch_unit="dBFS",
)

RIGCTLD = Profile(
    "rigctld", "rigctld (Hamlib)", 4532,
    # Hamlib's names: CW is the upper sideband, CWR the reverse.
    to_sdr={"LSB": "LSB", "USB": "USB", "CWL": "CWR", "CWU": "CW"},
    from_sdr={"LSB": "LSB", "USB": "USB", "CW": "CWU", "CWR": "CWL"},
    self_describing=True,
    volume_range=(0.0, 1.0),
    squelch_range=(0.0, 1.0),
)

PROFILES = {"sdr++": SDRPP, "sdrpp": SDRPP, "gqrx": GQRX,
            "rigctld": RIGCTLD, "hamlib": RIGCTLD}


def profile_for(setting):
    """
    The profile the "SDR Software" setting names -- SDR++ if it names none
    this application knows, since that is what it has always driven.
    """
    return PROFILES.get(str(setting or "").strip().lower(), SDRPP)
