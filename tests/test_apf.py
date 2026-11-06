"""
SDRoxide Brown's CW peak filter (APF) over rigctl, against a fake that
behaves as its PR does: `u APF` / `l APF` answered in any mode, `U APF` /
`L APF` refused outside CW, the level being the width (0 widest .. 1
narrowest).

    python3 test_apf.py <app folder>
"""
import sys, types, io, contextlib
sys.path.insert(0, '.')
# sys.path.insert(0, sys.argv[1])
gv = types.ModuleType("globalvars")
class Cfg:
    def __getattr__(self, n): return lambda *a, **k: 0
gv.config = Cfg(); sys.modules["globalvars"] = gv
import importlib.util
# Stand-ins only where the app folder lacks a module sdr_link imports.
for name in ("sdr_launcher", "system_audio", "rest_sdr"):
    if importlib.util.find_spec(name) is None:
        stub = types.ModuleType(name); stub.RestSDR = object; sys.modules[name] = stub
import rigctl_sdr, sdr_programs, sdr_link
from rigctl_client import Reply

class FakeBrown:
    connected = True
    def __init__(self, mode="CW", apf=True):
        self.mode, self.has_apf, self.on, self.level, self.sent = mode, apf, False, 5 / 9, []
    def connect(self, h, p): return True
    def close(self): pass
    def query(self, c, lines=1):
        c = c.strip()
        if c == "f": return Reply(True, ["7030000"])
        if c == "m": return Reply(True, [self.mode, "500"])
        if c == "u APF" and self.has_apf: return Reply(True, ["1" if self.on else "0"])
        if c == "l APF" and self.has_apf: return Reply(True, [f"{self.level:.6f}"])
        return Reply(False, code=-11)
    def command(self, c):
        self.sent.append(c); p = c.split()
        if p[:2] in (["U", "APF"], ["L", "APF"]):
            if not self.has_apf or self.mode != "CW": return Reply(False, code=-11)
            if p[0] == "U": self.on = p[2] == "1"
            else: self.level = float(p[2])
            return Reply(True)
        if p[0] == "M": self.mode = p[1]; return Reply(True)
        return Reply(True)

class Root:
    def after(self, ms, fn): return 1
    def after_cancel(self, i): pass

def make(mode="CW", apf=True):
    prof = sdr_programs.profile_for("sdroxide")
    prof = types.SimpleNamespace(**{**vars(prof), "settle_seconds": 0, "known_missing": set(),
                                    "width_needs_mode_change": False})
    sdr = rigctl_sdr.RigctlSDR(Root(), prof)
    sdr._client = FakeBrown(mode, apf)
    seen = []
    sdr.on_dsp = seen.append
    sdr.discover()
    return sdr, seen

def poll(sdr):
    with contextlib.redirect_stdout(io.StringIO()):
        sdr._poll()

out = []
def case(name):
    def wrap(fn):
        try: fn(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

@case("found at connect in CW: the lamp, off, and its width knob at 100 Hz")
def _():
    sdr, _ = make("CW")
    assert rigctl_sdr.CW_PEAK in sdr.capabilities, sdr.capabilities
    assert sdr.dsp_on.get("cw") is False
    assert sdr.dsp_knob_names("cw") == ["width"]
    assert sdr.dsp_settings["cw"]["width"] == 1, sdr.dsp_settings

@case("found at connect in USB too, where Brown refuses a set")
def _():
    sdr, _ = make("USB")
    assert rigctl_sdr.CW_PEAK in sdr.capabilities, sdr.capabilities
    assert sdr.dsp_knob_names("cw") == ["width"]
    assert not any("APF" in c for c in sdr._client.sent), sdr._client.sent

@case("the lamp switches APF; the knob sets the width")
def _():
    sdr, _ = make("CW")
    assert sdr.set_dsp("cw", True)
    assert sdr._client.sent[-1] == "U APF 1" and sdr._client.on
    assert sdr.set_dsp_setting("cw", "width", 2)
    assert sdr._client.sent[-1] == "L APF 0.833333", sdr._client.sent[-1]

@case("a change made in SDRoxide is followed")
def _():
    sdr, seen = make("CW")
    sdr._client.on, sdr._client.level = True, 1.0
    poll(sdr)
    assert sdr.dsp_on["cw"] is True and sdr.dsp_settings["cw"]["width"] == 3, (sdr.dsp_on, sdr.dsp_settings)
    assert "cw" in seen, seen

@case("a program without APF: no lamp, no knob")
def _():
    sdr, _ = make("CW", apf=False)
    assert rigctl_sdr.CW_PEAK not in sdr.capabilities
    assert sdr.dsp_knob_names("cw") == [] and not sdr.set_dsp("cw", True)

@case("the window greys it outside CW, saying why, and not in CW")
def _():
    sdr, _ = make("USB")
    model = types.SimpleNamespace(rx_vfo="A", mode="USB")
    model.mode_of = lambda vfo: model.mode
    link = types.SimpleNamespace(controller=sdr, _model=model, connected=True,
                                 profile=sdr.profile, OFF_IN_CW=sdr_link.SDR_Link.OFF_IN_CW,
                                 has_dsp=lambda f: True)
    blocked = lambda f: sdr_link.SDR_Link.dsp_blocked(link, f)
    assert blocked("cw") and "CW only" in blocked("cw"), blocked("cw")
    model.mode = "CWU"
    assert blocked("cw") is None, blocked("cw")
    model.mode = "USB"
    assert blocked("nb") is None

print("\n".join(out))
print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
