"""
Connecting the rig again reaches the SDR link and the scanner too.

    python3 test_reconnect.py <app folder>

Found by Mark (2026-11-18): with a new USB-to-TTL adapter chosen and connected
from Setup, the rig's frequency reached the SDR, but a click in the SDR's
spectrum never reached the rig -- the SDR link was still sending to the link
it was given at start-up.
"""
import ast, os, sys, textwrap, types

folder = sys.argv[1]
src = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()
tree = ast.parse(src)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "UbitxCecDesktop")
methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
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


class NullRig:
    reader_process_id = None
    bytes_seen = 0
    def __getattr__(self, name):
        return lambda *a, **k: None


class Link:
    """Stands in for uBITX_Link: remembers the port it was opened on."""
    def __init__(self, root, stream, model, period):
        self.stream = stream
        self.reader_process_id = None
        self.command_headroom = None


class Stream:
    def __init__(self, name):
        self.name, self.closed = name, False
    def close(self):
        self.closed = True


def app(port, with_parts=True):
    """A window with just what _open_rig and _close_rig touch."""
    w = types.SimpleNamespace(rig_stream=None, rig_state="unchosen", rig_note="",
                              model=types.SimpleNamespace(reports=0))
    w.connection = NullRig()
    if with_parts:
        w.sdr = types.SimpleNamespace(_rig=w.connection)
        w.scanner = types.SimpleNamespace(_rig=w.connection)
    w.after = lambda ms, f: None
    w.after_cancel = lambda i: None
    w._headroom_setting = lambda: 0.04
    w._timing_setting = lambda: {}
    w._check_rig_answered = lambda: None
    ns = {
        "print": lambda *a, **k: None,
        "NullRig": NullRig,
        "uBITX_Link": Link,
        "RIG_ANSWER_MS": 2500,
        "parse_rig_port": lambda s: ("serial", s, None) if s else (None, None, "none"),
        "open_rig_port": lambda value, baud: Stream(value),
        "ubitx_link": types.SimpleNamespace(apply_timing=lambda t: None),
        "gv": types.SimpleNamespace(config=types.SimpleNamespace(
            get_rig_port=lambda: port[0], get_rig_baud=lambda: 57600)),
    }
    for name in ("_open_rig", "_close_rig", "_set_connection"):
        if name not in methods:
            continue
        exec(textwrap.dedent(ast.get_source_segment(src, methods[name])), ns)
        setattr(w, name, types.MethodType(ns[name], w))
    return w


@case("a rig connected again from Setup: the SDR link sends to the new link")
def _():
    port = ["/dev/cu.old"]
    w = app(port)
    w._open_rig()
    port[0] = "/dev/cu.SLAB_USBtoUART"          # the CP2102, chosen in Setup
    w._open_rig()
    assert w.connection.stream.name == "/dev/cu.SLAB_USBtoUART"
    assert w.sdr._rig is w.connection, "the SDR link still holds the old link"


@case("... and so does the scanner")
def _():
    port = [""]                                  # nothing chosen at start-up
    w = app(port)
    w._open_rig()
    port[0] = "/dev/cu.SLAB_USBtoUART"
    w._open_rig()
    assert w.scanner._rig is w.connection, "the scanner still holds the NullRig"


@case("closing leaves them with the NullRig, not a closed port")
def _():
    port = ["/dev/cu.old"]
    w = app(port)
    w._open_rig()
    stream = w.rig_stream
    w._close_rig()
    assert stream.closed
    assert isinstance(w.sdr._rig, NullRig) and isinstance(w.scanner._rig, NullRig)


@case("at start-up, before the SDR link and scanner exist, opening works")
def _():
    w = app(["/dev/cu.old"], with_parts=False)
    assert w._open_rig() is True
    assert isinstance(w.connection, Link)


print("\n".join(out))
print(f"\n{sum(l.startswith('PASS') for l in out)}/{len(out)} passed")
sys.exit(0 if all(l.startswith("PASS") for l in out) else 1)
