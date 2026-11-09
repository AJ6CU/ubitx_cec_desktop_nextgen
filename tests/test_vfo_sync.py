"""
The SDR's VFO A/B kept with the rig's (SDRoxide / Brown over rigctl), the rig
leading; one-VFO SDRs unchanged.

    python3 test_vfo_sync.py <app folder>
"""
import os, sys, types
folder = sys.argv[1]
sys.path.insert(0, folder)
for name in ("globalvars", "sdr_launcher", "system_audio", "rest_sdr"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["rest_sdr"].RestSDR = object
sys.modules["globalvars"].config = types.SimpleNamespace()
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

try:
    import rigctl_sdr as rs
    import sdr_link as sl
    HAVE = hasattr(rs, "VFO_AB")
except Exception as e:
    print("import failed:", e); HAVE = False

class Reply:
    def __init__(self, ok, values=()): self.ok, self.values = ok, list(values)

class FakeBrown:
    """rigctl as Brown answers it: two VFOs."""
    def __init__(self, two=True):
        self.vfo, self.f = "VFOA", {"VFOA": 7074000, "VFOB": 14074000}
        self.two, self.sent = two, []
    def query(self, text, lines=1):
        t = text.split()
        if t[0] == "v":
            return Reply(True, [self.vfo]) if self.two else Reply(False)
        if t[0] == "f":
            vfo = t[1] if len(t) > 1 else self.vfo
            return Reply(True, [str(self.f[vfo])]) if (self.two or len(t) == 1) else Reply(False)
        if t[0] == "m":
            return Reply(True, ["USB", "2400"])
        return Reply(False)
    def command(self, text):
        self.sent.append(text); t = text.split()
        if t[0] == "V" and self.two:
            self.vfo = t[1]; return Reply(True)
        if t[0] == "F":
            if len(t) == 3 and self.two:
                self.f[t[1]] = int(t[2]); return Reply(True)
            if len(t) == 2:
                self.f[self.vfo] = int(t[1]); return Reply(True)
        return Reply(False)

def transport(client):
    t = rs.RigctlSDR.__new__(rs.RigctlSDR)
    t._client = client; t.profile = types.SimpleNamespace(settle_seconds=0.5)
    t._settling = {}; t.capabilities = frozenset({rs.VFO_AB}); t.active_vfo = "a"
    t.frequency = client.f["VFOA"]; t.other_vfo_hz = None
    return t

@case("transport: switching and the other VFO's frequency go as Brown's commands")
def _():
    assert HAVE, "no VFO A/B"
    c = FakeBrown(); t = transport(c)
    assert t.set_vfo("b") and c.vfo == "VFOB" and t.active_vfo == "b"
    assert t.set_vfo_frequency("a", 3573000) and c.f["VFOA"] == 3573000
    assert c.sent == ["V VFOB", "F VFOA 3573000"], c.sent

@case("transport: names read as a/b")
def _():
    assert HAVE, "no VFO A/B"
    assert [rs._vfo_letter(x) for x in ("VFOA", "Main", "VFOB", "sub", "x")] == ["a", "a", "b", "b", None]

@case("transport: a program that refuses a VFO switch drops back to one VFO")
def _():
    assert HAVE, "no VFO A/B"
    c = FakeBrown(two=False); t = transport(c)
    assert not t.set_vfo("b") and rs.VFO_AB not in t.capabilities

@case("transport: the poll reads which VFO before the frequency")
def _():
    assert HAVE, "no VFO A/B"
    import inspect
    body = inspect.getsource(rs.RigctlSDR._poll)
    assert body.index('query("v")') < body.index('query("f")'), "frequency read first"

class LaggingBrown(FakeBrown):
    """Applies "V" only after `lag` polls -- as SDRoxide was seen to."""
    def __init__(self, lag):
        super().__init__(); self.lag, self.queue = lag, []
        self.connected = True
    def command(self, text):
        self.sent.append(text); t = text.split()
        if t[0] == "V":
            self.queue.append([self.lag, t[1]]); return Reply(True)
        if t[0] == "F" and len(t) == 2:
            # As Brown: a bare F goes to the VFO active NOW (before queued
            # switches are applied).
            self.queue.append([self.lag, ("F", self.vfo, int(t[1]))]); return Reply(True)
        if t[0] == "F" and len(t) == 3:
            self.queue.append([self.lag, ("F", t[1], int(t[2]))]); return Reply(True)
        return super().command(text)
    def tick(self):
        for item in self.queue:
            item[0] -= 1
        while self.queue and self.queue[0][0] <= 0:
            _, what = self.queue.pop(0)
            if isinstance(what, tuple):
                self.f[what[1]] = what[2]
            else:
                self.vfo = what

def polled(client):
    t = transport(client)
    t._hop = None; t.mode = "USB"; t.filter_width = 2400; t._decoder_socket = None
    t._levels_found = set(); t.dsp_on = {}; t.dsp_settings = {}
    t.root = types.SimpleNamespace(after=lambda ms, f: None)
    t.on_vfo_calls, t.on_freq_calls = [], []
    t.on_vfo = t.on_vfo_calls.append; t.on_frequency = t.on_freq_calls.append
    t.on_mode = t.on_filter = lambda *a: None
    return t

@case("transport: A->B->A quickly with a lagging SDR -- its late B is not reported back")
def _():
    assert HAVE, "no VFO A/B"
    assert hasattr(rs, "VFO_SETTLE_SECONDS"), "no VFO settle window"
    c = LaggingBrown(lag=4); t = polled(c)
    t.profile.settle_seconds = 0                       # as SDRoxide's profile has
    t.set_vfo("b"); t.set_frequency(14074000)
    c.tick(); t._poll()
    t.set_vfo("a"); t.set_frequency(7074000)           # quickly back
    for _ in range(10):
        c.tick(); t._poll()
    assert t.on_vfo_calls == [], f"late VFO reported: {t.on_vfo_calls}"
    assert 14074000 not in t.on_freq_calls, f"B's frequency reported: {t.on_freq_calls}"
    assert c.vfo == "VFOA"

@case("transport: after the window, a VFO chosen in the SDR is reported")
def _():
    assert HAVE, "no VFO A/B"
    c = LaggingBrown(lag=0); t = polled(c); t.profile.settle_seconds = 0
    c.vfo = "VFOB"; t._poll()
    assert t.on_vfo_calls == ["b"], t.on_vfo_calls

@case("transport: a switch the SDR never made is sent again after the hold, not reported")
def _():
    assert HAVE, "no VFO A/B"
    assert hasattr(rs, "VFO_SETTLE_SECONDS"), "no VFO settle window"
    now = [1000.0]; real = rs.time.monotonic; rs.time.monotonic = lambda: now[0]
    try:
        c = LaggingBrown(lag=10 ** 6); t = polled(c); t.profile.settle_seconds = 0
        c.vfo = "VFOA"
        t.set_vfo("b")                                  # lost: never applied
        t._poll(); now[0] += rs.VFO_SETTLE_SECONDS + 0.1; t._poll()
        assert t.on_vfo_calls == [], t.on_vfo_calls
        assert c.sent.count("V VFOB") == 2, c.sent
    finally:
        rs.time.monotonic = real

@case("transport: the active VFO's frequency names its VFO -- a bare F would land on the old one")
def _():
    assert HAVE, "no VFO A/B"
    c = LaggingBrown(lag=3); t = polled(c); t.profile.settle_seconds = 0
    c.f = {"VFOA": 7074000, "VFOB": 14074000}
    t.set_vfo("b"); t.set_vfo_frequency("a", 7074000); t.set_frequency(14074000)
    for _ in range(6):
        c.tick()
    assert c.f == {"VFOA": 7074000, "VFOB": 14074000}, f"A overwritten: {c.f} ({c.sent})"
    assert "F VFOB 14074000" in c.sent, c.sent

# --- the link ---------------------------------------------------------------
class FakeController:
    def __init__(self, two=True):
        self.capabilities = frozenset({rs.VFO_AB} if two else set())
        self.calls = []
        self.filter_width = 2400
    def set_vfo(self, w): self.calls.append(("V", w)); return True
    def set_vfo_frequency(self, w, hz): self.calls.append(("Fo", w, hz)); return True
    def set_frequency(self, hz, band=None): self.calls.append(("F", hz)); return True
    def set_mode(self, *a): pass
    def default_filter_width(self, m): return 2400

def link(two=True):
    model = types.SimpleNamespace(vfo_a=7074000, vfo_b=14074000, rx_vfo="a", rit_offset=0,
                                  rit=False, transmitting=False, split=False)
    model.frequency = lambda w: model.vfo_a if w == "a" else model.vfo_b
    model.role_frequency = lambda r: model.frequency(model.rx_vfo)
    model.mode_of = lambda w: "USB"
    toggles = []
    rig = types.SimpleNamespace(toggle_vfo=lambda: toggles.append(1),
                                set_role_frequency=lambda r, hz: toggles.append(("rx", hz)))
    l = sl.SDR_Link.__new__(sl.SDR_Link)
    l.controller = FakeController(two); l._model = model; l._rig = rig
    l.root = types.SimpleNamespace(after=lambda ms, f: None)
    l.profile = types.SimpleNamespace(to_sdr={"USB": "USB"})
    for a in ("_sent_hz", "_sent_mode", "_sent_vfo", "_sent_other_hz", "_vfo_pending",
              "_qsy", "_rig_mode_asked", "_rit_rx_asked"):
        setattr(l, a, None)
    l._decoding = False
    l._follow_rit = lambda: None
    l._framing_for = lambda hz: None
    type(l).connected = property(lambda self: True)
    return l, model, toggles

@case("link: the SDR's active VFO and both frequencies follow the rig")
def _():
    assert HAVE, "no VFO A/B"
    l, m, _ = link(); l.follow()
    calls = l.controller.calls
    assert ("V", "a") in calls and ("Fo", "b", 14074000) in calls and ("F", 7074000) in calls, calls
    l.controller.calls.clear(); m.rx_vfo = "b"; l.follow()            # A/B on the rig
    assert l.controller.calls[:3] == [("V", "b"), ("Fo", "a", 7074000), ("F", 14074000)], l.controller.calls
    l.controller.calls.clear(); m.vfo_a = 7030000; l.follow()          # the other VFO tuned
    assert l.controller.calls == [("Fo", "a", 7030000)], l.controller.calls

@case("link: B chosen in the SDR is asked of the rig; its frequency is not a QSY")
def _():
    assert HAVE, "no VFO A/B"
    l, m, toggles = link(); l.follow(); l.controller.calls.clear()
    l._from_sdr_vfo("b")
    assert toggles == [1], toggles
    l._from_sdr_frequency(14074000)                                    # what B reads
    assert toggles == [1], "taken for a QSY"
    l.follow(); assert l.controller.calls == [], "the old VFO pushed back while pending"
    m.rx_vfo = "b"; l.follow()                                         # the rig switched
    assert l._vfo_pending is None and ("V", "b") not in l.controller.calls, l.controller.calls

@case("link: the rig does not switch -- the SDR goes back to the rig's VFO")
def _():
    assert HAVE, "no VFO A/B"
    l, m, toggles = link(); l.follow(); l.controller.calls.clear()
    l._from_sdr_vfo("b")
    target, at = l._vfo_pending; l._vfo_pending = (target, at - sl.VFO_CONFIRM_SECONDS - 1)
    l.follow()
    assert ("V", "a") in l.controller.calls, l.controller.calls

@case("link: not while transmitting -- the SDR is put back at once")
def _():
    assert HAVE, "no VFO A/B"
    l, m, toggles = link(); l.follow(); l.controller.calls.clear(); m.transmitting = True
    l._from_sdr_vfo("b")
    assert toggles == [] and ("V", "a") in l.controller.calls, (toggles, l.controller.calls)

@case("link: a one-VFO SDR (Gqrx, SDR++) only follows the receive frequency")
def _():
    assert HAVE, "no VFO A/B"
    l, m, _ = link(two=False); l.follow(); m.rx_vfo = "b"; l.follow()
    assert l.controller.calls == [("F", 7074000), ("F", 14074000)], l.controller.calls

@case("split: the firmware's swap to transmit is not followed -- the SDR stays on receive")
def _():
    assert HAVE, "no VFO A/B"
    assert hasattr(sl, "SPLIT_TX_GRACE_SECONDS"), "follows the swap"
    now = [500.0]; real = sl.monotonic; sl.monotonic = lambda: now[0]
    try:
        l, m, _ = link(); m.split = True; l.follow(); l.controller.calls.clear()
        m.rx_vfo = "b"; l.follow()                    # cv arrives first...
        now[0] += 0.1; m.transmitting = True; l.follow()   # ...then TX
        now[0] += 5; l.follow()
        assert l.controller.calls == [], f"followed the swap: {l.controller.calls}"
        m.transmitting = False; m.rx_vfo = "a"; l.follow()  # swapped back
        assert l.controller.calls == [], l.controller.calls
    finally:
        sl.monotonic = real

@case("split: a real A/B press still goes through once the grace is over")
def _():
    assert HAVE, "no VFO A/B"
    assert hasattr(sl, "SPLIT_TX_GRACE_SECONDS"), "follows the swap"
    now = [500.0]; real = sl.monotonic; sl.monotonic = lambda: now[0]
    try:
        l, m, _ = link(); m.split = True; l.follow(); l.controller.calls.clear()
        m.rx_vfo = "b"; l.follow()
        assert l.controller.calls == []
        now[0] += sl.SPLIT_TX_GRACE_SECONDS + 0.1; l.follow()
        assert ("V", "b") in l.controller.calls, l.controller.calls
    finally:
        sl.monotonic = real

@case("RIT: the SDR's RIT just after a VFO switch is its old VFO's -- not asked of the rig")
def _():
    assert HAVE, "no VFO A/B"
    assert hasattr(sl, "VFO_RIT_QUIET_SECONDS"), "SDR RIT pushed straight after a switch"
    now = [800.0]; real = sl.monotonic; sl.monotonic = lambda: now[0]
    try:
        l, m, toggles = link(); l._rit_asked = None; l._rit_rx_asked = None; l._sent_rit = 300
        m.rit = False; m.rit_base_hz = 0
        l._rig.Toggle_RIT = l._rig.toggle_rit_for_operator = lambda: toggles.append("rit")
        l.follow()                                   # first look: VFO A
        m.rx_vfo = "b"; l.follow()                   # the rig switched
        now[0] += 1; l._from_sdr_rit(300)            # Brown still shows A's +300
        assert "rit" not in toggles and l._sent_rit is None, (toggles, l._sent_rit)
        now[0] += sl.VFO_RIT_QUIET_SECONDS; l._from_sdr_rit(150)   # later: the operator's
        assert "rit" in toggles, toggles
    finally:
        sl.monotonic = real

@case("RIT: frequencies the SDR reports while a switch made in it settles are not a QSY")
def _():
    assert HAVE, "no VFO A/B"
    now = [900.0]; real = sl.monotonic; sl.monotonic = lambda: now[0]
    try:
        l, m, toggles = link(); l.follow(); l.controller.calls.clear()
        m.rit = True; m.rit_base_hz = 14074000
        l._rig.Toggle_RIT = l._rig.toggle_rit_for_operator = lambda: toggles.append("rit")
        l._from_sdr_vfo("b")                       # chosen in Brown
        m.rx_vfo = "b"; l.follow()                 # the rig switched
        now[0] += 1.0; l._from_sdr_frequency(14073800)   # Brown, late, as RIT goes back
        assert toggles == [1], f"taken for a QSY: {toggles}"
        assert l._qsy is None
    finally:
        sl.monotonic = real

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
