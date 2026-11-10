"""
SDRangel 8.1.0's REST fixes are used, and 7.x keeps its workarounds.

    python3 test_sdrangel_version.py <folder with rest_sdr.py, sdr_controls.py/.json>
"""
import os, sys, types, importlib
folder = os.path.abspath(sys.argv[1])
sys.path.insert(0, folder)
sys.path.insert(1, "/home/claude/app")
sys.modules["globalvars"] = types.SimpleNamespace(config=None)
import builtins
_print = builtins.print
said = []
builtins.print = lambda *a, **k: said.append(" ".join(map(str, a)))
rest_sdr = importlib.import_module("rest_sdr")
builtins.print = _print
from sdr_programs import MODE, NR

out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

class FakeClient:
    def __init__(self, version):
        self.version, self.patches, self.connected = version, [], False
        self.info = None
    def open(self, host, port):
        self.connected = True
        self.info = {"appname": "SDRangel"} | ({"version": self.version} if self.version else {})
        return True
    def close(self): self.connected = False
    def patch(self, path, body):
        self.patches.append(body); return True

def sdr(version, channel="WDSPRx"):
    s = rest_sdr.RestSDR.__new__(rest_sdr.RestSDR)
    root = types.SimpleNamespace(after=lambda ms, f: None, after_cancel=lambda i: None)
    rest_sdr.RestSDR.__init__(s, root, types.SimpleNamespace(name="SDRangel"))
    s._client = FakeClient(version)
    # connect() as far as the version: open, then read it -- discover() stubbed.
    s.discover = lambda: True
    builtins.print = lambda *a, **k: said.append(" ".join(map(str, a)))
    try:
        s.connect("127.0.0.1", 8091)
    finally:
        builtins.print = _print
    s._set_index, s._channel_index = 0, 0
    s._channel_type, s._channel_key = channel, channel + "Settings"
    s.capabilities = frozenset({MODE, NR})
    s._sideband, s._low, s._high = "U", 0, 3000
    s._span_log2 = 3
    return s

def fields(s):
    return [list(b.values())[-1] for b in s._client.patches]

@case("8.1.0: WDSP passband written a cut at a time, and checked")
def _():
    s = sdr("8.1.0")
    assert s._write_passband("LSB", 3000)
    f = fields(s)
    assert len(f) == 3 and f[0] == {"lowCutoff": 0}, f
    assert s._passband_check is not None, "read-back not checked"
    assert s._written_passband is None

@case("8.1.0: other PATCHes do not carry a passband")
def _():
    s = sdr("8.1.0")
    s._write_passband("LSB", 3000)
    s._client.patches.clear()
    s._patch_channel({"agc": 1})
    assert fields(s) == [{"agc": 1}], fields(s)

@case("7.27.2-1315: WDSP passband still in one PATCH, riding along")
def _():
    s = sdr("7.27.2-1315")
    assert s._write_passband("LSB", 3000)
    assert fields(s) == [{"rfBandwidth": -3000, "lowCutoff": 0}], fields(s)
    s._client.patches.clear()
    s._patch_channel({"agc": 1})
    assert fields(s) == [{"agc": 1, "rfBandwidth": -3000, "lowCutoff": 0}], fields(s)

@case("no version given: taken as old -- workaround kept")
def _():
    s = sdr(None)
    s._write_passband("LSB", 3000)
    assert len(fields(s)) == 1, fields(s)

@case("SSB demodulator NR scheme live on 8.1.0, shown only on 7.x")
def _():
    new, old = sdr("8.1.0", "SSBDemod"), sdr("7.27.2", "SSBDemod")
    for s in (new, old):
        s.dsp_settings = {"nr": {"scheme": 0, "avg": 40, "sigma": 4, "peaks": 20, "alpha": 1}}
    assert new.dsp_adjustable("nr", "scheme")
    assert new.set_dsp_setting("nr", "scheme", 2)
    assert fields(new) == [{"dnrScheme": 2}], fields(new)
    assert not old.dsp_adjustable("nr", "scheme")
    assert not old.set_dsp_setting("nr", "scheme", 2) and fields(old) == []

@case("WDSP report still never read, on 8.1.0 too (frozen value)")
def _():
    s = sdr("8.1.0")
    s._client.get = lambda path: (_ for _ in ()).throw(AssertionError("report read"))
    assert s._read_report(0, 0) is None

@case("the version is said at connect")
def _():
    said.clear(); sdr("8.1.0")
    assert any("SDRangel 8.1.0" in line for line in said), said

@case("parse_version")
def _():
    import sdr_controls
    pv = sdr_controls.parse_version
    assert pv("8.1.0") == (8, 1, 0) and pv("7.27.2-1315") == (7, 27, 2)
    assert pv("v8.0") == (8, 0) and pv(None) is None and pv("abc") is None
    assert pv("8.0") < (8, 1, 0) and pv("8.1.0") >= (8, 1, 0)

print("\n".join(out))
print(f"{sum(l.startswith('PASS') for l in out)}/{len(out)}")
