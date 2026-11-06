"""
The backup dialog's values: the radio's EEPROM settings read and decoded,
and the three columns compared in the same terms.

    python3 test_eeprom_backup.py <app folder>
"""
import ast, os, sys, textwrap, types
folder = sys.argv[1]
sys.path.insert(0, folder)
import EEPROM
lsrc = open(os.path.join(folder, "ubitx_link.py")).read()
ltree = ast.parse(lsrc)
link_cls = next(n for n in ltree.body if isinstance(n, ast.ClassDef) and n.name == "uBITX_Link")
LINK = ("read_settings", "_send_next_setting_request", "_setting_read_timed_out",
        "_finish_setting_request", "_on_setting_reply", "_decode_setting", "_on_memory_reply")
lf = {n.name: n for n in link_cls.body if isinstance(n, ast.FunctionDef) and n.name in LINK}
reads = next((ast.literal_eval(n.value) for n in link_cls.body if isinstance(n, ast.Assign)
              and getattr(n.targets[0], "id", "") == "SETTING_READS"), None)
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

def link():
    sent, timers = [], []
    m = types.SimpleNamespace(settings_state="unread", settings_failed=[], eeprom_settings={},
                              channels_state="read", changed=lambda: None)
    l = types.SimpleNamespace(_model=m, memoryQueue=[], SETTING_READS=reads,
                              toRadioCommandDict={"TS_CMD_READMEM": 31})
    l.sendCommandToMCU = lambda b: sent.append(list(b))
    l.root = types.SimpleNamespace(after=lambda ms, f: (timers.append(f), len(timers))[1],
                                   after_cancel=lambda t: None)
    ns = {"EEPROM": EEPROM, "CHANNEL_READ_TIMEOUT_MS": 800, "CHANNEL_READ_RETRIES": 2,
          "CHANNEL_READ_PACE_MS": 50, "print": lambda *a, **k: None}
    for name, node in lf.items():
        exec(textwrap.dedent(ast.get_source_segment(lsrc, node)), ns)
        static = any(getattr(d, "id", "") == "staticmethod" for d in node.decorator_list)
        setattr(l, name, ns[name] if static else types.MethodType(ns[name], l))
    return l, sent, timers

@case("the seven reads go out one at a time, to EEPROM.py's addresses")
def _():
    assert "read_settings" in lf, "no read_settings"
    l, sent, timers = link(); l.read_settings()
    assert sent == [[31, 0x00, 0x0, 4, 0x48]], sent          # master cal first
    replies = {"master_cal": "000243B7", "ssb_bfo": "00A8B726", "cw_bfo": "00A8B2BA",
               "factory_master_cal": "00014D67", "factory_ssb_bfo": "00A8B9A0",
               "factory_cw_wpm": "50", "factory_cw_sidetone": "00000258"}
    for name in reads:
        l._on_memory_reply(replies[name]); timers[-1]()
    assert len(sent) == 7 and l._model.settings_state == "read", (len(sent), l._model.settings_state)
    e = l._model.eeprom_settings
    assert e["master_cal"] == 148407 and e["factory_master_cal"] == 85351, e
    assert e["factory_cw_wpm"] == 15 and e["factory_cw_sidetone"] == 600, e

@case("calibration is signed; erased EEPROM is no value")
def _():
    assert "_decode_setting" in lf, "no _decode_setting"
    l, _, _ = link()
    assert l._decode_setting("master_cal", "FFFFFF9C") == -100
    assert l._decode_setting("ssb_bfo", "FFFFFFFF") is None
    assert l._decode_setting("factory_cw_wpm", "FF") is None
    assert l._decode_setting("factory_cw_wpm", "0") is None

@case("no reply: retried, then given up on and the rest still read")
def _():
    assert "read_settings" in lf, "no read_settings"
    l, sent, timers = link(); l.read_settings()
    for _ in range(3):
        timers[-1]()                                         # timeouts
    timers[-1]()                                             # the pace, then the next read
    assert l._model.settings_failed == ["master_cal"], l._model.settings_failed
    assert sent[-1][1] == 0x08, sent[-1]                     # ssb bfo next

@case("not while the channels are being read")
def _():
    assert "read_settings" in lf, "no read_settings"
    l, sent, _ = link(); l._model.channels_state = "reading"; l.read_settings()
    assert sent == [] and l._model.settings_state == "unread"

# --- the dialog's columns ---------------------------------------------------
asrc = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()
acls = next(n for n in ast.parse(asrc).body if isinstance(n, ast.ClassDef) and n.name == "UbitxCecDesktop")
af = {n.name: n for n in acls.body if isinstance(n, ast.FunctionDef)
      and n.name in ("_backup_values", "_backup_normal", "_backup_text")}
rows = next((n for n in acls.body if isinstance(n, ast.Assign)
             and getattr(n.targets[0], "id", "") == "BACKUP_ROWS"), None)
keyers = next((ast.literal_eval(n.value) for n in acls.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "CW_KEYERS"), None)

def window(config):
    cfg = types.SimpleNamespace(**{k: (lambda v=v: v) for k, v in config.items()})
    w = types.SimpleNamespace(BACKUP_ROWS=ast.literal_eval(rows.value), CW_KEYERS=keyers)
    w.model = types.SimpleNamespace(
        eeprom_settings={"master_cal": 148407, "factory_master_cal": 85351, "ssb_bfo": 11056934,
                         "factory_ssb_bfo": 11057568, "cw_bfo": 11055802,
                         "factory_cw_wpm": 15, "factory_cw_sidetone": 600},
        cw_tone=600, cw_tone_reported=True, cw_key_type="IAMBICA", cw_wpm=12,
        cw_delay_tx_ms=260, cw_delay_rx_ms=1010)
    ns = {"gv": types.SimpleNamespace(config=cfg)}
    for name, node in af.items():
        exec(textwrap.dedent(ast.get_source_segment(asrc, node)), ns)
        setattr(w, name, types.MethodType(ns[name], w))
    return w

@case("each row: factory, radio, file -- factory only where the rig keeps one")
def _():
    assert rows is not None and "_backup_values" in af, "still the mock-up"
    w = window({"get_Master_Cal": "148407", "get_SSB_BFO": 11056934, "get_CW_BFO": "11055802",
                "get_Keytype": "Iambic A", "get_CW_Speed": "10", "get_CW_Tone": 600,
                "get_CW_Delay_Before_TX": "260", "get_CW_Delay_Returning_to_RX": 1010})
    v = w._backup_values()
    assert v[0] == (85351, 148407, 148407), v[0]
    assert v[2] == (None, 11055802, 11055802), v[2]
    assert v[3] == (None, "IAMBICA", "IAMBICA"), v[3]          # "Iambic A" in the file
    assert v[4] == (15, 12, 10), v[4]                          # a real difference
    assert w._backup_text("cw_key_type", "IAMBICA") == "Iambic A"

@case("a value missing from the file shows as not known, not an error")
def _():
    assert rows is not None and "_backup_values" in af, "still the mock-up"
    w = window({})
    assert all(c is None for _, _, c in w._backup_values())

@case("factory values are never written: no row has a factory setter")
def _():
    assert rows is not None, "still the mock-up"
    for row in ast.literal_eval(rows.value):
        assert not row[4].lower().startswith("set_factory"), row

# --- restore: the link's set_stored ------------------------------------------
SF = ("set_stored", "_send_cw_write", "_cw_write_timed_out", "_on_cw_written", "_on_memory_written",
      "_eeprom_write", "Freq_Encode", "restart_rig")
sf = {n.name: n for n in link_cls.body if isinstance(n, ast.FunctionDef) and n.name in SF}
limits = next((ast.literal_eval(n.value) for n in link_cls.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "STORED_LIMITS"), None)

def writer():
    sent, timers = [], []
    m = types.SimpleNamespace(eeprom_settings={"master_cal": 148407}, settings_pending={},
                              cw_pending={}, cw_write_failed=None, changed=lambda: None)
    l = types.SimpleNamespace(_model=m, STORED_LIMITS=limits,
                              toRadioCommandDict={"TS_CMD_WRITEMEM": 32})
    l.sendCommandToMCU = lambda b: sent.append(list(b))
    l.reboot_ubitx = lambda: sent.append("reboot")
    l.Set_Tuning_Preset = lambda n: sent.append("preset")
    l.root = types.SimpleNamespace(after=lambda ms, f: (timers.append(f), len(timers))[1],
                                   after_cancel=lambda t: None)
    ns = {"EEPROM": EEPROM, "CHANNEL_WRITE_TIMEOUT_MS": 1500, "CHANNEL_READ_RETRIES": 2,
          "STEP_SETTLE_MS": 150, "REBOOT_SETTLE": 0.25, "print": lambda *a, **k: None}
    for name, node in sf.items():
        exec(textwrap.dedent(ast.get_source_segment(lsrc, node)), ns)
        setattr(l, name, types.MethodType(ns[name], l))
    return l, sent, timers

@case("restore: a negative calibration goes as 32-bit two's complement to 0x000")
def _():
    assert "set_stored" in sf, "no set_stored"
    l, sent, _ = writer(); l.set_stored("master_cal", -100)
    assert sent == [[32, 0x00, 0x00, 4, 4, 0x9C, 0xFF, 0xFF, 0xFF]], sent
    assert l._model.eeprom_settings["master_cal"] == 148407, "changed before the rig confirmed"
    l._on_memory_written("0")
    assert l._model.eeprom_settings["master_cal"] == -100 and l._model.settings_pending == {"master_cal": -100}

@case("restore: the SSB BFO to 0x008, waiting on a restart; the restart clears it")
def _():
    assert "set_stored" in sf, "no set_stored"
    l, sent, _ = writer(); l.set_stored("ssb_bfo", 11056934)
    v = 11056934
    assert sent[0] == [32, 0x08, 0x00, 4, 12, v & 255, (v >> 8) & 255, (v >> 16) & 255, 0], sent[0]
    l._on_memory_written("8"); assert l._model.settings_pending == {"ssb_bfo": v}
    l.restart_rig(); assert l._model.settings_pending == {}, "not cleared by the restart"

@case("restore: out of range is refused, nothing sent")
def _():
    assert "set_stored" in sf, "no set_stored"
    l, sent, _ = writer()
    for name, bad in (("master_cal", 900000), ("cw_bfo", 5000000)):
        try: l.set_stored(name, bad)
        except ValueError: pass
        else: raise AssertionError(f"{name} {bad} accepted")
    assert sent == [], sent

@case("restore: the factory values cannot be written -- no writer knows them")
def _():
    assert limits is not None, "no STORED_LIMITS"
    assert not any(k.startswith("factory") for k in limits), limits

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
