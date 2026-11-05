"""
The sampled span over rigctl (SPECTRUM_SPAN), against a fake SDRoxide Brown
that behaves as #479 does: a width becomes the nearest power-of-two
decimation, clamped to what the device carries, applied a moment later.

    python3 test_span.py <app folder>
"""
import sys, types, time, io, contextlib
sys.path.insert(0, ".")
# sys.path.insert(0, sys.argv[1])
gv = types.ModuleType("globalvars")
class Cfg:
    def __getattr__(self, n): return lambda *a, **k: 0
gv.config = Cfg(); sys.modules["globalvars"] = gv
import math
import rigctl_sdr, sdr_programs
from rigctl_client import Reply

rigctl_sdr.SPAN_SETTLE_SECONDS = 0.15
RATE, MAX_DECIM, APPLY_DELAY = 1_536_000, 32, 0.05

class FakeBrown:
    def __init__(self, span=True):
        self.has_span, self.decim, self.pending, self.sent = span, 2, None, []
        self.f = 7_030_000
    def connect(self, h, p): return True
    def close(self): pass
    connected = True
    def _apply(self):
        if self.pending and time.monotonic() >= self.pending[1]:
            self.decim, self.pending = self.pending[0], None
    def query(self, c, lines=1):
        self._apply(); c = c.strip()
        if c == "f": return Reply(True, [str(self.f)])
        if c == "m": return Reply(True, ["USB", "2700"])
        if c == "l SPECTRUM_SPAN":
            return Reply(True, [str(RATE // self.decim)]) if self.has_span else Reply(False, code=-11)
        return Reply(False, code=-11)
    def command(self, c):
        self.sent.append(c); parts = c.split()
        if parts[:2] == ["L", "SPECTRUM_SPAN"]:
            if not self.has_span: return Reply(False, code=-11)
            ratio = RATE / max(1, int(parts[2]))
            d = 2 ** max(0, round(math.log2(ratio))) if ratio > 1 else 1
            self.pending = (min(MAX_DECIM, d), time.monotonic() + APPLY_DELAY)
            return Reply(True)
        if parts[0] == "F": self.f = int(parts[1]); return Reply(True)
        return Reply(True)

class Root:
    def after(self, ms, fn): return 1
    def after_cancel(self, i): pass

def make(span=True, key="sdroxide"):
    prof = sdr_programs.profile_for(key)
    prof = types.SimpleNamespace(**{**vars(prof), "settle_seconds": 0, "known_missing": set()})
    sdr = rigctl_sdr.RigctlSDR(Root(), prof)
    sdr._client = FakeBrown(span)
    seen = []
    sdr.on_bandwidth = seen.append
    sdr.discover()
    return sdr, seen

def poll(sdr, n=1, wait=0.0):
    for _ in range(n):
        if wait: time.sleep(wait)
        with contextlib.redirect_stdout(io.StringIO()):
            sdr._poll()

out = []
def case(name):
    def wrap(fn):
        try: fn(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

@case("found at connect: the span read, the slider offered")
def _():
    sdr, _ = make()
    assert rigctl_sdr.BANDWIDTH in sdr.capabilities and sdr.bandwidth == 768_000, sdr.bandwidth
    ch = sdr.bandwidth_choices()
    assert 768_000 in ch and 1_536_000 in ch and 48_000 in ch and min(ch) >= 48_000, ch
    assert ch == sorted(ch)

@case("no SPECTRUM_SPAN (SDR++, a stock SDRoxide): no slider")
def _():
    sdr, _ = make(span=False)
    assert rigctl_sdr.BANDWIDTH not in sdr.capabilities and sdr.bandwidth_choices() == []
    assert not sdr.set_bandwidth(384_000)

@case("a narrower span: sent, read back once applied")
def _():
    sdr, seen = make()
    assert sdr.set_bandwidth(384_000)
    assert sdr._client.sent[-1] == "L SPECTRUM_SPAN 384000"
    poll(sdr, 6, 0.05)
    assert sdr.bandwidth == 384_000 and sdr._span_max is None and sdr._span_min is None, (sdr.bandwidth, sdr._span_min, sdr._span_max)

@case("the old span read before it applies is not believed (no limit learned)")
def _():
    sdr, seen = make()
    sdr._client_delay = None
    sdr.set_bandwidth(192_000)
    poll(sdr, 1)                               # still 768000: inside the window
    assert sdr.bandwidth == 768_000 and sdr._span_min is None, (sdr.bandwidth, sdr._span_min)
    poll(sdr, 6, 0.05)
    assert sdr.bandwidth == 192_000 and sdr._span_min is None

@case("wider than the device: clamped, and the widest learned")
def _():
    sdr, _ = make()
    sdr.set_bandwidth(3_072_000)
    poll(sdr, 8, 0.05)
    assert sdr.bandwidth == 1_536_000 and sdr._span_max == 1_536_000, (sdr.bandwidth, sdr._span_max)
    assert max(sdr.bandwidth_choices()) == 1_536_000, sdr.bandwidth_choices()

@case("narrower than the decimation allows: the narrowest learned")
def _():
    sdr, _ = make()
    sdr.set_bandwidth(24_000)                  # 1536000 / 64; the fake stops at 32
    poll(sdr, 8, 0.05)
    assert sdr.bandwidth == 48_000 and sdr._span_min == 48_000, (sdr.bandwidth, sdr._span_min)

@case("changed in the SDR itself: followed and reported")
def _():
    sdr, seen = make()
    sdr._client.decim = 8
    poll(sdr, 1)
    assert sdr.bandwidth == 192_000 and seen == [192_000], (sdr.bandwidth, seen)

@case("framing a band no longer raises (band accepted, frequency set)")
def _():
    sdr, _ = make()
    assert sdr.set_frequency(7_000_000, band=(7_000_000, 7_300_000))
    assert sdr._client.f == 7_000_000

@case("the same width again is not sent again")
def _():
    sdr, _ = make()
    assert not sdr.set_bandwidth(768_000)          # already there
    sdr.set_bandwidth(384_000)
    assert not sdr.set_bandwidth(384_000)          # already on its way
    sent = [c for c in sdr._client.sent if c.startswith("L SPECTRUM_SPAN")]
    assert sent == ["L SPECTRUM_SPAN 384000"], sent
    poll(sdr, 6, 0.05)
    assert not sdr.set_bandwidth(384_000)          # arrived
    assert sdr.set_bandwidth(768_000)              # a real change still goes

@case("disconnect forgets the span and its limits")
def _():
    sdr, _ = make()
    sdr._span_max = 1_536_000
    sdr.disconnect()
    assert sdr.bandwidth is None and sdr._span_max is None

print("\n".join(out))
print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
