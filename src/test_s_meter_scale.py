"""
The SDR S-meter scale (Setup > SDR settings, 0-200 %, 100 as before).

    python3 test_s_meter_scale.py <app folder>
"""
import ast, os, sys, types, textwrap
folder = sys.argv[1]
sys.path.insert(0, folder)
for name in ("globalvars", "sdr_launcher", "system_audio", "rest_sdr"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["rest_sdr"].RestSDR = object
gv = sys.modules["globalvars"]
saved = []
gv.config = types.SimpleNamespace(config_data={}, saveConfig=lambda: saved.append(1))
import sdr_link as sl
from sdr_programs import SIGNAL
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

def link(level):
    l = sl.SDR_Link.__new__(sl.SDR_Link)
    l.controller = types.SimpleNamespace(signal=level, capabilities=frozenset({SIGNAL}))
    l.profile = types.SimpleNamespace(signal_unit="dBFS")
    type(l).capabilities = property(lambda self: self.controller.capabilities)
    return l

@case("100 %: as before (S9 at -44 dBFS reads 9)")
def _():
    l = link(-44.0); l.s_meter_scale = 1.0
    assert abs(l.s_units() - 9.0) < 1e-9, l.s_units()

@case("a known S9 reading S7: 9/7 brings it to S9")
def _():
    l = link(-56.0); l.s_meter_scale = 1.0
    assert abs(l.s_units() - 7.0) < 1e-9, l.s_units()
    l.s_meter_scale = 9 / 7
    assert abs(l.s_units() - 9.0) < 1e-9, l.s_units()

@case("no reading stays None, whatever the scale")
def _():
    l = link(None); l.s_meter_scale = 2.0
    assert l.s_units() is None

src = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()
tree = ast.parse(src)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "UbitxCecDesktop")
fns = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
consts = {t.id: ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
          for t in n.targets if isinstance(t, ast.Name) and t.id in ("PREFERENCES_KEY", "S_METER_SCALE_RANGE")}

def window():
    w = types.SimpleNamespace(**consts, sdr=types.SimpleNamespace(s_meter_scale=1.0))
    for name in ("_s_meter_scale_saved", "_set_s_meter_scale"):
        ns = {"gv": gv}
        exec(textwrap.dedent(ast.get_source_segment(src, fns[name])), ns)
        setattr(w, name, types.MethodType(ns[name], w))
    return w

@case("window: saved as a percentage, applied as a factor, kept to 0-200")
def _():
    assert "_set_s_meter_scale" in fns, "no S-meter scale in the window"
    gv.config.config_data.clear(); saved.clear()
    w = window()
    assert w._s_meter_scale_saved() == 100
    w._set_s_meter_scale(129)
    assert abs(w.sdr.s_meter_scale - 1.29) < 1e-9 and saved
    assert gv.config.config_data["Preferences"]["s_meter_scale_pct"] == 129
    assert w._s_meter_scale_saved() == 129
    w._set_s_meter_scale(500); assert w._s_meter_scale_saved() == 200
    gv.config.config_data["Preferences"]["s_meter_scale_pct"] = "junk"
    assert w._s_meter_scale_saved() == 100

@case("window: applied at start-up and saved from SDR settings")
def _():
    assert "_set_s_meter_scale(self._s_meter_scale_saved(), save=False)" in src
    seg = ast.get_source_segment(src, fns["_sdr_advanced"])
    assert "_set_s_meter_scale(" in seg and "S-meter scale" in seg

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)}/{len(out)}")
