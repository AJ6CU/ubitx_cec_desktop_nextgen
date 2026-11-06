"""
Values lost from the rig's startup burst are fetched by restarting it.

    python3 test_report_recovery.py <app folder>
"""
import ast, os, sys, textwrap, types
folder = sys.argv[1]
src = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()
tree = ast.parse(src)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "UbitxCecDesktop")
fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_check_rig_answered")
consts = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
          if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "").startswith("RIG_")}
lsrc = open(os.path.join(folder, "ubitx_link.py")).read()
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

def app(missing_each_time, transmitting=False):
    log, later = [], []
    w = types.SimpleNamespace(rig_state="connected", _report_retries=0, notebook=None)
    w.model = types.SimpleNamespace(reports=5, transmitting=transmitting)
    answers = list(missing_each_time)
    w.connection = types.SimpleNamespace(
        check_expected_reports=lambda: answers.pop(0) if answers else {},
        restart_rig=lambda: log.append("restart"),
        reboot_ubitx=lambda: log.append("reboot"))
    w.after = lambda ms, f: later.append(f)
    ns = dict(consts, print=lambda *a, **k: None)
    exec(textwrap.dedent(ast.get_source_segment(src, fn)), ns)
    w._check_rig_answered = types.MethodType(ns["_check_rig_answered"], w)
    def run():
        w._check_rig_answered()
        while later:
            later.pop(0)()
    return w, log, run

@case("missing values: the rig is restarted and checked again")
def _():
    w, log, run = app([{"vs": "CW speed"}, {}]); run()
    assert log == ["restart"], log

@case("at most twice, then left")
def _():
    w, log, run = app([{"vs": "x"}] * 5); run()
    assert log == ["restart", "restart"], log

@case("everything arrived: no restart")
def _():
    w, log, run = app([{}]); run()
    assert log == [], log

@case("not while transmitting")
def _():
    w, log, run = app([{"vs": "x"}], transmitting=True); run()
    assert log == [], log

@case("the link's restart puts the fine tuning preset back")
def _():
    assert "def restart_rig" in lsrc, "no restart_rig"
    body = lsrc.split("def restart_rig")[1].split("\n    def ")[0]
    assert "reboot_ubitx()" in body and "Set_Tuning_Preset(1)" in body, body[-200:]

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
