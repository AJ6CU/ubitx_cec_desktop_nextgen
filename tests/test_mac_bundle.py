"""
An .app bundle given as the SDR program's location is opened as an
application, not run as a file.

    python3 test_mac_bundle.py <folder with sdr_launcher.py>
"""
import os, sys, tempfile, types
sys.path.insert(0, sys.argv[1])
import sdr_launcher as L
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

app = os.path.join(tempfile.mkdtemp(), "sdroxide-Brown.app")
os.makedirs(os.path.join(app, "Contents", "MacOS"))
profile = types.SimpleNamespace(name="SDRoxide Brown", app_name="SDRoxide",
                                needs_command_line=False, launch_as_application=False)

def run(system, override):
    ran, popened = [], []
    L._system = lambda: system
    L.subprocess.run = lambda cmd, **k: ran.append(cmd)
    L.subprocess.Popen = lambda cmd, **k: (popened.append(cmd), (_ for _ in ()).throw(
        PermissionError(13, "Permission denied", cmd[0])))[1]
    L.running_process = lambda p: types.SimpleNamespace(pid=4242)
    L.time.sleep = lambda s: None
    L.program_command = lambda p, o: [o] if o else None
    return L.start(profile, override), ran, popened

@case("an .app path on the Mac is opened as that application")
def _():
    (handle, note), ran, popened = run("darwin", app)
    assert ran == [["open", "-a", app]] and not popened, (ran, popened)
    assert handle is not None and handle.pid == 4242, note
    assert note == "started sdroxide-Brown.app", note

@case("a trailing slash or ~ still counts")
def _():
    (handle, note), ran, _ = run("darwin", app + "/")
    assert ran == [["open", "-a", app]], ran

@case("an ordinary program path is still run directly")
def _():
    exe = os.path.join(os.path.dirname(app), "rigctld")
    open(exe, "w").close()
    (handle, note), ran, popened = run("darwin", exe)
    assert ran == [] and popened == [[exe]], (ran, popened)

@case("not on Linux or Windows, where there are no .app bundles")
def _():
    (handle, note), ran, popened = run("linux", app)
    assert ran == [] and popened == [[app]], (ran, popened)

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
