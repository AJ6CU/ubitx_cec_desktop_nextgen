#!/usr/bin/env python3
"""
Builds the uBITX CEC Desktop wheel from src/.

    python3 packaging/build_wheel.py

Run from anywhere; needs pip and an internet connection the first time (pip
fetches setuptools to build with). The wheel lands in dist/ at the top of the
repository:

    dist/ubitx_cec_desktop-<version>-py3-none-any.whl

Install and run:

    pip install dist/ubitx_cec_desktop-<version>-py3-none-any.whl
    ubitx-cec-desktop            (or: python -m ubitx_cec_app)

WHAT IT DOES. src/ is left exactly as it is. Its program files, the shipped
JSON and help/ are copied into build/wheel/ubitx_cec_app/ with a launcher as
__main__.py (see launcher.py), and a pyproject.toml is written beside them
with the version from globalvars.APPVERSION -- one place to change it. The
src/ test_*.py files are left out.

The package is ubitx_cec_app, not ubitx_cec_desktop: the main program is
ubitx_cec_desktop.py, and a package of the same name would shadow it.
"""
import ast
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
STAGE = os.path.join(ROOT, "build", "wheel")
PACKAGE = "ubitx_cec_app"
DIST = os.path.join(ROOT, "dist")

DATA = ("*.json", "help/*", "help/images/*")
SKIP = ("test_*.py",)


def version():
    """globalvars.APPVERSION, read without importing it (it imports tkinter)."""
    tree = ast.parse(open(os.path.join(SRC, "globalvars.py"), encoding="utf-8").read())
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", None) == "APPVERSION"):
            return str(ast.literal_eval(node.value))
    raise SystemExit("APPVERSION not found in src/globalvars.py")


PYPROJECT = """\
[build-system]
requires = ["setuptools>=61.0.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ubitx-cec-desktop"
version = "{version}"
description = "A desktop control panel for the uBITX transceiver running KD8CEC firmware, with SDR integration."
readme = "README.md"
authors = [{{ name = "Mark Hatch, AJ6CU" }}]
requires-python = ">=3.10"
classifiers = [
    "Programming Language :: Python :: 3",
    "Operating System :: OS Independent",
    "Topic :: Communications :: Ham Radio",
]
dependencies = [
    # Not on PyPI: installed from its GitHub repository (needs git). A wheel
    # with a URL dependency cannot go to PyPI itself; publish sCTk there
    # first, then make this "scustomtkinter>=0.1.6.2".
    "scustomtkinter @ git+https://github.com/aj6cu/sCustomTkinter/",
    "customtkinter",
    "pyserial",
    "psutil",
]

[project.scripts]
ubitx-cec-desktop = "{package}.__main__:main"

[tool.setuptools]
packages = ["{package}"]
include-package-data = false

[tool.setuptools.package-data]
{package} = {data}
"""


def ignore(folder, names):
    import fnmatch
    return [n for n in names
            if n == "__pycache__" or n == ".DS_Store" or n.endswith(".pyc")
            or any(fnmatch.fnmatch(n, p) for p in SKIP)]


def main():
    ver = version()
    if os.path.exists(STAGE):
        shutil.rmtree(STAGE)
    package = os.path.join(STAGE, PACKAGE)
    shutil.copytree(SRC, package, ignore=ignore)
    shutil.copy(os.path.join(HERE, "launcher.py"), os.path.join(package, "__main__.py"))
    with open(os.path.join(package, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(f'"""uBITX CEC Desktop -- run with `ubitx-cec-desktop` or `python -m {PACKAGE}`."""\n'
                f'__version__ = "{ver}"\n')
    readme = os.path.join(ROOT, "README.md")
    if os.path.exists(readme):
        shutil.copy(readme, os.path.join(STAGE, "README.md"))
    else:
        with open(os.path.join(STAGE, "README.md"), "w", encoding="utf-8") as f:
            f.write("# uBITX CEC Desktop\n\nRun with `ubitx-cec-desktop`.\n")
    with open(os.path.join(STAGE, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write(PYPROJECT.format(version=ver, package=PACKAGE,
                                 data="[" + ", ".join(f'"{d}"' for d in DATA) + "]"))
    os.makedirs(DIST, exist_ok=True)
    print(f"building ubitx-cec-desktop {ver} ...")
    subprocess.check_call([sys.executable, "-m", "pip", "wheel", "--no-deps",
                           "-w", DIST, STAGE] + sys.argv[1:])
    print(f"done -- {DIST}")


if __name__ == "__main__":
    main()
