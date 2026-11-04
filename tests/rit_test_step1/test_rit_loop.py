"""The SDR and the rig together: who turns RIT off, and does it stay off."""
import sys, types
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
gv = types.ModuleType("globalvars")
class Cfg:
    def __getattr__(self, n): return lambda *a, **k: 0
gv.config = Cfg(); sys.modules["globalvars"] = gv
import io, contextlib
import rigctl_sdr, sdr_programs
from rigctl_client import Reply
from test_rit import FakeClient, Root

class Rig:
    """The rig and model as the hooks see them (ubitx_link + sdr_link)."""
    def __init__(self):
        self.rit, self.base, self.rx, self.turn_off_flag, self.seed = False, 7030000, 7030000, False, 0
    # Toggle_RIT -> cr_ report -> cr_UX_RIT_Toggle / _leave_rit
    def toggle(self):
        if not self.rit:
            self.rit, self.base = True, self.rx
            if self.seed: self.rx = self.base + self.seed   # FIX path: rig asked, rig reports
            self.seed = 0
        else:
            self.rit, self.seed, self.turn_off_flag = False, 0, True
            self.rx = self.base
    @property
    def offset(self): return self.rx - self.base if self.rit else 0
    def hook(self, sdr):
        sdr.model_rit_state = lambda: self.rit
        sdr.model_rit_offset = lambda: self.offset
        def turn_off():
            f, self.turn_off_flag = self.turn_off_flag, False; return f
        sdr.model_turn_SDR_rit_off = turn_off
        def state_changed(hz, toggle):
            if toggle: self.toggle_pending = True
            self.seed = hz
        sdr.model_rit_state_changed = state_changed
        def update(hz): self.rx = self.base + hz
        sdr.model_update_rit_offset = update
        self.toggle_pending = False
    refuse = False
    toggles_asked = 0
    def tick(self):
        if self.toggle_pending:
            self.toggle_pending = False; self.toggles_asked += 1
            if not self.refuse: self.toggle()

def setup():
    sdr = rigctl_sdr.RigctlSDR(Root(), sdr_programs.profile_for("sdroxide"))
    sdr._client = FakeClient(); sdr.on_frequency = lambda hz: None
    rig = Rig(); rig.hook(sdr); sdr.discover()
    return sdr, rig

def run(sdr, rig, n=6):
    for _ in range(n):
        with contextlib.redirect_stdout(io.StringIO()):
            sdr._poll()
        rig.tick()

out = []
def case(name, fn):
    try: fn(); out.append(f"PASS  {name}")
    except AssertionError as e: out.append(f"FAIL  {name}: {e}")
    except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")

def a():
    sdr, rig = setup()
    rig.toggle(); run(sdr, rig)            # app turns RIT on
    rig.rx += 300; run(sdr, rig)           # app tunes +300 (app changed last)
    assert sdr._client.j == 300, f"SDR j={sdr._client.j}"
    sdr._client.j = 0; run(sdr, rig)       # operator zeroes RIT in SDRoxide
    assert not rig.rit, "rig RIT still on"
    assert rig.rx == rig.base, f"rx {rig.rx} != base {rig.base}"
    run(sdr, rig, 10)
    assert not rig.rit, "RIT came back on"
case("app on + app tuned, then j=0 in SDR -> app off, stays off", a)

def b():
    sdr, rig = setup()
    sdr._client.j = 200; run(sdr, rig)     # RIT started in SDRoxide
    assert rig.rit and rig.offset == 200, f"rit={rig.rit} offset={rig.offset}"
    sdr._client.j = 0; run(sdr, rig)
    assert not rig.rit, "rig RIT still on"
    run(sdr, rig, 10); assert not rig.rit, "RIT came back on"
case("SDR on, then j=0 in SDR -> app off, stays off", b)

def c():
    sdr, rig = setup()
    sdr._client.j = 200; run(sdr, rig)
    sdr._client.j_reply = Reply(False, code=-11); run(sdr, rig)
    assert rig.rit, "one refused j reply turned RIT off"
case("refused j reply while on -> RIT stays on", c)

def d():
    sdr, rig = setup()
    rig.toggle(); run(sdr, rig)
    rig.toggle(); run(sdr, rig)            # app turns it off again
    assert not rig.rit and sdr._client.j == 0, f"rit={rig.rit} j={sdr._client.j}"
    run(sdr, rig, 10); assert not rig.rit, "RIT came back on"
case("app on then off -> stays off", d)
import time
def e():
    rigctl_sdr.RIT_TOGGLE_TIMEOUT_SECONDS = 0.05
    sdr, rig = setup(); rig.refuse = True          # e.g. the rig is in split
    sdr._client.j = 200; run(sdr, rig, 2)
    time.sleep(0.1); run(sdr, rig, 4)
    assert sdr.rit_toggle_in_process is None, "still waiting"
    assert sdr._client.j == 0 and not rig.rit, f"j={sdr._client.j} rig={rig.rit}"
    time.sleep(0.1); run(sdr, rig, 10)
    assert rig.toggles_asked == 1, f"toggle asked {rig.toggles_asked} times"
case("rig refuses RIT on -> wait ends, SDR follows the rig, no retry loop", e)

def f():
    rigctl_sdr.RIT_TOGGLE_TIMEOUT_SECONDS = 0.05
    sdr, rig = setup()
    sdr._client.j = 200; run(sdr, rig)              # on from SDR, accepted
    rig.refuse = True
    sdr._client.j = 0; run(sdr, rig, 2)             # off from SDR, refused
    time.sleep(0.1); run(sdr, rig, 4)
    assert sdr.rit_toggle_in_process is None, "still waiting"
    assert rig.rit and sdr._client.j == rig.offset == 200, f"j={sdr._client.j} offset={rig.offset}"
case("rig refuses RIT off -> wait ends, SDR given the rig's offset back", f)
print("\n".join(out))
