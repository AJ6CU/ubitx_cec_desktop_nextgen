"""
With the rig's RIT on, an SDR without RIT of its own (SDRangel, SDR++, Gqrx)
is tuned where the rig listens -- base plus offset; one with RIT (Brown) is
sent the base, its J carrying the offset.

    python3 test_sdr_rit_tuning.py <app folder>
"""
import sys, types
sys.path.insert(0, sys.argv[1])
for name in ("globalvars", "sdr_launcher", "system_audio", "rest_sdr"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["rest_sdr"].RestSDR = object
sys.modules["globalvars"].config = types.SimpleNamespace()
import sdr_link as sl
from sdr_programs import RIT, FREQUENCY
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

class Controller:
    def __init__(self, caps):
        self.capabilities, self.sent, self.has_bandwidth = frozenset(caps), [], True
    def set_frequency(self, hz, band=None): self.sent.append(hz); return True
    def set_mode(self, *a, **k): return True
    def set_bandwidth(self, w): return True
    def default_filter_width(self, m): return 2400
    def __getattr__(self, n): return lambda *a, **k: None

def link(caps):
    m = types.SimpleNamespace(rx_vfo="a", rit=True, rit_base_hz=7094000, rit_offset=300,
                              transmitting=False, split=False)
    m.role_frequency = lambda r: 7094300
    m.mode_of = lambda w: "USB"
    l = sl.SDR_Link.__new__(sl.SDR_Link)
    l.controller = Controller(caps); l._model = m
    l._rig = types.SimpleNamespace()
    l.root = types.SimpleNamespace(after=lambda ms, f: None)
    l.profile = types.SimpleNamespace(to_sdr={"USB": "USB"})
    for a in ("_sent_hz", "_sent_mode", "_sent_vfo", "_sent_other_hz", "_vfo_pending",
              "_qsy", "_rig_mode_asked", "_rit_rx_asked"):
        setattr(l, a, None)
    l._decoding = False
    l._follow_rit = lambda: None
    l._follow_split = lambda: None
    l._framing_for = lambda hz: None
    l._band_of = lambda hz: None
    type(l).connected = property(lambda self: True)
    type(l).capabilities = property(lambda self: self.controller.capabilities)
    type(l).has_bandwidth = property(lambda self: True)
    return l

@case("SDRangel/SDR++ (no RIT): tuned to 7.094.300, where the rig listens")
def _():
    l = link({FREQUENCY}); l.follow()
    assert l.controller.sent == [7094300], l.controller.sent

@case("Brown (RIT): sent the base 7.094.000; J carries the 300")
def _():
    l = link({FREQUENCY, RIT}); l.follow()
    assert l.controller.sent == [7094000], l.controller.sent

@case("a span change re-centres on the same: listening frequency without RIT")
def _():
    l = link({FREQUENCY}); l._pending_bandwidth = 48000; l._apply_bandwidth()
    assert l.controller.sent == [7094300], l.controller.sent

@case("... and the base with RIT")
def _():
    l = link({FREQUENCY, RIT}); l._pending_bandwidth = 48000; l._apply_bandwidth()
    assert l.controller.sent == [7094000], l.controller.sent

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)}/{len(out)}")
