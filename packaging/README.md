# Building the wheel

```
python3 packaging/build_wheel.py
```

This writes `dist/ubitx_cec_desktop-<version>-py3-none-any.whl`. The version comes from `APPVERSION` in `src/globalvars.py`, and the dependencies from `requirements.txt` at the top of the repository: each is kept in one place only. `src/` itself is not touched.

To run from source instead, install the same list into a virtual environment with `pip install -r requirements.txt`.

## Installing it

```
pip install dist/ubitx_cec_desktop-1.0-py3-none-any.whl
ubitx-cec-desktop
```

You can also start it with `python -m ubitx_cec_app`.

pip installs everything else from PyPI: sCustomTkinter, customtkinter, pyserial and psutil. Git isn't needed. Installing into a virtual environment keeps it apart from your development copy.

## Notes

- **The package is called `ubitx_cec_app`.** The main program is `ubitx_cec_desktop.py`, and a package with the same name would hide it. The launcher (`launcher.py`, installed as `__main__.py`) puts the package folder on `sys.path` and runs `ubitx_cec_desktop.py`, so the modules' plain imports (`import globalvars`) work unchanged.
- **What's included:** every `.py` file in `src/` except `test_*.py`, the shipped JSON files, and `help/`.
- **Your settings are not in the wheel.** They stay in `~/.ubitx_cec_desktop`, shared with the development copy.
- **PyPI:** sCustomTkinter is on PyPI (0.2.1 and later), so this wheel could go there too.
