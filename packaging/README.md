# Building the wheel

```
python3 packaging/build_wheel.py
```

This writes `dist/ubitx_cec_desktop-<version>-py3-none-any.whl`. The version comes from `APPVERSION` in `src/globalvars.py`, which is the only place to change it. `src/` itself is not touched.

## Installing it

```
pip install dist/ubitx_cec_desktop-1.0-py3-none-any.whl
ubitx-cec-desktop
```

You can also start it with `python -m ubitx_cec_app`.

pip installs customtkinter, pyserial and psutil from PyPI, plus sCustomTkinter from its GitHub repository. sCustomTkinter isn't on PyPI, so git must be installed for that step. Installing into a virtual environment keeps it apart from your development copy.

## Notes

- **The package is called `ubitx_cec_app`.** The main program is `ubitx_cec_desktop.py`, and a package with the same name would hide it. The launcher (`launcher.py`, installed as `__main__.py`) puts the package folder on `sys.path` and runs `ubitx_cec_desktop.py`, so the modules' plain imports (`import globalvars`) work unchanged.
- **What's included:** every `.py` file in `src/` except `test_*.py`, the shipped JSON files, and `help/`.
- **Your settings are not in the wheel.** They stay in `~/.ubitx_cec_desktop`, shared with the development copy.
- **PyPI:** to publish there, put sCustomTkinter on PyPI first, then change its dependency line in `build_wheel.py` to a plain `scustomtkinter>=…`.
