@echo off
rem Double-click to remove uBITX CEC Desktop. Your settings and logbook are kept.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
echo.
pause
