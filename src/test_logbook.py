"""
Log QSO writes the logbook, and its button follows Setup's Logbook switch.
    python3 test_logbook.py <app folder>
"""
import ast, os, sys, tempfile, textwrap, types
from datetime import datetime
folder = sys.argv[1]
sys.path.insert(0, folder)
out = []
def case(name):
    def wrap(f):
        try: f(); out.append(f"PASS  {name}")
        except AssertionError as e: out.append(f"FAIL  {name}: {e}")
        except Exception as e: out.append(f"FAIL  {name}: {type(e).__name__}: {e}")
    return wrap

QSO = dict(call="k6abc", band="40m", mode="CW", qso_date="20261110", time_on="1712",
           freq="7.030000", rst_sent="599", rst_rcvd="579")

def lb():
    import logbook
    return logbook

@case("an ADIF logbook gets the QSO, with the old app's header and fields")
def _():
    path = os.path.join(tempfile.mkdtemp(), "uBITX_Logbook.adi")
    ok, msg = lb().append_qso(path, QSO)
    text = open(path).read()
    assert ok, msg
    assert text.startswith("ADIF Real-Time Log File Class\n<EOH>"), text[:60]
    for piece in ("<call:5>K6ABC", "<band:3>40m", "<mode:2>CW", "<qso_date:8>20261110",
                  "<time_on:4>1712", "<freq:8>7.030000", "<rst_sent:3>599",
                  "<rst_rcvd:3>579", "<app_qrzlog_logid:12>", "<EOR>"):
        assert piece in text, piece

@case("the same QSO again is refused; the next one is appended")
def _():
    path = os.path.join(tempfile.mkdtemp(), "log.adi")
    lb().append_qso(path, QSO)
    ok, msg = lb().append_qso(path, dict(QSO, call="K6ABC"))
    assert not ok and "already" in msg, msg
    ok, _ = lb().append_qso(path, dict(QSO, time_on="1715"))
    assert ok and open(path).read().count("<EOR>") == 2

@case("an existing logbook from the old app carries on (its records read back)")
def _():
    path = os.path.join(tempfile.mkdtemp(), "old.adi")
    open(path, "w").write("ADIF Real-Time Log File Class\n<EOH>\n\n"
                          "<call:5>W1ABC <band:3>20m <mode:3>SSB <qso_date:8>20260101 "
                          "<time_on:4>0101 <freq:9>14.200000 <rst_sent:2>59 <rst_rcvd:2>59 "
                          "<app_qrzlog_logid:12>abcdefabcdef <EOR>\n")
    ok, msg = lb().append_qso(path, dict(QSO, call="W1ABC", band="20m", qso_date="20260101", time_on="0101"))
    assert not ok, "duplicate of an old record not seen"

@case("CSV: a header, then one row per QSO")
def _():
    path = os.path.join(tempfile.mkdtemp(), "log.csv")
    lb().append_qso(path, QSO); lb().append_qso(path, dict(QSO, time_on="1800"))
    lines = open(path).read().splitlines()
    assert lines[0] == "call,band,mode,qso_date,time_on,freq,rst_sent,rst_rcvd,app_id", lines[0]
    assert len(lines) == 3 and lines[1].startswith("K6ABC,40m,CW,20261110,1712")

@case("a callsign is required; nothing is written without one")
def _():
    path = os.path.join(tempfile.mkdtemp(), "log.adi")
    ok, msg = lb().append_qso(path, dict(QSO, call=" "))
    assert not ok and "call" in msg and not os.path.exists(path), msg

@case("a backup copy before writing, at most once per interval")
def _():
    d = tempfile.mkdtemp(); path = os.path.join(d, "log.adi")
    lb().append_qso(path, QSO, 10, now=datetime(2026, 11, 10, 17, 0))
    lb().append_qso(path, dict(QSO, time_on="1713"), 10, now=datetime(2026, 11, 10, 17, 1))
    lb().append_qso(path, dict(QSO, time_on="1714"), 10, now=datetime(2026, 11, 10, 17, 2))
    lb().append_qso(path, dict(QSO, time_on="1725"), 10, now=datetime(2026, 11, 10, 17, 15))
    backups = sorted(f for f in os.listdir(d) if "_backup_" in f)
    assert len(backups) == 2, backups

@case("modes and bands as ADIF writes them")
def _():
    assert [lb().adif_mode(m) for m in ("CWL", "CWU", "LSB", "USB")] == ["CW", "CW", "SSB", "SSB"]
    assert lb().adif_band("40 m") == "40m" and lb().adif_band(None) == ""

src = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()
funcs = {n.name: n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)}

@case("Log QSO greyed while Setup's logging is off, live while on")
def _():
    for n in ("_logging_on", "_show_log_button"):
        assert n in funcs, f"no {n}"
    class W:
        state = "normal"
        def configure(self, **k): self.state = k.get("state", self.state)
    for switch, want in (("False", "disabled"), ("True", "normal")):
        a = types.SimpleNamespace(log_qso_button=W())
        ns = {"gv": types.SimpleNamespace(config=types.SimpleNamespace(get_Logbook_Switch=lambda s=switch: s))}
        for n in ("_logging_on", "_show_log_button"):
            exec(textwrap.dedent(ast.get_source_segment(src, funcs[n])), ns)
            setattr(a, n, types.MethodType(ns[n], a))
        a._show_log_button()
        assert a.log_qso_button.state == want, (switch, a.log_qso_button.state)

@case("the dialog's Log writes through the logbook, not just closing")
def _():
    body = ast.get_source_segment(src, funcs["_log_qso"])
    assert "logbook.append_qso" in body, "Log does not write"

print("\n".join(out)); print(f"{sum(o.startswith('PASS') for o in out)} of {len(out)} passed")
