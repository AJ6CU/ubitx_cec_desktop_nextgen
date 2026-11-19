"""
The radio's speed is not the operator's to choose in Setup.

    python3 test_rig_baud.py <app folder>

Mark (2026-11-18): at 9600 the app's timers no longer work, and the Nano's
software serial tops out at 57600; KD8CEC 2.0 on the Pico could do 115200.
So Setup shows the speed instead of offering a list, and the saved
"Rig Baud" is used only if it is 57600 or 115200 -- anything else (a 9600
left from testing) is read as 57600.
"""
import ast, os, sys, types

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


# ConfigurationManager without its file: just the dictionary get_rig_baud reads.
sys.modules.setdefault("globalvars", types.ModuleType("globalvars"))
try:
    import tkinter, tkinter.messagebox          # noqa: F401
except ImportError:                              # a machine without Tk: not needed here
    sys.modules["tkinter"] = types.ModuleType("tkinter")
    sys.modules["tkinter"].messagebox = sys.modules["tkinter.messagebox"] = types.ModuleType("tkinter.messagebox")
import configuration


def baud_for(saved):
    cm = configuration.ConfigurationManager.__new__(configuration.ConfigurationManager)
    cm.config_data = {"Rig Baud": saved}
    cm.saveConfig = lambda: None
    return cm.get_rig_baud()


@case("57600 is used as saved")
def _():
    assert baud_for(57600) == 57600


@case("115200 is used as saved (a Pico board)")
def _():
    assert baud_for(115200) == 115200, baud_for(115200)


@case("9600 left from testing is read as 57600")
def _():
    assert baud_for(9600) == 57600, baud_for(9600)


@case("19200 and 38400 likewise")
def _():
    assert baud_for(19200) == 57600 and baud_for("38400") == 57600


@case("rubbish in the file is read as 57600, not a crash")
def _():
    assert baud_for("fast") == 57600


src = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()


@case("Setup offers no list of speeds")
def _():
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.List) and any(
                isinstance(e, ast.Constant) and e.value == "9600" for e in node.elts):
            raise AssertionError(f"a list with 9600 at line {node.lineno}")


@case("Connect doesn't save a speed")
def _():
    assert "set_rig_baud(" not in src, "the window still calls set_rig_baud"


print("\n".join(out))
print(f"\n{sum(l.startswith('PASS') for l in out)}/{len(out)} passed")
sys.exit(0 if all(l.startswith("PASS") for l in out) else 1)
