import sys, types, time, traceback
sys.path.insert(0, sys.argv[1])
gv = types.ModuleType("globalvars")
class Cfg:
    def __getattr__(self, n): return lambda *a, **k: 0
gv.config = Cfg(); sys.modules["globalvars"] = gv
import rigctl_sdr, sdr_programs
from rigctl_client import Reply

class FakeClient:
    """A scripted rigctl server: holds f, j, s, and logs commands."""
    def __init__(self, rit=True, j_reply=None, s_reply=None):
        self.f, self.j = 7030000, 0
        self.rit, self.j_reply, self.s_reply = rit, j_reply, s_reply
        self.sent = []
    def connect(self, h, p): return True
    def close(self): pass
    @property
    def connected(self): return True
    def query(self, c, lines=1):
        c = c.strip()
        if c == "f": return Reply(True, [str(self.f)])
        if c == "m": return Reply(True, ["CW", "500"])
        if c == "j":
            if not self.rit: return Reply(False, code=-11)
            if self.j_reply: return self.j_reply
            return Reply(True, [str(self.j)])
        if c == "s":
            return self.s_reply or Reply(True, ["0", "VFOA"])
        return Reply(False, code=-11)
    def command(self, c):
        self.sent.append(c)
        if c.startswith("F "): self.f = int(c.split()[1]); return Reply(True)
        if c.startswith("J "): self.j = int(c.split()[1]); return Reply(True)
        return Reply(False, code=-11)

class Root:
    def after(self, ms, fn): return 1
    def after_cancel(self, i): pass

def make(key, **kw):
    sdr = rigctl_sdr.RigctlSDR(Root(), sdr_programs.profile_for(key))
    sdr._client = FakeClient(**kw)
    seen = []
    sdr.on_frequency = seen.append
    sdr.model_rit_state = lambda: False
    sdr.model_turn_SDR_rit_off = lambda: False
    sdr.model_rit_state_changed = lambda hz, t: None
    sdr.model_update_rit_offset = lambda hz: None
    sdr.model_rit_offset = lambda: 0
    ok = sdr.discover()
    return sdr, seen, ok

results = []
def check(name, fn):
    try:
        fn(); results.append((name, "PASS"))
    except Exception as e:
        results.append((name, f"FAIL {type(e).__name__}: {e}"))

def no_rit_sdr():   # SDR++-like: j refused
    sdr, seen, ok = make("sdr++", rit=False)
    assert ok
    assert sdr.set_frequency(14070000)
    sdr._client.f = 14071000; sdr._settling.clear()
    sdr._poll()
    assert seen == [14071000], seen
check("no-RIT SDR: tune both ways, no crash", no_rit_sdr)

def rit_sign():
    sdr, seen, ok = make("sdroxide")
    assert rigctl_sdr.RIT in sdr.capabilities
    sdr.rit, sdr.rit_offset = True, 500
    sdr._client.f = 7031000
    sdr._poll()
    assert seen and seen[0] == 7031500, seen
check("RIT on, tune in SDR: rig told f + j", rit_sign)

def settle():
    sdr, seen, ok = make("sdroxide")
    sdr.rit_offset = 500
    sdr.profile = types.SimpleNamespace(**{**vars(sdr.profile), "settle_seconds": 3})
    sdr.set_frequency(7030000)
    assert sdr._settling["frequency"][0] == 7030000, sdr._settling
check("set_frequency expects the base back", settle)

def bad_j_discover():
    sdr, seen, ok = make("sdroxide", j_reply=Reply(True, ["120.000000"]))
    assert ok and sdr.rit_offset == 120 and sdr.rit
check("decimal j in discover", bad_j_discover)

def bad_s():
    for r in (Reply(True, ["1"]), Reply(True, ["RPRT -11"]), Reply(True, ["0 VFOB"])):
        sdr, seen, ok = make("sdroxide", s_reply=r)
        assert ok, r
check("odd s replies in discover", bad_s)

def bad_j_poll():
    sdr, seen, ok = make("sdroxide")
    sdr.model_rit_state = lambda: True
    sdr.rit = True
    sdr._client.j_reply = Reply(True, ["junk"])
    sdr._poll()   # must not raise
check("junk j reply in poll", bad_j_poll)

def j_is_command():
    sdr, seen, ok = make("sdroxide")
    sdr.rit, sdr.rit_offset = True, 0
    sdr.model_rit_state = lambda: True
    sdr.model_rit_offset = lambda: 300
    sdr._poll()
    assert "J 300" in sdr._client.sent, sdr._client.sent
check("J sent as a command", j_is_command)

def disconnect_resets():
    sdr, seen, ok = make("sdroxide")
    sdr.rit, sdr.rit_offset = True, 500
    sdr.disconnect()
    assert sdr.rit is False and sdr.rit_offset == 0
check("disconnect forgets RIT", disconnect_resets)

for n, r in results: print(f"{r:6.6}  {n}" if r == "PASS" else f"{r}  -- {n}")
