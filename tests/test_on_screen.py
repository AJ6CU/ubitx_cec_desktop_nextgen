"""A remembered position that would put part of the window off the screen is moved back on.

    xvfb-run -a -s "-screen 0 1920x1080x24" python test_on_screen.py <src>
"""
import json, os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp()
sys.path.insert(0, sys.argv[1])
import ubitx_cec_desktop as m

res = []
def check(name, ok, info=""):
    res.append(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""))

def start(position):
    os.makedirs(os.path.dirname(m.GEOMETRY_FILE), exist_ok=True)
    with open(m.GEOMETRY_FILE, "w") as f:
        json.dump({"geometry": f"800x400{position}"}, f)
    app = m.UbitxCecDesktop()
    end = time.monotonic() + 3.0
    while time.monotonic() < end:
        app.update(); time.sleep(0.005)
    got = (app.winfo_x(), app.winfo_y(), app.winfo_width(), app.winfo_height(),
           app.winfo_screenwidth(), app.winfo_screenheight())
    app.close_down(); app.destroy()
    return got

x, y, w, h, sw, sh = start("+1500+900")      # saved when the window was smaller
check("right edge on the screen", x + w <= sw, f"x {x} + width {w} vs screen {sw}")
check("bottom edge on the screen", y + h <= sh, f"y {y} + height {h} vs screen {sh}")
x, y, w, h, sw, sh = start("+40+30")          # fits: left where it was
check("a position that fits is kept", (x, y) == (40, 30), f"+{x}+{y}")
x, y, w, h, sw, sh = start("+-3000+-50")      # wholly off to the left and top
check("left and top edges on the screen", x >= 0 and y >= 0, f"+{x}+{y}")
print("\n".join(res)); print(f"{sum(r.startswith('PASS') for r in res)}/{len(res)} passed")
