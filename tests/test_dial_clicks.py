"""
A click on a knob turns the knob, not just the frequency.

    python3 test_dial_clicks.py <app folder>

Mark (2026-11-19): a left click on the tuning knob stepped the frequency
down and a right click up, but the knob itself never moved -- RX or TX.
The app handed the dials left_click_callback / right_click_callback, and the
library (sCTk 0.2.1, sCTKDialBase._on_left_click_step) runs a click callback
INSTEAD of stepping: no step, no redraw of the knob's dimple. Left alone,
the dial steps itself -- turning the knob and calling its command with -1 or
+1, which is exactly what the callbacks did by hand.
"""
import ast, os, sys

folder = sys.argv[1]
src = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()
out = []

calls = [n for n in ast.walk(ast.parse(src))
         if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "sCTkDialContinuous"]
if not calls:
    out.append("FAIL  no sCTkDialContinuous found")
for call in calls:
    given = {k.arg for k in call.keywords} & {"left_click_callback", "right_click_callback"}
    if given:
        out.append(f"FAIL  the dial at line {call.lineno} takes {', '.join(sorted(given))}: "
                   "a click would step the frequency without turning the knob")
    else:
        has_command = any(k.arg == "command" for k in call.keywords)
        out.append(("PASS" if has_command else "FAIL") +
                   f"  the dial at line {call.lineno} turns itself on a click"
                   + ("" if has_command else " -- but has no command to tune with"))

print("\n".join(out))
print(f"\n{sum(l.startswith('PASS') for l in out)}/{len(out)} passed")
sys.exit(0 if all(l.startswith("PASS") for l in out) else 1)
