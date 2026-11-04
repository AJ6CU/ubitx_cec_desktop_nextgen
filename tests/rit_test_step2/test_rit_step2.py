"""
RIT with the rig leading: SDR_Link + RigctlSDR + RadioModel, against a fake
SDRoxide (FakeClient) and a fake rig that behaves like ubitx_link -- a
toggle or frequency write is confirmed on the next tick, as a report.

    python3 test_rit_step2.py <app folder>
"""
import sys, types, time, io, contextlib
sys.path.insert(0, sys.argv[1])
gv = types.ModuleType("globalvars")
class Cfg:
    def __getattr__(self, n): return lambda *a, **k: 0
gv.config = Cfg(); sys.modules["globalvars"] = gv
for name in ("sdr_launcher", "system_audio", "rest_sdr"):      # not exercised
    m = types.ModuleType(name); m.RestSDR = object; sys.modules.setdefault(name, m)

import rigctl_sdr, sdr_programs, sdr_link
from rigctl_client import Reply
from radio_model import RadioModel

BASE = 7030000

class FakeClient:
    """SDRoxide over rigctl: f, j (0 = RIT off), commands logged."""
    def __init__(self, rit=True):
        self.f, self.j, self.has_rit, self.sent, self.j_reply = BASE, 0, rit, [], None
    def connect(self, h, p): return True
    def close(self): pass
    connected = True
    def query(self, c, lines=1):
        c = c.strip()
        if c == "f": return Reply(True, [str(self.f)])
        if c == "m": return Reply(True, ["CW", "500"])
        if c == "j":
            if not self.has_rit: return Reply(False, code=-11)
            return self.j_reply or Reply(True, [str(self.j)])
        if c == "s": return Reply(True, ["0", "VFOA"])
        return Reply(False, code=-11)
    def command(self, c):
        self.sent.append(c)
        k, _, v = c.partition(" ")
        if k == "F": self.f = int(v); return Reply(True)
        if k == "J": self.j = int(v); return Reply(True)
        return Reply(True)

class Rig:
    """What uBITX_Link does, reduced: asks now, the rig's report next tick."""
    def __init__(self, model):
        self.m, self.queue, self.toggles, self.refuse = model, [], 0, False
        self.delay = 0          # ticks before a report arrives: a busy serial line
    def Toggle_RIT(self):
        self.toggles += 1; self.queue.append(("rit",))
    def set_role_frequency(self, role, hz):
        self.freq_asks = getattr(self, "freq_asks", 0) + 1
        self.queue.append(("freq", hz))
    def set_mode_everywhere(self, mode): pass
    def tick(self):
        if self.delay and self.queue:
            self._held = getattr(self, "_held", 0) + 1
            if self._held <= self.delay: return
        self._held = 0
        if getattr(self, "one_at_a_time", False):
            q, self.queue = self.queue[:1], self.queue[1:]
        else:
            q, self.queue = self.queue, []
        for item in q:
            if item[0] == "rit":
                if self.refuse: continue
                m = self.m
                if not m.rit:                       # cr_ 1
                    m.rit, m.rit_base_hz = True, m.frequency(m.rx_vfo)
                else:                               # cr_ 0 -> _leave_rit
                    base, m.rit_base_hz, m.rit = m.rit_base_hz, 0, False
                    if base: self.queue.append(("freq", base))
            else:
                self.m.set_role_frequency("rx", item[1])
    # the operator, at the rig or in the app (the app only sends commands)
    def app_rit(self): self.Toggle_RIT()
    def app_tune(self, hz): self.set_role_frequency("rx", hz)
    def split_on(self):                            # cr_ 0 then cs_ 1
        if self.m.rit: self.queue.append(("rit",))

class Root:
    def after(self, ms, fn): return 1
    def after_cancel(self, i): pass

def setup(program="sdroxide"):
    model = RadioModel()
    model.set_frequency("a", BASE)
    rig = Rig(model)
    link = sdr_link.SDR_Link.__new__(sdr_link.SDR_Link)
    link.__dict__.update(root=Root(), _model=model, _rig=rig,
                         profile=sdr_programs.profile_for(program),
                         _sent_hz=None, _sent_mode=None, _sent_rit=None, _rit_asked=None, _rit_rx_asked=None, _qsy=None,
                         _rig_mode_asked=None, _rig_mode_asked_at=0.0, _decoding=False,
                         _frame_band=None)
    sdr = rigctl_sdr.RigctlSDR(Root(), link.profile)
    sdr._client = FakeClient(rit=program == "sdroxide")
    link.controller = sdr
    sdr.on_frequency = link._from_sdr_frequency
    sdr.on_rit = link._from_sdr_rit
    sdr.discover()
    type(link).connected = property(lambda self: True)
    return link, sdr, rig, model

def run(link, sdr, rig, n=6):
    for _ in range(n):
        with contextlib.redirect_stdout(io.StringIO()):
            sdr._poll(); rig.tick(); link.follow()

def state(sdr, model):
    return (f"rig rit={model.rit} rx={model.frequency(model.rx_vfo)} "
            f"offset={model.rit_offset} | sdr f={sdr._client.f} j={sdr._client.j}")

out = []
def case(name):
    def wrap(fn):
        try: fn(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

@case("app: RIT on, tune +300 -> SDR f=base j=300")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    rig.app_rit(); run(link, sdr, rig)
    rig.app_tune(BASE + 300); run(link, sdr, rig)
    assert (sdr._client.f, sdr._client.j) == (BASE, 300), state(sdr, m)

@case("app: tune RIT back to exactly 0 -> SDR j=0, rig RIT stays on")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    rig.app_rit(); rig.app_tune(BASE + 300); run(link, sdr, rig)
    rig.app_tune(BASE); run(link, sdr, rig, 10)
    assert sdr._client.j == 0 and m.rit, state(sdr, m)

@case("app: RIT off -> SDR j=0, both on base")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    rig.app_rit(); rig.app_tune(BASE + 300); run(link, sdr, rig)
    rig.app_rit(); run(link, sdr, rig, 10)
    assert not m.rit and m.frequency(m.rx_vfo) == BASE and sdr._client.j == 0, state(sdr, m)

@case("SDR: j=200 with RIT off -> rig RIT on at base+200, one toggle")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    sdr._client.j = 200; run(link, sdr, rig, 10)
    assert m.rit and m.rit_offset == 200, state(sdr, m)
    assert (sdr._client.f, sdr._client.j) == (BASE, 200), state(sdr, m)
    assert rig.toggles == 1, f"toggles={rig.toggles}"

@case("SDR: j 200 -> 350 while on -> rig rx base+350")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    sdr._client.j = 200; run(link, sdr, rig)
    sdr._client.j = 350; run(link, sdr, rig)
    assert m.rit_offset == 350 and sdr._client.j == 350, state(sdr, m)

@case("SDR: spun 100, 200, 300 one poll apart -> ends at 300")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    for j in (100, 200, 300):
        sdr._client.j = j; run(link, sdr, rig, 1)
    run(link, sdr, rig, 10)
    assert m.rit_offset == 300 and sdr._client.j == 300, state(sdr, m)

@case("SDR: j=0 -> rig RIT off, on base, stays off")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    sdr._client.j = 200; run(link, sdr, rig)
    sdr._client.j = 0; run(link, sdr, rig, 15)
    assert not m.rit and m.frequency(m.rx_vfo) == BASE and sdr._client.j == 0, state(sdr, m)
    assert rig.toggles == 2, f"toggles={rig.toggles}"

@case("app turned RIT on and tuned; then j=0 in SDR -> rig off")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    rig.app_rit(); rig.app_tune(BASE + 300); run(link, sdr, rig)
    sdr._client.j = 0; run(link, sdr, rig, 15)
    assert not m.rit and sdr._client.j == 0, state(sdr, m)

@case("split on while RIT on -> rig RIT off, SDR j=0")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    sdr._client.j = 200; run(link, sdr, rig)
    rig.split_on(); run(link, sdr, rig)
    assert not m.rit and sdr._client.j == 0 and sdr._client.f == BASE, state(sdr, m)

@case("SDR on, quickly off before the rig confirms -> rig ends off")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    rig.refuse = True                         # hold the first report back
    sdr._client.j = 200; run(link, sdr, rig, 1)
    sdr._client.j = 0;   run(link, sdr, rig, 1)
    rig.refuse = False; rig.queue.clear()     # both toggles lost: nets out
    run(link, sdr, rig, 10)
    assert not m.rit and sdr._client.j == 0, state(sdr, m)

@case("rig never confirms RIT on -> after the wait the SDR follows the rig")
def _():
    sdr_link.RIT_CONFIRM_SECONDS = 0.05
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    rig.refuse = True
    sdr._client.j = 200; run(link, sdr, rig, 2)
    time.sleep(0.1); run(link, sdr, rig, 5)
    assert not m.rit and sdr._client.j == 0 and link._rit_asked is None, state(sdr, m)
    time.sleep(0.1); run(link, sdr, rig, 10)
    assert rig.toggles == 1, f"toggles={rig.toggles}"
    sdr_link.RIT_CONFIRM_SECONDS = 3.0

@case("a refused j reply changes nothing")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    sdr._client.j = 200; run(link, sdr, rig)
    sdr._client.j_reply = Reply(False, code=-11); run(link, sdr, rig, 10)
    assert m.rit and m.rit_offset == 200 and rig.toggles == 1, state(sdr, m)

@case("SDR without RIT (SDR++): tuning works, J never sent")
def _():
    link, sdr, rig, m = setup("sdr++"); run(link, sdr, rig)
    rig.app_rit(); rig.app_tune(BASE + 300); run(link, sdr, rig)
    assert not any(c.startswith("J") for c in sdr._client.sent), sdr._client.sent
    sdr._client.f = BASE + 1000; run(link, sdr, rig)
    assert m.frequency(m.rx_vfo) == BASE + 1000, state(sdr, m)

def no_snap_back(sdr, old):
    return not any(c == f"F {old}" for c in sdr._client.sent)

@case("QSY: app RIT on +300, click in SDRoxide -> RIT off, rig on the click")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    rig.app_rit(); rig.app_tune(BASE + 300); run(link, sdr, rig)
    sdr._client.sent.clear()
    sdr._client.f = BASE + 5000; run(link, sdr, rig, 10)
    assert not m.rit and m.frequency(m.rx_vfo) == BASE + 5000, state(sdr, m)
    assert (sdr._client.f, sdr._client.j) == (BASE + 5000, 0), state(sdr, m)
    assert no_snap_back(sdr, BASE), f"SDR sent back: {sdr._client.sent}"

@case("QSY: RIT from SDRoxide j=200, click -> RIT off, rig on the click")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    sdr._client.j = 200; run(link, sdr, rig)
    sdr._client.sent.clear()
    sdr._client.f = BASE + 5000; run(link, sdr, rig, 10)
    assert not m.rit and m.frequency(m.rx_vfo) == BASE + 5000, state(sdr, m)
    assert sdr._client.j == 0 and no_snap_back(sdr, BASE), sdr._client.sent

@case("QSY, slow rig, dial spun 3 steps -> ends on the last, no snap back")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    rig.app_rit(); rig.app_tune(BASE + 300); run(link, sdr, rig)
    rig.delay = 2; rig.one_at_a_time = True; sdr._client.sent.clear()
    for k in (1, 2, 3):
        sdr._client.f = BASE + 1000 * k; run(link, sdr, rig, 1)
    run(link, sdr, rig, 30)
    assert not m.rit and m.frequency(m.rx_vfo) == BASE + 3000, state(sdr, m)
    assert sdr._client.f == BASE + 3000 and no_snap_back(sdr, BASE), sdr._client.sent

@case("QSY in SDR++ (no RIT in the SDR) with the app's RIT on -> RIT off, tuned")
def _():
    link, sdr, rig, m = setup("sdr++"); run(link, sdr, rig)
    rig.app_rit(); rig.app_tune(BASE + 300); run(link, sdr, rig)
    sdr._client.f = BASE + 5000; run(link, sdr, rig, 10)
    assert not m.rit and m.frequency(m.rx_vfo) == BASE + 5000, state(sdr, m)

@case("QSY, rig never leaves RIT -> after the wait the SDR follows the rig")
def _():
    sdr_link.RIT_CONFIRM_SECONDS = 0.05
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    rig.app_rit(); rig.app_tune(BASE + 300); run(link, sdr, rig)
    rig.refuse = True
    sdr._client.f = BASE + 5000; run(link, sdr, rig, 2)
    time.sleep(0.1); run(link, sdr, rig, 5)
    sdr_link.RIT_CONFIRM_SECONDS = 3.0
    assert m.rit and link._qsy is None, state(sdr, m)
    assert (sdr._client.f, sdr._client.j) == (BASE, 300), state(sdr, m)

@case("no RIT: a click just tunes, nothing toggled")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    sdr._client.f = BASE + 5000; run(link, sdr, rig)
    assert m.frequency(m.rx_vfo) == BASE + 5000 and rig.toggles == 0, state(sdr, m)

@case("slow rig: SDR's j=200 is not overwritten while the rig catches up")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    rig.delay = 3
    sdr._client.j = 200; run(link, sdr, rig, 20)
    assert m.rit and m.rit_offset == 200 and sdr._client.j == 200, state(sdr, m)
    assert rig.toggles == 1, f"toggles={rig.toggles}"
    assert rig.freq_asks == 1, f"receive frequency asked {rig.freq_asks} times"

@case("slow rig: SDR spun 100, 200, 300 -> SDR never sent back an older j")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    sdr._client.j = 50; run(link, sdr, rig)          # RIT on first
    rig.delay = 2; rig.one_at_a_time = True; sdr._client.sent.clear()
    for j in (100, 200, 300):
        sdr._client.j = j; run(link, sdr, rig, 1)
    run(link, sdr, rig, 20)
    assert m.rit_offset == 300 and sdr._client.j == 300, state(sdr, m)
    stale = [c for c in sdr._client.sent if c.startswith("J") and c != "J 300"]
    assert not stale, f"sent the SDR {stale}"

@case("slow rig: app spin under RIT reaches the SDR at the end")
def _():
    link, sdr, rig, m = setup(); run(link, sdr, rig)
    rig.app_rit(); run(link, sdr, rig)
    rig.delay = 2
    for hz in (BASE + 100, BASE + 200, BASE + 300):
        rig.app_tune(hz); run(link, sdr, rig, 1)
    run(link, sdr, rig, 20)
    assert m.rit_offset == 300 and sdr._client.j == 300, state(sdr, m)

print("\n".join(out))
print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
