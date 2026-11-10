"""
Starts uBITX CEC Desktop from an installed wheel -- the `ubitx-cec-desktop`
command, or `python -m ubitx_cec_app`.

Copied into the wheel as ubitx_cec_app/__main__.py by build_wheel.py.

WHY A LAUNCHER: the app's modules import each other by their plain names
(`import globalvars`, `from sdr_link import SDR_Link`), as they do when run
from src/. Installed, they live inside the ubitx_cec_app package, so this
puts that folder first on sys.path and runs ubitx_cec_desktop.py as the main
program -- no change to any of the app's own files.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    runpy.run_path(os.path.join(HERE, "ubitx_cec_desktop.py"), run_name="__main__")


if __name__ == "__main__":
    main()
