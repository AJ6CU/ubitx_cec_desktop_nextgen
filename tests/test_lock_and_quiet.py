"""
The rig's lock across the app's controls, and the SDR silenced in rig mode.

    python3 test_lock_and_quiet.py <app folder>

Runs ubitx_cec_desktop.py's own handlers (lifted from the file) and
sdr_link.SDR_Link against stand-ins -- no window, no rig, no SDR.
"""
import ast, sys, textwrap, types, os, importlib.util
folder = sys.argv[1]
sys.path.insert(0, folder)
gv = types.ModuleType("globalvars")
class Cfg:
    def __getattr__(self, n): return lambda *a, **k: 0
gv.config = Cfg(); sys.modules["globalvars"] = gv
for name in ("sdr_launcher", "system_audio", "rest_sdr"):
    if importlib.util.find_spec(name) is None:
        stub = types.ModuleType(name); stub.RestSDR = object; sys.modules[name] = stub
import sdr_link
from sdr_programs import MUTE, RIT

src = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()
tree = ast.parse(src)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "UbitxCecDesktop")
wanted = ("_toggle", "_set_listen_source", "_sdr_quiet_for_rig", "_on_band", "_on_mode",
          "_filter_reset", "_volume_set", "_toggle_scan", "_show_filter_buttons")
methods = {n.name: textwrap.dedent(ast.get_source_segment(src, n))
           for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in wanted}
consts = {}
for n in cls.body:
    if isinstance(n, ast.Assign) and n.targets[0].id in ("LOCKED_NOTE", "LIVE_WHEN_LOCKED", "OFF_BAND"):
        consts[n.targets[0].id] = ast.literal_eval(n.value)

class Picker:
    def __init__(self, v): self.v = v
    def get(self): return self.v
    def set(self, v): self.v = v

def window(locked=False, source="Rig"):
    sent = []
    w = types.SimpleNamespace(**consts)
    w.model = types.SimpleNamespace(locked=locked, muted=False, mode="USB",
                                    band_name=lambda: "40m", BANDS=[("40m", 7000000, 7300000)])
    w.connection = types.SimpleNamespace(**{n: (lambda n=n: (lambda *a: sent.append(n)))()
                                            for n in ("Toggle_Split", "Toggle_RIT", "Toggle_Lock",
                                                      "Toggle_Stop", "Toggle_Speaker",
                                                      "set_mode_everywhere", "set_role_frequency",
                                                      "set_mode")})
    w.sdr = types.SimpleNamespace(connected=True, capabilities={MUTE}, muted=False,
                                  reset_filter=lambda: sent.append("reset_filter"),
                                  set_volume=lambda v: sent.append("volume"),
                                  frame_band=lambda *a: None)
    w.sdr.set_muted = lambda m: (sent.append(f"sdr_mute {m}"), setattr(w.sdr, "muted", m))
    w._ready, w._listen_source, w._listen_chosen = True, source, False
    w.receiver_picker, w.band_picker, w.mode_picker = Picker(source), Picker("40m"), Picker("USB")
    w.volume_knob = types.SimpleNamespace(set_live=lambda live: None)
    w.refresh = lambda: None
    w._mute_pressed = lambda: sent.append("mute")
    w._show_volume = lambda: None
    w._volume_level, w._volume_shown = 50, None
    w.scanner = types.SimpleNamespace(running=False)
    w._notify = lambda text: sent.append(f"note {text}")
    for name, code in methods.items():
        ns = {"MUTE": MUTE, "time": __import__("time")}
        exec(code, ns)
        setattr(w, name, types.MethodType(ns[name], w))
    return w, sent

out = []
def case(name):
    def wrap(fn):
        try: fn(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

@case("locked: split, RIT, band, mode, filter, volume and scan send nothing")
def _():
    w, sent = window(locked=True)
    w._toggle("split"); w._toggle("rit")
    w.band_picker.set("20m"); w._on_band()
    w._on_mode("LSB"); w._filter_reset(); w._volume_set(80)
    w._toggle_scan()
    assert [x for x in sent if not x.startswith("note")] == [], sent
    assert w.band_picker.get() == "40m" and w.mode_picker.get() == "USB", "pickers not put back"

@case("locked: Lock and TX off still work")
def _():
    w, sent = window(locked=True)
    w._toggle("locked"); w._toggle("tx_inhibit")
    assert sent == ["Toggle_Lock", "Toggle_Stop"], sent

@case("locked: the receiver choice is refused and the picker put back")
def _():
    w, sent = window(locked=True, source="SDR")
    w.receiver_picker.set("Rig"); w._set_listen_source("Rig", by_operator=True)
    assert w._listen_source == "SDR" and w.receiver_picker.get() == "SDR" and not sent, sent

@case("unlocked: the controls work")
def _():
    w, sent = window()
    w._toggle("split"); w._filter_reset()
    assert sent == ["Toggle_Split", "reset_filter"], sent

@case("rig mode mutes the SDR; SDR mode gives it back as it was")
def _():
    w, sent = window(source="SDR")
    w._set_listen_source("Rig", by_operator=True)
    assert w.sdr.muted is True and "sdr_mute True" in sent, sent
    w._set_listen_source("SDR", by_operator=True)
    assert w.sdr.muted is False, "not given back"

@case("an SDR the operator had muted stays muted on return to SDR mode")
def _():
    w, sent = window(source="SDR"); w.sdr.muted = True
    w._set_listen_source("Rig", by_operator=True)
    w._set_listen_source("SDR", by_operator=True)
    assert w.sdr.muted is True and not any(x.startswith("sdr_mute") for x in sent), sent

@case("an SDR without a mute of its own is left alone (no computer mute)")
def _():
    w, sent = window(source="SDR"); w.sdr.capabilities = set()
    w._set_listen_source("Rig", by_operator=True)
    assert not any(x.startswith("sdr_mute") for x in sent), sent

class Btn:
    def __init__(self): self.s = "normal"
    def state(self, s): self.s = s

@case("locked: the filter buttons stay grey when the SDR (re)connects")
def _():
    w, sent = window(locked=True); w.sdr.capabilities = {"filter"}
    w.filter_buttons = [Btn(), Btn(), Btn()]
    assert "_show_filter_buttons" in methods, "no _show_filter_buttons"
    w._show_filter_buttons()
    assert all(b.s == "disabled" for b in w.filter_buttons), [b.s for b in w.filter_buttons]
    assert "_show_filter_buttons()" in src.split("def _show_sdr_status")[1].split("\n    def ")[0], \
        "the SDR status still sets the filter buttons itself"
    w.model.locked = False; w._show_filter_buttons()
    assert all(b.s == "normal" for b in w.filter_buttons), "not back when unlocked"

class Ctl:
    def __init__(self): self.calls, self.capabilities, self.is_connected, self.filter_width = [], {RIT}, True, 500
    def set_frequency(self, hz, band=None): self.calls.append(("F", hz))
    def set_mode(self, m, w): self.calls.append(("M", m, w))
    def set_rit(self, hz): self.calls.append(("J", hz))
    def default_filter_width(self, m): return 2600

def link(locked):
    l = sdr_link.SDR_Link.__new__(sdr_link.SDR_Link)
    asked = []
    l._model = types.SimpleNamespace(locked=locked, rit=False, rit_offset=0, rit_base_hz=None,
                                     rx_vfo="a", role_frequency=lambda r: 7030000,
                                     mode_of=lambda v: "USB", default_sideband=lambda hz: "LSB")
    l._rig = types.SimpleNamespace(set_role_frequency=lambda r, hz: asked.append(("freq", hz)),
                                   set_mode_everywhere=lambda m: asked.append(("mode", m)),
                                   Toggle_RIT=lambda: asked.append("rit"))
    l.controller, l.profile = Ctl(), types.SimpleNamespace(to_sdr={"USB": "USB", "LSB": "LSB"},
                                                          from_sdr={"USB": "USB", "LSB": "LSB"}, name="x")
    l._sent_hz, l._sent_mode, l._sent_rit = 7030000, "USB", 0
    l._qsy = l._rit_asked = l._rit_rx_asked = l._rig_mode_asked = None
    l._rig_mode_asked_at, l._decoding = 0.0, False
    return l, asked

@case("locked: the SDR still leads -- a tune made there is asked of the rig")
def _():
    l, asked = link(True)
    l._from_sdr_frequency(7040000)
    assert asked == [("freq", 7040000)], asked

@case("unlocked: a tune in the SDR is asked of the rig, as before")
def _():
    l, asked = link(False)
    l._from_sdr_frequency(7040000)
    assert asked == [("freq", 7040000)], asked

print("\n".join(out))
print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
