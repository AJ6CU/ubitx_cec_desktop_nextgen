"""
The app's dialogs open over the app, not at the screen's top left.

    python3 test_dialog_place.py <app folder>
"""
import ast, os, sys, textwrap, types
src = open(os.path.join(sys.argv[1], "ubitx_cec_desktop.py")).read()
cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "UbitxCecDesktop")
fn = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_over_app"), None)
out = []
try:
    assert fn is not None, "no _over_app"
    ns = {}; exec(textwrap.dedent(ast.get_source_segment(src, fn)), ns)
    root = types.SimpleNamespace(update_idletasks=lambda: None,
                                 winfo_rootx=lambda: 400, winfo_rooty=lambda: 300,
                                 winfo_width=lambda: 800, winfo_height=lambda: 600,
                                 winfo_screenwidth=lambda: 1920, winfo_screenheight=lambda: 1080)
    got = []
    win = types.SimpleNamespace(geometry=got.append)
    ns["_over_app"](root, win, 340, 300)
    size, x, y = got[0].split("+"); x, y = int(x), int(y)
    assert size == "340x300", got
    assert 400 <= x <= 400 + 800 - 340 and 300 <= y <= 300 + 600 - 300, (x, y)
    out.append(f"PASS  a dialog opens over the app ({x},{y})")
    for title in ("Log QSO", "About", "SDR settings"):
        body = src.split(f'win.title("{title}")')[1][:80]
        assert "_over_app(win" in body, f"{title} not placed"
        out.append(f"PASS  {title} uses it")
except AssertionError as e:
    out.append(f"FAIL  {e}")
print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)} of 4 passed")
