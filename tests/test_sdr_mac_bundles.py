"""
On a Mac, SDRoxide and SDRoxide Brown are told apart by their bundle ids.

    python3 test_sdr_mac_bundles.py <app folder>

Brown's fix for #752 (2026-11-19, merged as #753) renamed its bundle
sdroxide-brown.app, with its own CFBundleIdentifier
(com.github.madmedicnl.sdroxide-brown); upstream stays sdroxide.app
(com.github.dividebysandwich.sdroxide). BOTH executables are still called
"sdroxide", so the process name can't tell them apart -- Mark: "ps ax | grep
sdroxide returns sdroxide ... and so it doesn't close even though it
started". The app asked "sdroxide" to quit, which is no longer Brown's name.

Here the Mac is pretended (sdr_launcher._system), the two bundles are real
folders with real Info.plists, and psutil and osascript are stand-ins.
"""
import os, plistlib, sys, tempfile, types

folder = os.path.abspath(sys.argv[1])
sys.path.insert(0, folder)
out = []


def case(name):
    def wrap(f):
        try:
            f(); out.append(f"PASS  {name}")
        except AssertionError as e:
            out.append(f"FAIL  {name}: {e}")
        except Exception as e:
            out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap


sys.modules.setdefault("globalvars", types.ModuleType("globalvars"))
import sdr_launcher
import sdr_programs

sdr_launcher._system = lambda: "darwin"

apps = tempfile.mkdtemp()
BROWN_ID = "com.github.madmedicnl.sdroxide-brown"
UP_ID = "com.github.dividebysandwich.sdroxide"


def bundle(name, bundle_id):
    path = os.path.join(apps, name)
    os.makedirs(os.path.join(path, "Contents", "MacOS"))
    with open(os.path.join(path, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump({"CFBundleIdentifier": bundle_id, "CFBundleExecutable": "sdroxide"}, f)
    exe = os.path.join(path, "Contents", "MacOS", "sdroxide")
    open(exe, "w").close()
    return path, exe


BROWN_APP, BROWN_EXE = bundle("sdroxide-brown.app", BROWN_ID)
UP_APP, UP_EXE = bundle("sdroxide.app", UP_ID)


class Proc:
    def __init__(self, pid, exe):
        self.pid = pid
        self.info = {"pid": pid, "name": "sdroxide", "exe": exe}


def fake_psutil(*procs):
    mod = types.ModuleType("psutil")
    mod.process_iter = lambda attrs=None: iter(procs)
    mod.pid_exists = lambda pid: any(p.pid == pid for p in procs)
    sys.modules["psutil"] = mod


def profile(key):
    return sdr_programs.PROFILES[key]


@case("sdr_programs.json gives each SDRoxide its own bundle id")
def _():
    assert getattr(profile("sdroxide-brown"), "bundle_id", "") == BROWN_ID, \
        getattr(profile("sdroxide-brown"), "bundle_id", None)
    assert getattr(profile("sdroxide"), "bundle_id", "") == UP_ID, \
        getattr(profile("sdroxide"), "bundle_id", None)


@case("with upstream SDRoxide running, Brown is NOT found running")
def _():
    fake_psutil(Proc(101, UP_EXE))
    assert sdr_launcher.running_process(profile("sdroxide-brown")) is None, \
        "upstream's process was taken for Brown's"


@case("with both running, each is found as itself")
def _():
    fake_psutil(Proc(101, UP_EXE), Proc(202, BROWN_EXE))
    assert sdr_launcher.running_process(profile("sdroxide-brown")).pid == 202
    assert sdr_launcher.running_process(profile("sdroxide")).pid == 101


@case("Brown is asked to quit by its bundle id, not the name \"sdroxide\"")
def _():
    calls = []
    real = sdr_launcher.subprocess.run
    sdr_launcher.subprocess.run = lambda args, **k: (
        calls.append(args), types.SimpleNamespace(returncode=0, stderr="", stdout=""))[1]
    try:
        sdr_launcher.Started(profile("sdroxide-brown"), pid=202).ask_to_quit()
    finally:
        sdr_launcher.subprocess.run = real
    script = " ".join(calls[0]) if calls else ""
    assert f'application id "{BROWN_ID}"' in script, script


@case("started from a chosen .app, it is quit by THAT bundle's id")
def _():
    calls = []
    real = sdr_launcher.subprocess.run
    sdr_launcher.subprocess.run = lambda args, **k: (
        calls.append(args), types.SimpleNamespace(returncode=0, stderr="", stdout=""))[1]
    fake_psutil(Proc(202, BROWN_EXE))
    try:
        started, note = sdr_launcher.start(profile("sdroxide-brown"), BROWN_APP)
        assert started is not None, note
        assert ["open", "-a", BROWN_APP] in calls, calls
        assert getattr(started, "bundle_id", None) == BROWN_ID, getattr(started, "bundle_id", None)
        assert started.pid == 202, started.pid
    finally:
        sdr_launcher.subprocess.run = real


@case("started with no path set, Brown is opened by its bundle id")
def _():
    calls = []
    real = sdr_launcher.subprocess.run
    sdr_launcher.subprocess.run = lambda args, **k: (
        calls.append(args), types.SimpleNamespace(returncode=0, stderr="", stdout=""))[1]
    fake_psutil(Proc(202, BROWN_EXE))
    try:
        started, note = sdr_launcher.start(profile("sdroxide-brown"), "")
        assert ["open", "-b", BROWN_ID] in calls, calls
        assert started is not None and started.pid == 202, note
    finally:
        sdr_launcher.subprocess.run = real


print("\n".join(out))
print(f"\n{sum(l.startswith('PASS') for l in out)}/{len(out)} passed")
sys.exit(0 if all(l.startswith("PASS") for l in out) else 1)
