"""
The scanner holds on a channel with a signal, and the rig's S-meter reaches
the model.

    python3 test_scan_signal.py <app folder>
"""
import ast, os, sys, textwrap, types
folder = sys.argv[1]
sys.path.insert(0, folder)
import scanner as sc

class Clock:
    """Tk's after(), on a clock the test moves -- with time.monotonic tied to it."""
    def __init__(self):
        self.now, self.jobs, self.n = 0.0, {}, 0
    def after(self, ms, fn):
        self.n += 1; self.jobs[self.n] = (self.now + ms / 1000, fn); return self.n
    def after_cancel(self, h): self.jobs.pop(h, None)
    def run(self, seconds):
        end = self.now + seconds
        while True:
            due = [(t, h) for h, (t, f) in self.jobs.items() if t <= end]
            if not due: break
            t, h = min(due); self.now = t; f = self.jobs.pop(h)[1]; f()
        self.now = end

out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

CH = [{"freq": 7000000, "mode": "LSB"}, {"freq": 7100000, "mode": "LSB"}, {"freq": 7200000, "mode": "LSB"}]

def scan(levels, threshold=5, dwell=2):
    """levels: {channel index: S-units}."""
    clock = Clock()
    sc.time.monotonic = lambda: clock.now
    model = types.SimpleNamespace(transmitting=False, heard=None)
    model.role_frequency = lambda role: model.heard
    tuned = []
    def tune_to(hz, mode):
        tuned.append(hz); model.heard = hz       # the rig arrives at once
    s = sc.Scanner(clock, model, types.SimpleNamespace(tune_to=tune_to))
    held = []
    s.on_hold = lambda i, lvl: held.append((i, lvl))
    try:
        s.start(lambda: CH, dwell_seconds=dwell,
                signal=lambda: levels.get(s.index, 0.0), threshold=threshold)
    except TypeError as e:
        raise AssertionError(f"no signal option: {e}")
    s.watch()                                     # the rig reported the first channel
    orig = s._go_to
    def go(i):
        orig(i); s.watch()
    s._go_to = go
    return s, clock, tuned, held

@case("no signal: channel to channel by time, as before")
def _():
    s, clock, tuned, held = scan({})
    clock.run(6.5)
    assert tuned[:4] == [7000000, 7100000, 7200000, 7000000], tuned
    assert held == []

@case("a signal at the threshold holds the scan, past the dwell")
def _():
    s, clock, tuned, held = scan({1: 7.0})
    clock.run(20)
    assert tuned == [7000000, 7100000], tuned
    assert s.holding and held == [(1, 7.0)], (s.holding, held)

@case("below the threshold: not held")
def _():
    s, clock, tuned, held = scan({1: 4.0})
    clock.run(6.5)
    assert len(tuned) >= 4 and held == [], (tuned, held)

@case("when the signal drops, it moves on after the hang time")
def _():
    levels = {1: 7.0}
    s, clock, tuned, held = scan(levels)
    clock.run(10); levels[1] = 0.0
    clock.run(sc.SIGNAL_HANG_MS / 1000 - 0.5)
    assert tuned[-1] == 7100000, "moved on before the hang time"
    clock.run(1.0)
    assert tuned[-1] == 7200000 and held[-1] == (1, None), (tuned, held)

@case("a gap shorter than the hang time does not move it on")
def _():
    levels = {1: 7.0}
    s, clock, tuned, held = scan(levels)
    clock.run(10); levels[1] = 0.0; clock.run(1.0); levels[1] = 7.0; clock.run(10)
    assert tuned[-1] == 7100000, tuned

@case("a reading straight after arriving is not believed (the last channel's)")
def _():
    s, clock, tuned, held = scan({0: 9.0}, dwell=sc.SIGNAL_SETTLE_MS / 1000 * 0.5 + 0.0)
    # dwell clamps to the minimum (1 s); the settle window is shorter, so the
    # reading counts -- the point: not before SIGNAL_SETTLE_MS
    clock.run(sc.SIGNAL_SETTLE_MS / 1000 - 0.1)
    assert not s.holding, "believed before the settle time"
    clock.run(0.5)
    assert s.holding, "never held"

@case("stop works while holding")
def _():
    s, clock, tuned, held = scan({1: 7.0})
    clock.run(10); s.stop("stopped")
    assert not s.running and not s.holding and not clock.jobs, clock.jobs

@case("no reading at all (SDR++): by time")
def _():
    clock = Clock(); sc.time.monotonic = lambda: clock.now
    model = types.SimpleNamespace(transmitting=False, role_frequency=lambda r: None)
    tuned = []
    s = sc.Scanner(clock, model, types.SimpleNamespace(tune_to=lambda hz, m: tuned.append(hz)))
    try:
        s.start(lambda: CH, dwell_seconds=2, signal=lambda: None, threshold=5)
    except TypeError as e:
        raise AssertionError(f"no signal option: {e}")
    clock.run(6.5)
    assert len(tuned) >= 4, tuned

@case("skip: on to the next channel now, released from a hold")
def _():
    s, clock, tuned, held = scan({1: 7.0})
    clock.run(10)
    assert hasattr(s, "skip"), "no skip"
    s.skip()
    assert tuned[-1] == 7200000 and not s.holding and held[-1] == (1, None), (tuned, held)
    clock.run(0.5); s.skip()                     # not holding: still moves on
    assert tuned[-1] == 7000000, tuned

@case("skip when not scanning does nothing")
def _():
    s, clock, tuned, held = scan({})
    assert hasattr(s, "skip"), "no skip"
    s.stop(None); n = len(tuned); s.skip()
    assert len(tuned) == n

# --- the rig's S-meter --------------------------------------------------------
lsrc = open(os.path.join(folder, "ubitx_link.py")).read()
ltree = ast.parse(lsrc)
cp = next(n for n in ast.walk(ltree) if isinstance(n, ast.FunctionDef) and n.name == "cp_UX_S_Meter_Value")
ext = next(n for n in ast.walk(ltree) if isinstance(n, ast.FunctionDef) and n.name == "_extract_value")
steps = next((ast.literal_eval(n.value) for n in ast.walk(ltree) if isinstance(n, ast.Assign)
              and getattr(n.targets[0], "id", "") == "RIG_S_STEPS"), None)

def reader():
    r = types.SimpleNamespace(_model=types.SimpleNamespace(s_value=0.0, s_reported=False),
                              RIG_S_STEPS=steps)
    ns = {"print": lambda *a, **k: None}
    for node in (cp, ext):
        exec(textwrap.dedent(ast.get_source_segment(lsrc, node)), ns)
        setattr(r, node.name, types.MethodType(ns[node.name], r))
    return r

@case("the rig's S-meter step reaches the model on the S-unit scale")
def _():
    assert steps is not None, "not wired"
    r = reader()
    r.cp_UX_S_Meter_Value(list("pm.cp.val=8\xff\xff\xff"))
    assert r._model.s_value == steps[8] == 9.0 and r._model.s_reported, r._model.s_value
    r.cp_UX_S_Meter_Value(list("pm.cp.val=0\xff\xff\xff"))
    assert r._model.s_value == 0.0

@case("a bad S-meter value is ignored")
def _():
    assert steps is not None, "not wired"
    r = reader(); r._model.s_value = 3.0
    for bad in ("x", "12", "-1"):
        r.cp_UX_S_Meter_Value(list(f"pm.cp.val={bad}\xff\xff\xff"))
    assert r._model.s_value == 3.0, r._model.s_value

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
