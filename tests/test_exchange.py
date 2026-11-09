"""
A/B selects, A<->B exchanges (Brown's meaning), A->B copies. An exchange made
in the SDR is done on the rig too.

    python3 test_exchange.py <app folder>
"""
import ast, os, sys, textwrap, types
folder = sys.argv[1]
sys.path.insert(0, folder)
for name in ("globalvars", "sdr_launcher", "system_audio", "rest_sdr"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["rest_sdr"].RestSDR = object
sys.modules["globalvars"].config = types.SimpleNamespace()
import rigctl_sdr as rs
import sdr_link as sl
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

lsrc = open(os.path.join(folder, "ubitx_link.py")).read()
lcls = next(n for n in ast.parse(lsrc).body if isinstance(n, ast.ClassDef) and n.name == "uBITX_Link")
lf = {n.name: n for n in lcls.body if isinstance(n, ast.FunctionDef) and n.name in ("exchange_vfos", "_exchange_step", "_exchange_now",
                                                                   "_exchange_after_rit_off")}

@case("link: exchange -- the other VFO gets the active one's, then the active one the other's")
def _():
    assert "exchange_vfos" in lf, "no exchange"
    import radio_model
    m = radio_model.RadioModel(); m.set_frequency("a", 7074000); m.set_frequency("b", 14070000)
    m.set_mode("a", "LSB"); m.set_mode("b", "USB")
    done, timers = [], []
    l = types.SimpleNamespace(_model=m, _rit_saved={"a": (7074000, 7074300)}, _tx_write_state=None,
                              _vrit_saved={"b": 14069000}, _exchange_carry=None,
                              _exchange_rit_off=False)
    l._maybe_restore_rit = lambda: done.append(("restore",))
    l.root = types.SimpleNamespace(after=lambda ms, f: timers.append(f))
    l._begin_borrowed_write = lambda hz, mode=None: done.append(("other", hz, mode))
    l.set_mode = lambda mode: done.append(("mode", mode))
    l._request_frequency = lambda hz: done.append(("rx", hz))
    ns = {"monotonic": __import__("time").monotonic, "EXCHANGE_TIMEOUT_S": 5.0,
          "STEP_SETTLE_MS": 150, "print": lambda *a, **k: None}
    for name, node in lf.items():
        exec(textwrap.dedent(ast.get_source_segment(lsrc, node)), ns)
        setattr(l, name, types.MethodType(ns[name], l))
    l.exchange_vfos()
    assert done == [("other", 7074000, "LSB")], done
    l._tx_write_state = "awaiting-borrow"; timers.pop(0)()
    assert len(done) == 1, "the active VFO written during the borrow"
    l._tx_write_state = None; timers.pop(0)()
    assert done[1:] in ([("mode", "USB"), ("rx", 14070000)], [("mode", "USB"), ("restore",)]), done
    assert l._rit_saved == {"b": (7074000, 7074300)}, "A's remembered RIT did not go with its contents"
    assert l._vrit_saved == {"a": 14069000}, "B's split RIT did not go with its contents"

class Reply:
    def __init__(self, ok, values=()): self.ok, self.values = ok, list(values)

class Brown:
    def __init__(self): self.vfo, self.f, self.connected = "VFOA", {"VFOA": 7074000, "VFOB": 14070000}, True
    def query(self, text, lines=1):
        t = text.split()
        if t[0] == "v": return Reply(True, [self.vfo])
        if t[0] == "f": return Reply(True, [str(self.f[t[1] if len(t) > 1 else self.vfo])])
        if t[0] == "m": return Reply(True, ["USB", "2400"])
        return Reply(False)
    def command(self, text): return Reply(True)

def transport(c):
    t = rs.RigctlSDR.__new__(rs.RigctlSDR)
    t._client = c; t.profile = types.SimpleNamespace(settle_seconds=0)
    t._settling = {}; t.capabilities = frozenset({rs.VFO_AB}); t.active_vfo = "a"
    t.frequency, t.other_vfo_hz = 7074000, 14070000
    t._hop = None; t.mode = "USB"; t.filter_width = 2400; t._decoder_socket = None
    t._levels_found = set(); t.dsp_on = {}; t.dsp_settings = {}
    t.root = types.SimpleNamespace(after=lambda ms, f: None)
    t.calls = []
    t.on_swap = lambda: t.calls.append("swap"); t.on_frequency = lambda hz: t.calls.append(("f", hz))
    t.on_vfo = lambda v: t.calls.append(("v", v)); t.on_mode = t.on_filter = lambda *a: None
    return t

@case("transport: Brown's A<->B is reported as an exchange, not a tune")
def _():
    c = Brown(); t = transport(c)
    c.f = {"VFOA": 14070000, "VFOB": 7074000}            # swapped in Brown
    t._poll()
    assert t.calls == ["swap"], t.calls

@case("transport: a plain tune in Brown is still a tune")
def _():
    c = Brown(); t = transport(c)
    c.f["VFOA"] = 7075000
    t._poll()
    assert t.calls == [("f", 7075000)], t.calls

def link_with(**model):
    base = dict(transmitting=False, locked=False, rit=False, rx_vfo="a")
    base.update(model)
    m = types.SimpleNamespace(**base)
    asked = []
    l = sl.SDR_Link.__new__(sl.SDR_Link)
    l._model = m; l._rig = types.SimpleNamespace(exchange_vfos=lambda: asked.append("exchange"))
    l.follow = lambda: asked.append("put back")
    return l, asked

@case("link: an exchange in the SDR is done on the rig")
def _():
    assert hasattr(sl.SDR_Link, "_from_sdr_swap"), "not handled"
    l, asked = link_with(); l._from_sdr_swap()
    assert asked == ["exchange"], asked

@case("link: not transmitting or locked -- the SDR is put back; with RIT on it goes ahead")
def _():
    assert hasattr(sl.SDR_Link, "_from_sdr_swap"), "not handled"
    l, asked = link_with(rit=True); l._from_sdr_swap()
    assert asked == ["exchange"], ("rit", asked)
    for kw in (dict(transmitting=True), dict(locked=True)):
        l, asked = link_with(**kw); l._from_sdr_swap()
        assert asked == ["put back"], (kw, asked)

asrc = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()

@case("app: A/B selects, A⇄B exchanges, A→B copies")
def _():
    assert 'tx_button("A/B", self._swap' in asrc, "no A/B select"
    assert r'tx_button("A \u21c4 B", self._exchange' in asrc, "A⇄B does not exchange"
    assert "self.connection.exchange_vfos()" in asrc.split("def _exchange")[1].split("\\n    def ")[0]

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
