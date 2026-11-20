"""
Appearance: Dark / Light / Follow system, saved, Follow system by default.

    python3 test_appearance.py <app folder>
"""
import ast, os, sys, types, textwrap
folder = sys.argv[1]
src = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()
tree = ast.parse(src)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "UbitxCecDesktop")
fns = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
consts = {t.id: ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
          for t in n.targets if isinstance(t, ast.Name)
          and t.id in ("PREFERENCES_KEY", "APPEARANCES", "APPEARANCE_DEFAULT")}
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

modes, saved = [], []
gv = types.SimpleNamespace(config=types.SimpleNamespace(config_data={}, saveConfig=lambda: saved.append(1)))
ctk = types.SimpleNamespace(set_appearance_mode=modes.append)

def window():
    w = types.SimpleNamespace(**consts)
    for name in ("_appearance_saved", "_set_appearance"):
        ns = {"gv": gv, "ctk": ctk}
        exec(textwrap.dedent(ast.get_source_segment(src, fns[name])), ns)
        setattr(w, name, types.MethodType(ns[name], w))
    return w

@case("default is Follow system -> CustomTkinter's 'system'")
def _():
    assert "_set_appearance" in fns, "Appearance not wired"
    gv.config.config_data.clear(); modes.clear()
    w = window(); w._set_appearance(w._appearance_saved(), save=False)
    assert modes == ["system"], modes

@case("a choice is applied and saved; read back next start")
def _():
    gv.config.config_data.clear(); modes.clear(); saved.clear()
    w = window(); w._set_appearance("Light")
    assert modes == ["light"] and saved
    assert w._appearance_saved() == "Light"

@case("an unknown saved value falls back to Follow system")
def _():
    gv.config.config_data["Preferences"] = {"appearance": "Purple"}
    assert window()._appearance_saved() == "Follow system"

@case("applied at start-up before the window is built, and Setup's choice is live")
def _():
    init = ast.get_source_segment(src, fns["__init__"])
    assert init.index("_set_appearance(self._appearance_saved(), save=False)") < init.index("ChannelSets()")
    assert "self._set_appearance(choice)" in src

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)}/{len(out)}")
