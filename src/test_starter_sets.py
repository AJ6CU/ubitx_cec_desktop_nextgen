"""
Starter sets -- WWV/CHU, CW calling, FT8 -- go into an operator's channels
once, when they have none; and the scan's hold level is kept.

    python3 test_starter_sets.py <app folder>
"""
import json, os, sys, tempfile, types
folder = sys.argv[1]
sys.path.insert(0, folder)
sys.modules["app_paths"] = types.SimpleNamespace(config_path=lambda n: os.path.join(tempfile.gettempdir(), n))
import channel_sets as cs

out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

def fresh(existing=None):
    d = tempfile.mkdtemp(); p = os.path.join(d, "channels.json")
    if existing is not None:
        json.dump(existing, open(p, "w"))
    return cs.ChannelSets(p), p

@case("first start: the three starter sets are added and saved")
def _():
    sets, path = fresh()
    assert hasattr(sets, "add_starter_sets"), "no starter sets"
    assert sets.add_starter_sets() == ["Time signals", "CW calling", "FT8"]
    again = cs.ChannelSets(path)
    assert again.names() == ["Time signals", "CW calling", "FT8"], again.names()
    assert again.channels("FT8")[3] == {"freq_hz": 14074000, "mode": "USB", "label": "20M FT8",
                                        "name": "20 m FT8", "bandwidth": 2600}

@case("only once: deleted starter sets do not come back")
def _():
    sets, path = fresh()
    assert hasattr(sets, "add_starter_sets"), "no starter sets"
    sets.add_starter_sets()
    for n in sets.names():
        sets.delete_set(n)
    again = cs.ChannelSets(path)
    assert again.add_starter_sets() == [] and again.names() == [], again.names()

@case("an operator who already has sets gets none")
def _():
    sets, _ = fresh({"version": 1, "sets": {"MINE": [{"freq_hz": 7100000, "mode": "LSB"}]}})
    assert hasattr(sets, "add_starter_sets"), "no starter sets"
    assert sets.add_starter_sets() == [] and sets.names() == ["MINE"]

@case("a file with no sets (as now) gets them")
def _():
    sets, _ = fresh({"version": 1, "sets": {}, "scan": {"dwell_seconds": 5}})
    assert hasattr(sets, "add_starter_sets"), "no starter sets"
    assert len(sets.add_starter_sets()) == 3

@case("the starter file is sound: every channel has a frequency, a rig mode, a short label")
def _():
    path = os.path.join(folder, "starter_channels.json")
    data = json.load(open(path))
    for name, chans in data["sets"].items():
        assert chans, name
        for ch in chans:
            assert 3_000_000 <= ch["freq_hz"] <= 30_000_000, ch
            assert ch["mode"] in ("LSB", "USB", "CWL", "CWU"), ch
            assert len(ch["label"]) <= cs.LABEL_MAX, ch

@case("no starter file: nothing added, nothing broken")
def _():
    sets, _ = fresh()
    assert hasattr(sets, "add_starter_sets"), "no starter sets"
    assert sets.add_starter_sets("/nonexistent.json") == [] and sets.names() == []

@case("the hold level is kept between starts, 1 to 9")
def _():
    sets, path = fresh()
    assert hasattr(sets, "set_hold_level"), "not kept"
    assert sets.set_hold_level("7") == 7 and cs.ChannelSets(path).hold_level == 7
    assert sets.set_hold_level(15) == 9 and sets.set_hold_level("x") == 9

@case("backup: the file as it was, kept as .bak before the session's first change")
def _():
    sets, path = fresh({"version": 1, "sets": {"MINE": [{"freq_hz": 7100000, "mode": "LSB"}]}})
    assert hasattr(sets, "backup_path"), "no backup"
    before = open(path).read()
    sets.add("MINE", {"freq_hz": 7200000, "mode": "LSB"})
    sets.add("MINE", {"freq_hz": 7300000, "mode": "LSB"})
    assert open(sets.backup_path).read() == before, "not the file before the session"
    assert len(cs.ChannelSets(path).channels("MINE")) == 3

@case("backup: one only -- the next session's first change replaces it")
def _():
    sets, path = fresh({"version": 1, "sets": {"MINE": []}})
    assert hasattr(sets, "backup_path"), "no backup"
    sets.add("MINE", {"freq_hz": 7200000, "mode": "LSB"})
    middle = open(path).read()
    later = cs.ChannelSets(path); later.delete("MINE", 0)
    assert open(later.backup_path).read() == middle
    assert [f for f in os.listdir(os.path.dirname(path)) if ".bak" in f] == ["channels.json.bak"]

@case("backup: a session that changes nothing leaves it alone")
def _():
    sets, path = fresh({"version": 1, "sets": {"MINE": []}})
    assert hasattr(sets, "backup_path"), "no backup"
    cs.ChannelSets(path).names()
    assert not os.path.exists(sets.backup_path)

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
