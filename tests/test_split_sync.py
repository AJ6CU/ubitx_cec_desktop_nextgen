"""
Split follows both ways between the rig and an SDR with VFO A/B (Brown):
turned on in the SDR, it is asked of the rig, which leads; the rig's split
is given the SDR.

    python3 test_split_sync.py <app folder>
"""
import os, sys, types
folder = sys.argv[1]
sys.path.insert(0, folder)
for name in ("globalvars", "sdr_launcher", "system_audio", "rest_sdr"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["rest_sdr"].RestSDR = object
sys.modules["globalvars"].config = types.SimpleNamespace()
import rigctl_sdr as rs
import sdr_link as sl
import sdr_programs as sp
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

class Reply:
    def __init__(self, ok, values=()): self.ok, self.values = ok, list(values)

class Brown:
    def __init__(self):
        self.vfo, self.f, self.split, self.sent, self.connected = "VFOA", {"VFOA": 7094000, "VFOB": 7096000}, 0, [], True
    def query(self, text, lines=1):
        t = text.split()
        if t[0] == "v": return Reply(True, [self.vfo])
        if t[0] == "f": return Reply(True, [str(self.f[t[1] if len(t) > 1 else self.vfo])])
        if t[0] == "m": return Reply(True, ["USB", "2400"])
        if t[0] == "s": return Reply(True, [str(self.split), "VFOB" if self.vfo == "VFOA" else "VFOA"])
        return Reply(False)
    def command(self, text):
        self.sent.append(text)
        if text.startswith("S "): self.split = int(text.split()[1])
        return Reply(True)

def transport(c):
    t = rs.RigctlSDR.__new__(rs.RigctlSDR)
    t._client = c; t.profile = types.SimpleNamespace(settle_seconds=1.0)
    t._settling = {}; t.capabilities = frozenset({rs.VFO_AB, sp.SPLIT}); t.active_vfo = "a"
    t.frequency, t.other_vfo_hz = 7094000, 7096000
    t._hop = None; t.mode = "USB"; t.filter_width = 2400; t._decoder_socket = None
    t._levels_found = set(); t.dsp_on = {}; t.dsp_settings = {}
    t.split, t.split_vfo = False, "VFOB"
    t.root = types.SimpleNamespace(after=lambda ms, f: None)
    t.calls = []
    for name in ("on_frequency", "on_vfo", "on_mode", "on_filter", "on_swap"):
        setattr(t, name, lambda *a: None)
    t.on_split = lambda on: t.calls.append(("split", on))
    return t

@case("transport: split turned on in Brown is reported")
def _():
    c = Brown(); t = transport(c)
    c.split = 1; t._poll()
    assert t.calls == [("split", True)], t.calls
    t._poll()
    assert t.calls == [("split", True)], t.calls
    c.split = 0; t._poll()
    assert t.calls == [("split", True), ("split", False)], t.calls

@case("transport: split set by the app goes as S, transmit on the other VFO, not reported back")
def _():
    c = Brown(); t = transport(c)
    t.set_split(True)
    assert c.sent[-1] == "S 1 VFOB", c.sent
    t._poll()
    assert t.calls == [], t.calls
    t.active_vfo = "b"; t.set_split(False)
    assert c.sent[-1] == "S 0 VFOA", c.sent

class Ctl:
    def __init__(self): self.capabilities, self.sent = frozenset({sp.SPLIT}), []
    def set_split(self, on): self.sent.append(on); return True

def link(**model):
    base = dict(transmitting=False, locked=False, split=False)
    base.update(model)
    m = types.SimpleNamespace(**base)
    rig = types.SimpleNamespace(asked=[])
    rig.Toggle_Split = lambda: rig.asked.append("split")
    l = sl.SDR_Link.__new__(sl.SDR_Link)
    l._model, l._rig, l.controller = m, rig, Ctl()
    l._sent_split, l._split_asked = False, None
    l.follow = l._follow_split
    return l, m, rig

@case("link: split on in the SDR is asked of the rig once; the SDR is not put back meanwhile")
def _():
    l, m, rig = link()
    l._from_sdr_split(True); l._from_sdr_split(True)
    assert rig.asked == ["split"], rig.asked
    l._follow_split()
    assert l.controller.sent == [], l.controller.sent      # no S 0 while waiting
    m.split = True; l._follow_split()                       # the rig reports
    assert l.controller.sent == [] and l._split_asked is None, l.controller.sent

@case("link: the rig never confirms -- after the wait the SDR is put back")
def _():
    l, m, rig = link()
    l._from_sdr_split(True)
    l._split_asked = (True, sl.monotonic() - sl.SPLIT_CONFIRM_SECONDS - 1)
    l._follow_split()
    assert l.controller.sent == [False], l.controller.sent

@case("link: split changed on the rig or in the app reaches the SDR")
def _():
    l, m, rig = link()
    m.split = True; l._follow_split(); l._follow_split()
    m.split = False; l._follow_split()
    assert l.controller.sent == [True, False], l.controller.sent

@case("link: not while transmitting -- the SDR is put back, the rig not asked")
def _():
    l, m, rig = link(transmitting=True)
    l._from_sdr_split(True)
    assert rig.asked == [] and l.controller.sent == [False], (rig.asked, l.controller.sent)

print("\n".join(out))
print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
