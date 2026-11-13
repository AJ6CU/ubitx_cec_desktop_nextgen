#!/usr/bin/env bash
# Removes uBITX CEC Desktop installed by install.sh. Keeps your settings and
# logbook (~/.ubitx_cec_desktop); delete that folder yourself to remove them too.
set -u
rm -rf "$HOME/.local/share/ubitx-cec-desktop"
rm -f "$HOME/.local/bin/ubitx-cec-desktop" "$HOME/.local/share/applications/ubitx-cec-desktop.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1
printf '\nuBITX CEC Desktop removed. Your settings and logbook are still in ~/.ubitx_cec_desktop\n'
