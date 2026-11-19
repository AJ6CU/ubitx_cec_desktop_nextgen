"""
A new installation's logbook goes in Documents, where people look for it.

    python3 test_logbook_default.py <app folder>

Mark (2026-11-18): the logbook is the one file users are likely to use a lot,
and it defaulted to the home folder (~/uBITX_Logbook.adi), which most people
never browse. Now: ~/Documents if there is one, else the home folder -- and
the home folder still if an old default logbook is already there, so nobody's
log is split in two.
"""
import os, subprocess, sys, tempfile

folder = os.path.abspath(sys.argv[1])
out = []


def default_location(home):
    """The default 'Logbook Location' as the module works it out for this home."""
    env = dict(os.environ, HOME=home, USERPROFILE=home)
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "import defaultubitx_cec_desktop as d; "
            "print(d.default_config_data['Logbook Location'])")
    return subprocess.run([sys.executable, "-I", "-c", code, folder], env=env,
                          capture_output=True, text=True, check=True).stdout.strip()


def case(name, make, want):
    with tempfile.TemporaryDirectory() as home:
        make(home)
        got = default_location(home)
        out.append(f"{'PASS' if got == want else 'FAIL'}  {name}: {got!r}" + ("" if got == want else f", want {want!r}"))


case("a home with a Documents folder", lambda h: os.mkdir(os.path.join(h, "Documents")), "~/Documents")
case("a home with no Documents folder", lambda h: None, "~")
case("an old logbook already in the home folder stays there",
     lambda h: (os.mkdir(os.path.join(h, "Documents")),
                open(os.path.join(h, "uBITX_Logbook.adi"), "w").close()), "~")
case("... a CSV one too",
     lambda h: (os.mkdir(os.path.join(h, "Documents")),
                open(os.path.join(h, "uBITX_Logbook.csv"), "w").close()), "~")

print("\n".join(out))
print(f"\n{sum(l.startswith('PASS') for l in out)}/{len(out)} passed")
sys.exit(0 if all(l.startswith("PASS") for l in out) else 1)
