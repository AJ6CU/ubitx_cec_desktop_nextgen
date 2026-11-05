"""
Setup's SDR choice and the custom location (SDR settings' path).

    python3 test_sdr_path.py <path to ubitx_cec_desktop.py>

Runs the window's own _on_sdr_software and _show_sdr_path, lifted from the
file, against stand-ins -- no window, no SDR.
"""
import ast, sys, textwrap, types

# src = open(sys.argv[1]).read()
src = open("ubitx_cec_desktop.py").read()
methods = {n.name: textwrap.dedent(ast.get_source_segment(src, n))
           for n in ast.walk(ast.parse(src))
           if isinstance(n, ast.FunctionDef) and n.name in ("_on_sdr_software", "_show_sdr_path")}

class Config:
    def __init__(self, software, path):
        self.d = {"sw": software, "path": path, "port": "4532"}
    def get_sdr_software(self): return self.d["sw"]
    def set_sdr_software(self, k): self.d["sw"] = k
    def get_sdr_path(self): return self.d["path"]
    def set_sdr_path(self, p): self.d["path"] = str(p).strip()
    def get_sdr_port(self): return self.d["port"]
    def set_sdr_port(self, p): self.d["port"] = str(p)

CHOICES = [("none", "None"), ("gqrx", "Gqrx"), ("sdroxide", "SDRoxide")]
class Profile:
    def __init__(self, key): self.key, self.default_port = key, (None if key == "none" else 4532)

class Label:
    text = None
    def configure(self, text): self.text = text
class Entry:
    def delete(self, *a): pass
    def insert(self, *a): pass

def window(software, path, with_note=True):
    gv = types.SimpleNamespace(config=Config(software, path))
    ns = {"gv": gv, "sdr_choices": lambda: CHOICES, "profile_for": Profile,
          "sdr_programs": types.SimpleNamespace(
              PROFILES={k: Profile(k) for k, _ in CHOICES}),
          "print": lambda *a, **k: None}
    w = types.SimpleNamespace(sdr_port_entry=Entry(), _show_decoder_port=lambda: None)
    if with_note:
        w.sdr_path_note = Label()
    for name, code in methods.items():
        exec(code, ns)
        setattr(w, name, types.MethodType(ns[name], w))
    if not hasattr(w, "_show_sdr_path"):
        w._show_sdr_path = lambda: None
    return w, gv.config

out = []
def case(name):
    def wrap(fn):
        try: fn(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

@case("choosing a different program clears the custom location")
def _():
    w, c = window("gqrx", "/opt/gqrx/gqrx")
    w._on_sdr_software("SDRoxide")
    assert c.get_sdr_path() == "", repr(c.get_sdr_path())
    assert c.get_sdr_software() == "sdroxide"

@case("choosing the same program again keeps it")
def _():
    w, c = window("gqrx", "/opt/gqrx/gqrx")
    w._on_sdr_software("Gqrx")
    assert c.get_sdr_path() == "/opt/gqrx/gqrx", repr(c.get_sdr_path())

@case("the note says so while a location is set, and goes when it is cleared")
def _():
    w, c = window("gqrx", "/opt/gqrx/gqrx")
    w._show_sdr_path()
    assert w.sdr_path_note.text == "(custom path)", w.sdr_path_note.text
    w._on_sdr_software("SDRoxide")
    assert w.sdr_path_note.text == "", repr(w.sdr_path_note.text)

@case("no note without a location")
def _():
    w, c = window("gqrx", "")
    w._show_sdr_path()
    assert w.sdr_path_note.text == "", repr(w.sdr_path_note.text)

print("\n".join(out))
print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")