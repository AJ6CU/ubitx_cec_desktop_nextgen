"""
sdr_programs.set_user_setting -- the CW port written into your own file.

    python3 test_decoder_port.py <app folder>
"""
import sys, os, json, tempfile, importlib
sys.path.insert(0, '.')
# sys.path.insert(0, sys.argv[1])
tmp = tempfile.mkdtemp()
import app_paths
app_paths.config_path = lambda name: os.path.join(tmp, name)   # your folder -> a scratch one
import sdr_programs
importlib.reload(sdr_programs)
user = sdr_programs.USER_FILE
assert user.startswith(tmp), user

out = []
def case(name):
    def wrap(fn):
        try:
            if os.path.exists(user): os.remove(user)
            fn(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

key = next(k for k, p in sdr_programs.PROFILES.items() if p.decoder_udp_port)
usual = sdr_programs.shipped_setting(key, "decoder_udp_port")

@case(f"a port saved for {key} is used, and only for it")
def _():
    p = sdr_programs.set_user_setting(key, "decoder_udp_port", 9123)
    assert p.decoder_udp_port == 9123
    assert sdr_programs.profile_for(key).decoder_udp_port == 9123
    others = [k for k, q in sdr_programs.PROFILES.items() if k != key and q.decoder_udp_port == 9123]
    assert not others, others
    assert json.load(open(user)) == {key: {"decoder_udp_port": 9123}}

@case("None puts the usual port back, and the empty entry goes")
def _():
    sdr_programs.set_user_setting(key, "decoder_udp_port", 9123)
    p = sdr_programs.set_user_setting(key, "decoder_udp_port", None)
    assert p.decoder_udp_port == usual, (p.decoder_udp_port, usual)
    assert json.load(open(user)) == {}

@case("the rest of your file is kept, comments included")
def _():
    json.dump({"_note": "mine", key: {"settle_seconds": 2}, "other": {"x": 1}}, open(user, "w"))
    sdr_programs.set_user_setting(key, "decoder_udp_port", 9124)
    data = json.load(open(user))
    assert data["_note"] == "mine" and data["other"] == {"x": 1}, data
    assert data[key] == {"settle_seconds": 2, "decoder_udp_port": 9124}, data[key]

@case("a file that cannot be read is left alone")
def _():
    open(user, "w").write("{ not json")
    assert sdr_programs.set_user_setting(key, "decoder_udp_port", 9125) is None
    assert open(user).read() == "{ not json"

print("\n".join(out))
print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
