"""
The callsign, S-meter settings and command headroom: read from and written to
the rig's EEPROM byte for byte, within the firmware's checksum limit.

    python3 test_rig_settings.py <app folder>
"""
import ast, os, sys, textwrap, types
folder = sys.argv[1]
sys.path.insert(0, folder)
import EEPROM
lsrc = open(os.path.join(folder, "ubitx_link.py")).read()
tree = ast.parse(lsrc)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "uBITX_Link")
NAMES = ("set_rig_bytes", "set_callsign", "_queue_stored", "_mem_spec", "_eeprom_write",
         "_send_cw_write", "_cw_write_timed_out", "_on_cw_written", "_on_memory_written", "_decode_setting",
         "Freq_Encode", "read_settings", "_send_next_setting_request", "_on_setting_reply",
         "_finish_setting_request", "_on_memory_reply", "_setting_read_timed_out")
fns = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in NAMES}
consts = {n.targets[0].id: ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
          and isinstance(n.targets[0], ast.Name)
          and n.targets[0].id in ("RIG_EEPROM", "CALLSIGN_KEY", "CALLSIGN_MAX",
                                   "SMETER_DISPLAY_BIT", "SETTING_READS")}
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

def link():
    sent, timers = [], []
    m = types.SimpleNamespace(eeprom_settings={}, settings_pending={}, cw_pending={},
                              cw_write_failed=None, settings_state="unread", settings_failed=[],
                              channels_state="read", changed=lambda: None)
    l = types.SimpleNamespace(_model=m, memoryQueue=[], **consts,
                              toRadioCommandDict={"TS_CMD_WRITEMEM": 32, "TS_CMD_READMEM": 31})
    l.sendCommandToMCU = lambda b: sent.append(list(b))
    l.root = types.SimpleNamespace(after=lambda ms, f: (timers.append(f), len(timers))[1],
                                   after_cancel=lambda t: None)
    ns = {"EEPROM": EEPROM, "CHANNEL_WRITE_TIMEOUT_MS": 1500, "CHANNEL_READ_TIMEOUT_MS": 800,
          "CHANNEL_READ_RETRIES": 2, "CHANNEL_READ_PACE_MS": 50, "STEP_SETTLE_MS": 150,
          "print": lambda *a, **k: None, "uBITX_Link": types.SimpleNamespace(**consts)}
    for name, node in fns.items():
        exec(textwrap.dedent(ast.get_source_segment(lsrc, node)), ns)
        static = any(getattr(d, "id", "") == "staticmethod" for d in node.decorator_list)
        setattr(l, name, ns[name] if static else types.MethodType(ns[name], l))
    return l, sent, timers

def needs(*names):
    missing = [n for n in names if n not in fns]
    assert not missing, f"missing: {missing}"

@case("every new setting fits the firmware's checksum (address + length < 256)")
def _():
    assert "RIG_EEPROM" in consts, "no RIG_EEPROM"
    for name, spec in consts["RIG_EEPROM"].items():
        assert spec[0] + spec[1] + spec[2] < 256, (name, spec)
    assert 0x0C + 3 + 2 + 18 < 256, "the longest callsign write"

@case("callsign: key, show bit + length, text -- one write at 780")
def _():
    needs("set_callsign")
    l, sent, _ = link(); l.set_callsign("aj6cu", show=True)
    assert sent[0] == [32, 0x0C, 0x03, 7, 0x0C + 3 + 7, 0x59, 0x80 | 5] + list(b"AJ6CU"), sent[0]
    l._on_memory_written(str(780))
    assert l._model.settings_pending["callsign"] == ("AJ6CU", True)
    assert l._model.eeprom_settings["callsign_head"] == [0x59, 0x85]

@case("callsign: empty clears the key; bad characters or too long refused")
def _():
    needs("set_callsign")
    l, sent, _ = link(); l.set_callsign("")
    assert sent[0] == [32, 0x0C, 0x03, 2, 0x0C + 3 + 2, 0, 0], sent[0]
    for bad in ("AJ6 CU", "A" * 19, "AJ6CU!"):
        try: l.set_callsign(bad)
        except ValueError: pass
        else: raise AssertionError(f"{bad!r} accepted")

@case("S-meter levels: 8 bytes at 230; the display option: 1 byte at 361")
def _():
    needs("set_rig_bytes")
    l, sent, timers = link()
    l.set_rig_bytes("smeter_levels", [10, 20, 30, 40, 50, 60, 70, 80])
    assert sent[0] == [32, 0xE6, 0x00, 8, 0xE6 + 8, 10, 20, 30, 40, 50, 60, 70, 80], sent[0]
    l._on_memory_written("230"); timers[-1]()
    l.set_rig_bytes("display_option1", [0x0C])
    assert sent[1] == [32, 0x69, 0x01, 1, 0x69 + 1 + 1, 0x0C], sent[1]
    l._on_memory_written("361")
    assert l._model.eeprom_settings["smeter_levels"] == [10, 20, 30, 40, 50, 60, 70, 80]
    assert set(l._model.settings_pending) == {"smeter_levels", "display_option1"}

@case("reads: the three are asked for, in C byte order, and decoded as bytes")
def _():
    needs("read_settings", "_decode_setting")
    l, sent, timers = link(); l.read_settings()
    names = consts["SETTING_READS"]
    assert {"callsign_head", "display_option1", "smeter_levels"} <= set(names)
    replies = {"callsign_head": "5985", "display_option1": "0c",
               "smeter_levels": "0a141e28323c4650"}
    for name in names:
        l._on_memory_reply(replies.get(name, "00000000")); timers[-1]()
    e = l._model.eeprom_settings
    assert e["callsign_head"] == [0x59, 0x85] and e["display_option1"] == [0x0C], e
    assert e["smeter_levels"] == [10, 20, 30, 40, 50, 60, 70, 80], e["smeter_levels"]
    asked = [c for c in sent if c[1:3] == [0xE6, 0x00]]
    assert asked == [[31, 0xE6, 0x00, 8, 0x59]], asked

@case("headroom: the link paces commands by its own setting")
def _():
    assert 'getattr(self, "command_headroom", MCU_COMMAND_HEADROOM)' in lsrc, "still hardcoded"

# --- the app's helpers -------------------------------------------------------
asrc = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()
acls = next(n for n in ast.parse(asrc).body if isinstance(n, ast.ClassDef) and n.name == "UbitxCecDesktop")
af = {n.name: n for n in acls.body if isinstance(n, ast.FunctionDef)
      and n.name in ("_headroom_setting", "_rig_callsign", "_smeter_levels_entered",
                     "_smeter_levels_problem")}

def app(headroom=None, seen=()):
    w = types.SimpleNamespace(model=types.SimpleNamespace(callsign="AJ6CU/9"),
                              connection=types.SimpleNamespace(seen_reports=set(seen)))
    cfg = types.SimpleNamespace(get_MCU_Command_Headroom=lambda: headroom)
    ns = {"gv": types.SimpleNamespace(config=cfg), "MCU_COMMAND_HEADROOM": .04,
          "MCU_COMMAND_HEADROOM_MAX": .2}
    for name, node in af.items():
        exec(textwrap.dedent(ast.get_source_segment(asrc, node)), ns)
        static = any(getattr(d, "id", "") == "staticmethod" for d in node.decorator_list)
        setattr(w, name, ns[name] if static else types.MethodType(ns[name], w))
    return w

@case("headroom from the settings, kept between 40 and 200 ms")
def _():
    assert "_headroom_setting" in af, "no setting"
    assert app(0.09)._headroom_setting() == 0.09
    assert app(0.01)._headroom_setting() == 0.04 and app(5)._headroom_setting() == 0.2
    assert app(None)._headroom_setting() == 0.04 and app("x")._headroom_setting() == 0.04

@case("the callsign shown is the rig's, never the model's seed")
def _():
    assert "_rig_callsign" in af, "no _rig_callsign"
    assert app()._rig_callsign() == "" and app(seen={"sc"})._rig_callsign() == "AJ6CU/9"

@case("S-meter levels: left as the rig has them, nothing is checked or written")
def _():
    assert "_smeter_levels_entered" in af, "levels always checked"
    w = app()
    erased = [255] * 8                                   # do not rise
    assert w._smeter_levels_entered([str(v) for v in erased], erased) == (None, None)

@case("S-meter levels: changed ones are checked, and written when sound")
def _():
    assert "_smeter_levels_entered" in af, "levels always checked"
    w = app(); rig = [0] * 8
    good = ["10", "20", "30", "40", "50", "60", "70", "80"]
    assert w._smeter_levels_entered(good, rig) == ([10, 20, 30, 40, 50, 60, 70, 80], None)
    assert w._smeter_levels_entered(["5"] * 8, rig)[1] and w._smeter_levels_entered(["x"] * 8, rig)[1]

# --- the adjustable timings --------------------------------------------------
@case("timing: applied to the link's constants, kept in range, defaults otherwise")
def _():
    import importlib
    sys.modules.setdefault("serial", types.SimpleNamespace(Serial=object, SerialException=Exception))
    sys.modules.setdefault("scustomtkinter", types.SimpleNamespace(sCTkMessagebox=None))
    link_mod = importlib.import_module("ubitx_link")
    assert hasattr(link_mod, "apply_timing"), "no adjustable timing"
    used = link_mod.apply_timing({"STEP_SETTLE_MS": "300", "FREQ_FOLLOW_MS": 9999,
                                  "CHANNEL_READ_RETRIES": "x"})
    assert link_mod.STEP_SETTLE_MS == 300 and used["STEP_SETTLE_MS"] == 300
    assert link_mod.FREQ_FOLLOW_MS == 500, link_mod.FREQ_FOLLOW_MS      # kept in range
    assert link_mod.CHANNEL_READ_RETRIES == 2                          # unreadable: default
    link_mod.apply_timing({})
    defaults = {n: d for n, _, d, _, _ in link_mod.TIMING_SETTINGS}
    assert all(getattr(link_mod, n) == d for n, d in defaults.items()), "defaults not restored"
    assert defaults["STEP_SETTLE_MS"] == 150 and defaults["FREQ_CONFIRM_TIMEOUT_MS"] == 500

@case("callsign: not written until the show-at-start-up flag is known")
def _():
    body = asrc.split("def _callsign_entered")[1].split("\n    def ")[0]
    assert "if head is None:" in body and "read_settings()" in body, "writes without the flag"

@case("S-meter levels: all 0, all 255 and not rising each get their own warning")
def _():
    assert "_smeter_levels_problem" in af, "no warning"
    w = app()
    assert "S9" in w._smeter_levels_problem([0] * 8)
    assert "S0" in w._smeter_levels_problem([255] * 8)
    assert "do not rise" in w._smeter_levels_problem([10, 20, 15, 40, 50, 60, 70, 80])
    assert w._smeter_levels_problem([10, 20, 30, 40, 50, 60, 70, 80]) == ""
    assert w._smeter_levels_problem(None) == ""

@case("the operator sees 'radio S-meter sensor', never 'A7'")
def _():
    import re
    shown = re.findall(r'text="([^"]*)"', asrc)
    assert not [t for t in shown if "A7" in t], [t for t in shown if "A7" in t]

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
