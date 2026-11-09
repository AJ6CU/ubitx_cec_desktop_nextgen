"""
RIT kept across a VFO switch: the firmware clears it (menuVfoToggle calls
ritDisable); the app remembers the base and puts it back on return.

    python3 test_rit_vfo.py <app folder>
"""
import ast, os, sys, textwrap, types
folder = sys.argv[1]
sys.path.insert(0, folder)
import radio_model
src = open(os.path.join(folder, "ubitx_link.py")).read()
tree = ast.parse(src)
link_cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "uBITX_Link")
HANDLERS = ("cr_UX_RIT_Toggle", "cv_UX_VFO_Toggle", "cs_UX_SPLIT_Toggle", "_extract_value")
METHODS = ("_leave_rit", "_rit_cleared_by_switch", "_maybe_restore_rit", "_step_rit_restore",
           "toggle_rit_for_operator", "_start_virtual_rit", "_end_virtual_rit",
           "_virtual_rit_vfo_changed", "_decide_rit_off", "_rit_split_changed",
           "exchange_vfos", "_exchange_after_rit_off", "_exchange_now", "_exchange_step")
hf = {n.name: n for n in ast.walk(link_cls) if isinstance(n, ast.FunctionDef) and n.name in HANDLERS}
mf = {n.name: n for n in link_cls.body if isinstance(n, ast.FunctionDef) and n.name in METHODS}
consts = {n.targets[0].id: ast.literal_eval(n.value) for n in link_cls.body
          if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "RIT_RESTORE_TIMEOUT_S"}
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

class Rig:
    """The firmware's side, as ubitx_20.ino/ubitx_menu.ino do it."""
    def __init__(self, model, reader):
        self.m, self.r = model, reader
        self.vfo, self.f = "a", {"a": 7074000, "b": 14074000}
        self.rit, self.rit_tx = False, 0
        self.report_all()
    def report_all(self):
        self.m.set_frequency("a", self.f["a"]); self.m.set_frequency("b", self.f["b"])
    def cr(self, v): self.r.cr_UX_RIT_Toggle(list(f"pm.cr.val={v}\xff\xff\xff"))
    def cv(self, v): self.r.cv_UX_VFO_Toggle(list(f"pm.cv.val={v}\xff\xff\xff"))
    def cs(self, v):
        if hasattr(self.r, "cs_UX_SPLIT_Toggle"):
            self.r.cs_UX_SPLIT_Toggle(list(f"pm.cs.val={v}\xff\xff\xff"))
        else:
            self.m.split = bool(v)
    split = False
    def toggle_split(self):                   # menuSplitOnOff
        if self.split:
            self.split = False
        else:
            self.split = True
            self.rit = False                  # ritOn = 0, no retune
            self.cr(0)                        # reported first...
        self.cs(1 if self.split else 0)       # ...then split
    def key(self):                            # startTx
        if self.rit:
            return self.rit_tx
        if self.split:
            self.vfo = "b" if self.vfo == "a" else "a"; self.cv(0 if self.vfo == "a" else 1)
            hz = self.f[self.vfo]
            self.vfo = "b" if self.vfo == "a" else "a"; self.cv(0 if self.vfo == "a" else 1)
            return hz
        return self.f[self.vfo]
    def toggle_rit(self):
        self.rit = not self.rit
        self.rit_tx = self.f[self.vfo] if self.rit else 0
        self.cr(1 if self.rit else 0)
    def tune(self, hz):                       # the dial, or a frequency write
        self.f[self.vfo] = hz; self.m.set_frequency(self.vfo, hz)
    def toggle_vfo(self):                     # menuVfoToggle: switch, then ritDisable
        self.vfo = "b" if self.vfo == "a" else "a"
        self.cv(0 if self.vfo == "a" else 1)  # reported first
        if self.rit:
            # ritDisable: setFrequency(ritTxFrequency) -- on the NEW VFO
            self.rit = False
            self.f[self.vfo] = self.rit_tx
            self.m.set_frequency(self.vfo, self.rit_tx)
            self.cr(0)

def setup():
    m = radio_model.RadioModel()
    timers = []
    link = types.SimpleNamespace(_model=m, _rit_saved={}, _rit_restore=None, _tx_write_state=None,
                                 _freq_sent=None, _rit_switch_to=None, _rit_off_pending=None,
                                 _exchange_carry=None, _exchange_rit_off=False, **consts)
    link.root = types.SimpleNamespace(after=lambda ms, f: timers.append(f))
    reader = types.SimpleNamespace(_model=m, _radio_link=link)
    ns = {"STEP_SETTLE_MS": 150, "SPLIT_RIT_WAIT_MS": 300, "EXCHANGE_TIMEOUT_S": 5.0,
          "print": lambda *a, **k: None}
    import time
    ns["monotonic"] = time.monotonic
    for name, node in list(hf.items()) + list(mf.items()):
        exec(textwrap.dedent(ast.get_source_segment(src, node)), ns)
        target = reader if name in HANDLERS else link
        setattr(target, name, types.MethodType(ns[name], target))
    rig = Rig(m, reader)
    link._request_frequency = lambda hz: rig.tune(hz)
    link.Toggle_RIT = rig.toggle_rit
    link.root = types.SimpleNamespace(after=lambda ms, f: timers.append(f))
    def borrowed(hz, mode=None):            # the borrow: write the other VFO
        other = "b" if rig.vfo == "a" else "a"
        rig.f[other] = hz; m.set_frequency(other, hz)
    link._begin_borrowed_write = borrowed
    link.set_mode = lambda mode: None
    def run():
        for _ in range(50):
            if not timers: break
            timers.pop(0)()
    return m, rig, link, run

@case("RIT on A, switch to B and back: RIT is on again with the same offset")
def _():
    assert "_maybe_restore_rit" in mf, "not kept"
    m, rig, link, run = setup()
    rig.toggle_rit(); rig.tune(7074300)                 # RIT +300 on A
    assert m.rit and m.rit_offset == 300
    rig.toggle_vfo(); run()
    assert not m.rit and m.rx_vfo == "b"
    rig.toggle_vfo(); run()
    assert m.rit and m.rx_vfo == "a", (m.rit, m.rx_vfo)
    assert m.rit_base_hz == 7074000 and m.rit_offset == 300, (m.rit_base_hz, m.rit_offset)
    assert rig.rit_tx == 7074000, f"the rig transmits on {rig.rit_tx}"

@case("switching away with RIT on: B keeps its own frequency (the firmware moves it to A's base)")
def _():
    m, rig, link, run = setup()
    rig.toggle_rit(); rig.tune(7074300)
    rig.toggle_vfo(); run()
    assert m.rx_vfo == "b" and m.frequency("b") == 14074000, m.frequency("b")
    assert rig.f["b"] == 14074000, f"the rig left B on {rig.f['b']}"

@case("RIT turned off by the operator is not put back")
def _():
    assert "_maybe_restore_rit" in mf, "not kept"
    m, rig, link, run = setup()
    rig.toggle_rit(); rig.tune(7074300); rig.toggle_rit()      # off by hand
    rig.toggle_vfo(); run(); rig.toggle_vfo(); run()
    assert not m.rit, "put back"

@case("B never had RIT: nothing happens on B")
def _():
    assert "_maybe_restore_rit" in mf, "not kept"
    m, rig, link, run = setup()
    rig.toggle_rit(); rig.tune(7074300); rig.toggle_vfo(); run()
    assert not m.rit and link._rit_restore is None

@case("a different RIT on each VFO: each comes back with its own offset")
def _():
    assert "_maybe_restore_rit" in mf, "not kept"
    m, rig, link, run = setup()
    rig.toggle_rit(); rig.tune(7074300)                     # A +300
    rig.toggle_vfo(); run()
    rig.toggle_rit(); rig.tune(14073800)                    # B -200
    rig.toggle_vfo(); run()
    assert m.rx_vfo == "a" and m.rit and m.rit_offset == 300, (m.rx_vfo, m.rit, m.rit_offset)
    rig.toggle_vfo(); run()
    assert m.rx_vfo == "b" and m.rit and m.rit_offset == -200, (m.rx_vfo, m.rit, m.rit_offset)
    assert m.rit_base_hz == 14074000 and rig.rit_tx == 14074000
    rig.toggle_vfo(); run()
    assert m.rx_vfo == "a" and m.rit_offset == 300 and rig.rit_tx == 7074000

@case("A/B/A quicker than the restore: A's RIT is not lost")
def _():
    assert "_maybe_restore_rit" in mf, "not kept"
    m, rig, link, run = setup()
    rig.toggle_rit(); rig.tune(7074300)
    rig.toggle_vfo(); run()
    rig.toggle_vfo()                     # back on A: the restore starts...
    rig.toggle_vfo()                     # ...and B again before it is done
    run()
    rig.toggle_vfo(); run()              # A once more
    assert m.rx_vfo == "a" and m.rit and m.rit_offset == 300, (m.rx_vfo, m.rit, m.rit_offset)

def press_rit(link, rig):
    """The app's RIT button."""
    if hasattr(link, "toggle_rit_for_operator"):
        link.toggle_rit_for_operator()
    else:
        rig.toggle_rit()

@case("split: RIT on the receive VFO is the app's -- transmit stays on B")
def _():
    assert "toggle_rit_for_operator" in mf, "no RIT kept by the app"
    m, rig, link, run = setup()
    rig.toggle_split(); run()
    press_rit(link, rig); rig.tune(7074300)
    assert m.rit and m.rit_offset == 300 and not rig.rit, (m.rit, m.rit_offset, rig.rit)
    assert rig.key() == 14074000, "split ignored on transmit"
    press_rit(link, rig); run()
    assert not m.rit and rig.f["a"] == 7074000, (m.rit, rig.f["a"])

@case("split: the transmit swap does not disturb the app's RIT")
def _():
    assert "toggle_rit_for_operator" in mf, "no RIT kept by the app"
    m, rig, link, run = setup()
    rig.toggle_split(); run(); press_rit(link, rig); rig.tune(7074300)
    rig.key(); run()
    assert m.rit and m.rit_vfo == "a" and m.rit_offset == 300, (m.rit, m.rit_vfo, m.rit_offset)

@case("split ON with the firmware's RIT on: it carries on as the app's, receive unchanged")
def _():
    assert "toggle_rit_for_operator" in mf, "no RIT kept by the app"
    m, rig, link, run = setup()
    rig.toggle_rit(); rig.tune(7074300)
    rig.toggle_split(); run()
    assert m.split and m.rit and m.rit_virtual and m.rit_offset == 300, (m.rit, m.rit_offset)
    assert rig.f["a"] == 7074300, "receive moved"
    assert rig.key() == 14074000

@case("split OFF with the app's RIT: it becomes the firmware's real RIT")
def _():
    assert "toggle_rit_for_operator" in mf, "no RIT kept by the app"
    m, rig, link, run = setup()
    rig.toggle_split(); run(); press_rit(link, rig); rig.tune(7074300)
    rig.toggle_split(); run()
    assert not m.split and m.rit and not m.rit_virtual and rig.rit, (m.rit, rig.rit)
    assert rig.rit_tx == 7074000 and m.rit_offset == 300, (rig.rit_tx, m.rit_offset)

@case("exchange with RIT on: A's RIT goes to B with its contents, B's frequency comes to A")
def _():
    assert "exchange_vfos" in mf and "_exchange_now" in mf, "no exchange with RIT"
    m, rig, link, run = setup()
    rig.toggle_rit(); rig.tune(7074300)                  # A: base 7074000, +300
    link.exchange_vfos(); run()
    assert m.rx_vfo == "a" and rig.f["a"] == 14074000 and not m.rit, (rig.f, m.rit)
    assert rig.f["b"] == 7074300, f"B holds {rig.f['b']}"
    rig.toggle_vfo(); run()                               # over to B
    assert m.rit and m.rit_offset == 300 and rig.rit_tx == 7074000, (m.rit, m.rit_offset, rig.rit_tx)

@case("exchange with RIT on both: each RIT changes VFO with its contents")
def _():
    assert "_exchange_now" in mf, "no exchange with RIT"
    m, rig, link, run = setup()
    rig.toggle_rit(); rig.tune(7074300)                  # A +300
    rig.toggle_vfo(); run()
    rig.toggle_rit(); rig.tune(14073800)                 # B -200
    rig.toggle_vfo(); run()                              # back on A (+300 again)
    link.exchange_vfos(); run()
    assert m.rx_vfo == "a" and m.rit and m.rit_offset == -200 and rig.rit_tx == 14074000, \
        (m.rit, m.rit_offset, rig.rit_tx)
    rig.toggle_vfo(); run()
    assert m.rit and m.rit_offset == 300 and rig.rit_tx == 7074000, (m.rit_offset, rig.rit_tx)

@case("exchange with the app's RIT in split: it goes with A's contents, transmit untouched")
def _():
    assert "_exchange_now" in mf, "no exchange with RIT"
    m, rig, link, run = setup()
    rig.toggle_split(); run(); press_rit(link, rig); rig.tune(7074300)
    link.exchange_vfos(); run()
    assert rig.f["b"] == 7074300 and rig.f["a"] == 14074000 and not rig.rit, (rig.f, rig.rit)
    assert getattr(link, "_vrit_saved", {}).get("b") == 7074000, getattr(link, "_vrit_saved", None)

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
