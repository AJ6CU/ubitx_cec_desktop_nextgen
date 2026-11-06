"""
The keyer values the rig reports from EEPROM reach the model and the CW tab.

    python3 test_cw_values.py <app folder>

Runs ubitx_link's own handlers and the app's _show_cw, lifted from the files,
against stand-ins -- no rig, no window.
"""
import ast, os, sys, textwrap, types
folder = sys.argv[1]

def lift(path, names, cls=None):
    src = open(os.path.join(folder, path)).read()
    tree = ast.parse(src)
    if cls:
        tree = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    found = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names}
    return src, tree, found

LINK = ("vt_UX_SET_CW_Tone", "ck_UX_Set_CW_Key_Type", "vs_UX_Set_CW_Speed",
        "vy_UX_Set_CW_Delay_Returning_to_RX", "ve_UX_Set_CW_Delay_Starting_TX",
        "_extract_value", "_cw_key_word", "_cw_number")
src, _, found = lift("ubitx_link.py", LINK)

def reader():
    model = types.SimpleNamespace(cw_tone=600, cw_tone_reported=False, cw_key_type=None,
                                  cw_wpm=None, cw_delay_tx_ms=None, cw_delay_rx_ms=None,
                                  cw_pending={})
    r = types.SimpleNamespace(_model=model)
    ns = {"print": lambda *a, **k: None}
    for name, node in found.items():
        code = textwrap.dedent(ast.get_source_segment(src, node))
        decorated = any(getattr(d, "id", "") == "staticmethod" for d in node.decorator_list)
        exec(code, ns)
        fn = ns[name]
        setattr(r, name, fn if decorated else types.MethodType(fn, r))
    return r

def report(value):
    return list("x" * 10 + value + "yyy")

out = []
def case(name):
    def wrap(fn):
        try: fn(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

@case("the reports are stored in the operator's units")
def _():
    r = reader()
    r.vt_UX_SET_CW_Tone(report("700")); r.vs_UX_Set_CW_Speed(report("60"))
    r.ve_UX_Set_CW_Delay_Starting_TX(report("25")); r.vy_UX_Set_CW_Delay_Returning_to_RX(report("50"))
    r.ck_UX_Set_CW_Key_Type(report("2"))
    m = r._model
    got = (m.cw_tone, m.cw_tone_reported, m.cw_wpm, m.cw_delay_tx_ms, m.cw_delay_rx_ms, m.cw_key_type)
    assert got == (700, True, 20, 50, 500, "IAMBICB"), got

@case("each key type, as a number or a word")
def _():
    r = reader()
    for sent, want in (("0", "STRAIGHT"), ("1", "IAMBICA"), ("2", "IAMBICB"), ("IAMBICA", "IAMBICA")):
        r.ck_UX_Set_CW_Key_Type(report(sent)); assert r._model.cw_key_type == want, (sent, r._model.cw_key_type)

@case("nonsense is left unknown, not guessed (and speed 0 does not divide by zero)")
def _():
    r = reader()
    r.ck_UX_Set_CW_Key_Type(report("7")); r.vs_UX_Set_CW_Speed(report("0"))
    r.ve_UX_Set_CW_Delay_Starting_TX(report("")); 
    m = r._model
    assert (m.cw_key_type, m.cw_wpm, m.cw_delay_tx_ms) == (None, None, None), (m.cw_key_type, m.cw_wpm, m.cw_delay_tx_ms)

@case("a zero delay is a real value")
def _():
    r = reader(); r.vy_UX_Set_CW_Delay_Returning_to_RX(report("0"))
    assert r._model.cw_delay_rx_ms == 0, r._model.cw_delay_rx_ms

# --- sending: the link's set_cw ---------------------------------------------
sys.path.insert(0, folder)
import EEPROM
SEND = ("set_cw", "_cw_setting", "_send_cw_write", "_cw_write_timed_out", "_on_cw_written",
        "_on_memory_written", "_eeprom_write", "Freq_Encode")
lsrc, ltree, sfound = lift("ubitx_link.py", SEND, cls="uBITX_Link")
link_cls = next(n for n in ast.parse(lsrc).body if isinstance(n, ast.ClassDef) and n.name == "uBITX_Link")
lconsts = {n.targets[0].id: ast.literal_eval(n.value) for n in link_cls.body
           if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in ("CW_KEY_VALUES", "CW_LIMITS")}

def rig():
    sent, timers = [], []
    model = types.SimpleNamespace(cw_tone=600, cw_tone_reported=True, cw_key_type="STRAIGHT",
                                  cw_wpm=12, cw_delay_tx_ms=0, cw_delay_rx_ms=500,
                                  cw_pending={}, cw_write_failed=None, changed=lambda: None)
    l = types.SimpleNamespace(_model=model, **lconsts)
    l.toRadioCommandDict = {"TS_CMD_KEYTYPE": 19, "TS_CMD_WPM": 18, "TS_CMD_WRITEMEM": 32}
    l.sendCommandToMCU = lambda b: sent.append(list(b))
    l.root = types.SimpleNamespace(after=lambda ms, fn: (timers.append(fn), len(timers))[1],
                                   after_cancel=lambda t: None)
    ns = {"EEPROM": EEPROM, "CHANNEL_WRITE_TIMEOUT_MS": 1500, "CHANNEL_READ_RETRIES": 2,
          "STEP_SETTLE_MS": 150, "print": lambda *a, **k: None}
    for name, node in sfound.items():
        exec(textwrap.dedent(ast.get_source_segment(lsrc, node)), ns)
        setattr(l, name, types.MethodType(ns[name], l))
    return l, sent, timers

def ack(l, address):
    l._on_memory_written(str(address))

@case("speed: the command at once (5 bytes), then the dot length to 0x01C")
def _():
    assert "set_cw" in sfound, "no set_cw"
    l, sent, _ = rig(); l.set_cw("cw_wpm", 20)
    assert sent[0] == [18, 60, 0, 0, 0], sent[0]
    assert sent[1] == [32, 0x1C, 0x00, 4, (0x1C + 0 + 4) % 256, 60, 0, 0, 0], sent[1]
    assert l._model.cw_wpm == 12, "changed before the rig confirmed"
    ack(l, 0x1C); assert l._model.cw_wpm == 20, l._model.cw_wpm

@case("key type: the command at once, then one byte to 0x166")
def _():
    assert "set_cw" in sfound, "no set_cw"
    l, sent, _ = rig(); l.set_cw("cw_key_type", "IAMBICB")
    assert sent == [[19, 2, 0, 0, 0], [32, 0x66, 0x01, 1, (0x66 + 1 + 1) % 256, 2]], sent
    ack(l, 0x166); assert l._model.cw_key_type == "IAMBICB"

@case("tone and delays: EEPROM only, waiting on a restart; the live tone untouched")
def _():
    assert "set_cw" in sfound, "no set_cw"
    l, sent, timers = rig()
    l.set_cw("cw_tone", 700); l.set_cw("cw_delay_tx_ms", 25); l.set_cw("cw_delay_rx_ms", 1234)
    assert len(sent) == 1, "the next write went before the first was confirmed"
    assert sent[0] == [32, 0x18, 0x00, 4, (0x18 + 4) % 256, 700 & 255, 700 >> 8, 0, 0], sent[0]
    ack(l, 0x18); timers[-1]()                      # the settle, then the next
    assert sent[1] == [32, 0x03, 0x01, 1, (3 + 1 + 1) % 256, 12], sent[1]
    ack(l, 0x103); timers[-1]()
    assert sent[2] == [32, 0x02, 0x01, 1, (2 + 1 + 1) % 256, 123], sent[2]
    ack(l, 0x102)
    m = l._model
    assert m.cw_tone == 600, "live tone changed before a restart"
    assert m.cw_pending == {"cw_tone": 700, "cw_delay_tx_ms": 24, "cw_delay_rx_ms": 1230}, m.cw_pending

@case("an acknowledgement for another address does not count; giving up marks it")
def _():
    assert "set_cw" in sfound, "no set_cw"
    l, sent, timers = rig(); l.set_cw("cw_tone", 700)
    ack(l, 0x166); assert l._model.cw_pending == {}, "credited to the wrong write"
    for _ in range(3):
        timers.pop(0)()
    assert l._model.cw_write_failed == "cw_tone", l._model.cw_write_failed
    assert sum(1 for c in sent if c[0] == 32) == 3, "not retried twice"

@case("out of range is refused, nothing sent")
def _():
    assert "set_cw" in sfound, "no set_cw"
    l, sent, _ = rig()
    for key, bad in (("cw_wpm", 2), ("cw_tone", 5000), ("cw_delay_rx_ms", 3000)):
        try: l.set_cw(key, bad)
        except ValueError: pass
        else: raise AssertionError(f"{key} {bad} accepted")
    assert sent == [], sent

@case("a report after the restart clears the waiting value")
def _():
    r = reader(); r._model.cw_pending = {"cw_tone": 700, "cw_delay_rx_ms": 500}
    r.vt_UX_SET_CW_Tone(report("700")); r.vy_UX_Set_CW_Delay_Returning_to_RX(report("50"))
    assert r._model.cw_pending == {}, r._model.cw_pending

# --- the tab ---------------------------------------------------------------
asrc = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()
cls = next(n for n in ast.parse(asrc).body if isinstance(n, ast.ClassDef) and n.name == "UbitxCecDesktop")
show = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_show_cw"), None)
keyers = next((ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "CW_KEYERS"), None)

class Entry:
    def __init__(self): self.text, self.state = "500", "normal"
    def configure(self, state): self.state = state
    def get(self): return self.text
    def delete(self, a, b):
        assert self.state == "normal", "written while read-only"; self.text = ""
    def insert(self, i, t):
        assert self.state == "normal", "written while read-only"; self.text = t

class Seg:
    def __init__(self): self.value, self.state = "", "normal"
    def set(self, v): self.value = v
    def configure(self, state): self.state = state

class Note:
    def __init__(self): self.text, self.packed = "", False
    def configure(self, text): self.text = text
    def pack(self, **k): self.packed = True
    def pack_forget(self): self.packed = False

TAB = ("_show_cw", "_cw_values", "_cw_entered", "_cw_keyer_chosen", "_cw_restart_rig")
tab_methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in TAB}
lock_note = next((ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
                  and getattr(n.targets[0], "id", "") == "LOCKED_NOTE"), "locked")

def tab(rig_state="connected", **model):
    asked = []
    w = types.SimpleNamespace(CW_KEYERS=keyers, LOCKED_NOTE=lock_note, _cw_shown=None, _ready=True,
                              rig_state=rig_state,
                              _cw_fields={k: Entry() for k in ("cw_tone", "cw_wpm", "cw_delay_tx_ms", "cw_delay_rx_ms")},
                              _cw_keyer=Seg(), _cw_note=Note(), _cw_restart=Note())
    w.connection = types.SimpleNamespace(set_cw=lambda k, v: asked.append((k, v)),
                                         reboot_ubitx=lambda: asked.append("reboot"))
    base = dict(cw_tone=600, cw_tone_reported=False, cw_key_type=None, cw_wpm=None,
                cw_delay_tx_ms=None, cw_delay_rx_ms=None, cw_pending={}, cw_write_failed=None, locked=False)
    base.update(model); w.model = types.SimpleNamespace(**base)
    ns = {"uBITX_Link": types.SimpleNamespace(**lconsts)}
    for name, node in tab_methods.items():
        exec(textwrap.dedent(ast.get_source_segment(asrc, node)), ns)
        setattr(w, name, types.MethodType(ns[name], w))
    return w, asked

REPORTED = dict(cw_tone=700, cw_tone_reported=True, cw_wpm=20, cw_delay_tx_ms=50,
                cw_delay_rx_ms=500, cw_key_type="IAMBICB")

@case("the tab shows the rig's values, with its key chosen")
def _():
    assert show is not None, "no _show_cw"
    w, _ = tab(**REPORTED); w._show_cw()
    got = [e.text for e in w._cw_fields.values()]
    assert got == ["700", "20", "50", "500"], got
    assert w._cw_keyer.value == "Iambic B", vars(w._cw_keyer)

@case("before the rig reports: '--' and no key, not placeholders")
def _():
    assert show is not None, "no _show_cw"
    w, _ = tab(); w._show_cw()
    assert [e.text for e in w._cw_fields.values()] == ["--"] * 4
    assert w._cw_keyer.value == ""

@case("a later report repaints")
def _():
    assert show is not None, "no _show_cw"
    w, _ = tab(cw_wpm=20); w._show_cw()
    w.model.cw_wpm = 25; w._show_cw()
    assert w._cw_fields["cw_wpm"].text == "25"

@case("typing a speed sends it; an unchanged field sends nothing")
def _():
    assert "_cw_entered" in tab_methods, "not editable"
    w, asked = tab(**REPORTED); w._show_cw()
    w._cw_fields["cw_tone"].text = "700"; w._cw_entered("cw_tone")
    w._cw_fields["cw_wpm"].text = "25"; w._cw_entered("cw_wpm")
    assert asked == [("cw_wpm", 25)], asked

@case("out of range or not a number: refused, field put back")
def _():
    assert "_cw_entered" in tab_methods, "not editable"
    w, asked = tab(**REPORTED); w._show_cw()
    w._cw_fields["cw_tone"].text = "5000"; w._cw_entered("cw_tone")
    w._cw_fields["cw_wpm"].text = "fast"; w._cw_entered("cw_wpm")
    assert asked == [], asked
    assert w._cw_fields["cw_tone"].text == "700" and w._cw_fields["cw_wpm"].text == "20"

@case("choosing a key sends it, the button stays as the rig has it")
def _():
    assert "_cw_keyer_chosen" in tab_methods, "not editable"
    w, asked = tab(**REPORTED); w._show_cw()
    w._cw_keyer.value = "Straight"; w._cw_keyer_chosen("Straight")
    assert asked == [("cw_key_type", "STRAIGHT")] and w._cw_keyer.value == "Iambic B", (asked, w._cw_keyer.value)

@case("locked, or no rig: read-only, nothing sent")
def _():
    assert "_cw_entered" in tab_methods, "not editable"
    for kw in (dict(locked=True), dict(rig_state="failed")):
        w, asked = tab(**{**REPORTED, **kw}); w._show_cw()
        assert all(e.state == "readonly" for e in w._cw_fields.values()), kw
        assert w._cw_keyer.state == "disabled", kw
        w._cw_entered("cw_wpm"); w._cw_keyer_chosen("Straight")
        assert asked == [], (kw, asked)

@case("a saved tone shows, says it waits on a restart, and offers one")
def _():
    assert "_cw_restart_rig" in tab_methods, "no restart"
    w, asked = tab(**{**REPORTED, "cw_pending": {"cw_tone": 750}}); w._show_cw()
    assert w._cw_fields["cw_tone"].text == "750", w._cw_fields["cw_tone"].text
    assert "restart" in w._cw_note.text and w._cw_restart.packed, w._cw_note.text
    w._cw_restart_rig(); assert asked == ["reboot"], asked
    w.model.cw_pending = {}; w._show_cw()
    assert not w._cw_restart.packed and w._cw_note.text == "", "still offered"

print("\n".join(out))
print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
