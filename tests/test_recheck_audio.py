"""
A recheck that re-reads the SDR's audio tells the interface (Mark, 2026-11-22:
Brown muted at the last session, uBITX CEC Desktop showing it unmuted).

    python3 test_recheck_audio.py <app folder>
"""
import os, sys, types
folder = sys.argv[1]
sys.path.insert(0, folder)
for name in ("globalvars", "sdr_launcher", "system_audio", "rest_sdr"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["rest_sdr"].RestSDR = object
sys.modules["globalvars"].config = types.SimpleNamespace(config_data={}, saveConfig=lambda: None)
import sdr_link as sl
from sdr_programs import MUTE, VOLUME
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

def link(read_on_recheck):
    """A link whose controller, asked again, reads what read_on_recheck sets."""
    l = sl.SDR_Link.__new__(sl.SDR_Link)
    c = types.SimpleNamespace(is_connected=True, capabilities=frozenset({MUTE, VOLUME}),
                              muted=False, volume=0.5, squelch=None, rf_gain=None,
                              dsp_on={}, dsp_settings={})
    c.discover = lambda: read_on_recheck(c)
    l.controller = c
    l.profile = types.SimpleNamespace(name="SDRoxide Brown")
    heard = []
    l.on_audio = lambda: heard.append("audio")
    l.on_status = lambda connected: heard.append("status")
    return l, heard

@case("muted only by the recheck: the interface is told")
def _():
    l, heard = link(lambda c: setattr(c, "muted", True))
    l.recheck_capabilities()
    assert heard == ["audio"], heard

@case("volume changed by the recheck: the interface is told")
def _():
    l, heard = link(lambda c: setattr(c, "volume", 0.2))
    l.recheck_capabilities()
    assert heard == ["audio"], heard

@case("nothing changed: nothing said")
def _():
    l, heard = link(lambda c: None)
    l.recheck_capabilities()
    assert heard == [], heard

@case("a capability gained: reported as before (which refreshes everything)")
def _():
    def gain(c):
        c.capabilities = frozenset({MUTE, VOLUME, "squelch"}); c.muted = True
    l, heard = link(gain)
    l.recheck_capabilities()
    assert heard == ["status"], heard

print("\n".join(out))
sys.exit(any(o.startswith("FAIL") for o in out))
