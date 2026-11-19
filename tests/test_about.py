"""
The About box shows the real version and the real logbook path.

    python3 test_about.py <app folder>

Found 2026-11-18 while writing the help's "Where your settings are kept":
About said "1.0 · June 2026" (globalvars says 1.0.9, November 13, 2026) and
"~/Downloads/ubitx_Logbook.adi" whatever the logbook was set to (the default
is ~/uBITX_Logbook.adi).
"""
import ast, os, sys

folder = sys.argv[1]
src = open(os.path.join(folder, "ubitx_cec_desktop.py")).read()
out = []


def rows():
    """The (label, value) pairs of the About box's table, as source nodes."""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Tuple) and len(node.elts) == 2 \
                and isinstance(node.elts[0], ast.Constant) and node.elts[0].value in ("Version", "Logbook"):
            yield node.elts[0].value, node.elts[1]


found = dict(rows())
for label, needs in (("Version", "APPVERSION"), ("Logbook", "_logbook_path")):
    value = found.get(label)
    if value is None:
        out.append(f"FAIL  About has no {label} row")
    elif isinstance(value, ast.Constant):
        out.append(f"FAIL  About's {label} is a fixed string: {value.value!r}")
    elif needs not in ast.unparse(value):
        out.append(f"FAIL  About's {label} does not use {needs}: {ast.unparse(value)}")
    else:
        out.append(f"PASS  About's {label} comes from {needs}")

print("\n".join(out))
print(f"\n{sum(l.startswith('PASS') for l in out)}/{len(out)} passed")
sys.exit(0 if all(l.startswith("PASS") for l in out) else 1)
