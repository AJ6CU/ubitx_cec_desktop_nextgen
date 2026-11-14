"""Windows' display scale changed while the app runs: the window is fitted again.

    xvfb-run -a -s "-screen 0 1920x1080x24" python test_display_change.py <src>

Mark, X1 Carbon: started at 150 %, switched to 200 %, the window ran past the
right edge of the screen. Here the display scale goes up and back, as
CustomTkinter's DPI check does it on Windows -- up by enough that the content
needs a quarter more than the screen's width, as at 200 % on the X1's 2560 px
(1.5 on a 1920 px screen; more on a wider one, such as a 3440 px monitor).
"""
import json, os, sys, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp()
sys.path.insert(0, sys.argv[1])
import ubitx_cec_desktop as m
from customtkinter.windows.widgets.scaling import ScalingTracker

os.makedirs(os.path.dirname(m.GEOMETRY_FILE), exist_ok=True)
with open(m.GEOMETRY_FILE, "w") as f:
    json.dump({"geometry": "800x400+300+100"}, f)
app = m.UbitxCecDesktop()

def pump(s):
    end = time.monotonic() + s
    while time.monotonic() < end:
        app.update(); time.sleep(0.005)

# CustomTkinter checks the display scale ten times a second, and on Linux
# always finds 1: it is told the scale here instead, and finds the change
# itself, as it does on Windows.
SCALE = [1.0]
ScalingTracker.get_window_dpi_scaling = classmethod(lambda cls, window: SCALE[0])


def display(scale):
    SCALE[0] = scale
    pump(2.5)

res = []
def check(name, ok, info=""):
    res.append(("PASS " if ok else "FAIL ") + name + (f"  ({info})" if info else ""))

pump(3.0)
sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
w0 = app.winfo_width()
up = round(sw * 1.25 / w0, 2)
print(f"screen {sw} px, window {w0} px: display scale 1 -> {up} -> 1")
display(up)
x, w, rw = app.winfo_x(), app.winfo_width(), app.winfo_reqwidth()
check("raised: the window is on the screen", x >= 0 and x + w <= sw, f"x {x} width {w} screen {sw}")
check("raised: the content fits the window", rw <= w, f"content {rw}, window {w}")
check("raised: scaled down to fit", ScalingTracker.widget_scaling < 1.0, f"{ScalingTracker.widget_scaling:.2f}")
display(1.0)
w1 = app.winfo_width()
check("back at 1: the screen-fit scaling is undone", abs(ScalingTracker.widget_scaling - 1.0) < 0.001,
      f"{ScalingTracker.widget_scaling:.2f}")
check("back at 1: as wide as at start-up", abs(w1 - w0) <= 4, f"{w1} vs {w0}")
app.close_down(); app.destroy()
print("\n".join(res)); print(f"{sum(r.startswith('PASS') for r in res)}/{len(res)} passed")
