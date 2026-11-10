"""
ATT and IFS from the RX tab, and "-none-" for the SDR on Setup.

    python3 test_att_ifs.py <app folder>

Runs ubitx_link's handlers and setters and the app's own methods, lifted from
the files, against stand-ins -- no rig, no window.
"""
import ast, os, sys, textwrap, types
folder = sys.argv[1]
sys.path.insert(0, folder)

def lift(path, names, cls=None):
    src = open(os.path.join(folder, path)).read()
    tree = ast.parse(src)
    if cls:
        tree = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    found = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names}
    return src, found

def module_consts(path, names):
    src = open(os.path.join(folder, path)).read()
    ns = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets]
            ids = [e.id for t in targets for e in (t.elts if isinstance(t, ast.Tuple) else [t])
                   if isinstance(e, ast.Name)]
            if any(i in names for i in ids):
                exec(ast.get_source_segment(src, node), ns)
    return ns

def bind(obj, src, found, ns):
    for name, node in found.items():
        exec(textwrap.dedent(ast.get_source_segment(src, node)), ns)
        fn = ns[name]
        static = any(getattr(d, "id", "") == "staticmethod" for d in node.decorator_list)
        setattr(obj, name, fn if static else types.MethodType(fn, obj))

LINK = ("vf_UX_ATT_Level", "ci_UX_IFS_State_Set", "vi_UX_IFS_Level", "_extract_value",
        "Set_ATT", "Toggle_IFS", "Set_IFS_Level", "set_att", "set_ifs")
lsrc, lfound = lift("ubitx_link.py", LINK)
consts = module_consts("ubitx_link.py", {"ATT_MAX", "ATT_STEP", "IFS_MIN", "IFS_MAX",
                                         "IFS_STEP", "STEP_SETTLE_MS"})

def link():
    model = types.SimpleNamespace(att_level=0, ifs_on=False, ifs_hz=0)
    sent, later = [], []
    l = types.SimpleNamespace(_model=model, toRadioCommandDict={
        "TS_CMD_ATT": 10, "TS_CMD_IFS": 11, "TS_CMD_IFSVALUE": 12})
    l.sendCommandToMCU = lambda b: sent.append(bytes(b))
    l.root = types.SimpleNamespace(after=lambda ms, f: later.append(f))
    l.Freq_Encode = lambda f: (int(f) & 0xFFFFFFFF).to_bytes(4, "little")
    ns = {"print": lambda *a, **k: None, **consts}
    bind(l, lsrc, lfound, ns)
    return l, model, sent, later

def report(value):
    return list("x" * 10 + value + "yyy")

out = []
def case(name):
    def wrap(fn):
        try: fn(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

@case("the rig's ATT and IFS reports reach the model")
def _():
    l, m, _, _ = link()
    l.vf_UX_ATT_Level(report("50")); l.ci_UX_IFS_State_Set(report("1")); l.vi_UX_IFS_Level(report("-500"))
    assert (m.att_level, m.ifs_on, m.ifs_hz) == (50, True, -500), (m.att_level, m.ifs_on, m.ifs_hz)
    l.vf_UX_ATT_Level(report("0")); l.ci_UX_IFS_State_Set(report("0"))
    assert (m.att_level, m.ifs_on) == (0, False)

@case("a negative IF shift is sent as a signed 32-bit value")
def _():
    l, m, sent, _ = link()
    l.Set_IFS_Level(-500)
    assert sent == [bytes([12]) + (-500 & 0xFFFFFFFF).to_bytes(4, "little")], sent

@case("ATT: rounded to the menu's steps, clamped, sent only when it changes")
def _():
    l, m, sent, _ = link()
    l.set_att(52); l.set_att(999)
    assert sent == [bytes([10, 50, 0, 0, 0]), bytes([10, 250, 0, 0, 0])], sent
    m.att_level = 250; sent.clear(); l.set_att(250)
    assert sent == [], sent

@case("IFS on: the value, then the switch a settle later")
def _():
    l, m, sent, later = link()
    l.set_ifs(True, 512)
    assert sent == [bytes([12]) + (500).to_bytes(4, "little")], sent
    assert len(later) == 1
    later[0]()
    assert sent[-1] == bytes([11, 0, 0, 0, 0]), sent

@case("IFS already on: a new value only; off: the switch only")
def _():
    l, m, sent, later = link()
    m.ifs_on, m.ifs_hz = True, 500
    l.set_ifs(True, -1000)
    assert sent == [bytes([12]) + (-1000 & 0xFFFFFFFF).to_bytes(4, "little")] and later == [], (sent, later)
    sent.clear(); l.set_ifs(False, -1000)
    assert sent == [bytes([11, 0, 0, 0, 0])], sent
    m.ifs_on = False; sent.clear(); l.set_ifs(False, 300)
    assert sent == [], sent

@case("Setup offers -none- first")
def _():
    import types as t
    for name in ("globalvars",):
        sys.modules.setdefault(name, t.ModuleType(name))
    import sdr_programs
    assert sdr_programs.choices()[0] == ("none", "-none-"), sdr_programs.choices()[0]

APP = ("_show_sdr_fields", "_front_end_live")
asrc, afound = lift("ubitx_cec_desktop.py", APP)

class W:
    def __init__(self): self.state = "normal"
    def configure(self, **k): self.state = k.get("state", self.state)

def app(software, listen="Rig", rig="connected", locked=False):
    a = types.SimpleNamespace(sdr_connect_button=W(), sdr_autostart=W(),
                              sdr_host_entry=W(), sdr_port_entry=W(),
                              _ready=True, rig_state=rig, _listen_source=listen,
                              model=types.SimpleNamespace(locked=locked))
    gv = types.SimpleNamespace(config=types.SimpleNamespace(get_sdr_software=lambda: software))
    bind(a, asrc, afound, {"gv": gv})
    return a

@case("-none-: Connect, start it, address and port greyed; a program: live")
def _():
    assert afound.get("_show_sdr_fields"), "no _show_sdr_fields"
    a = app("none"); a._show_sdr_fields()
    states = {n: getattr(a, n).state for n in ("sdr_connect_button", "sdr_autostart",
                                               "sdr_host_entry", "sdr_port_entry")}
    assert set(states.values()) == {"disabled"}, states
    a = app("sdroxide-brown"); a._show_sdr_fields()
    assert a.sdr_connect_button.state == "normal" and a.sdr_port_entry.state == "normal"

@case("ATT/IFS live only listening through the rig, with a rig, unlocked")
def _():
    assert afound.get("_front_end_live"), "no _front_end_live"
    assert app("none")._front_end_live()
    assert not app("none", listen="SDR")._front_end_live()
    assert not app("none", locked=True)._front_end_live()
    assert not app("none", rig="silent")._front_end_live()

print("\n".join(out))
print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
