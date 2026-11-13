#!/bin/zsh
# Removes uBITX CEC Desktop installed by "Install uBITX CEC Desktop.command".
# Keeps your settings and logbook (~/.ubitx_cec_desktop); delete that folder
# yourself to remove them too.
APP="uBITX CEC Desktop"
rm -rf "$HOME/Library/Application Support/$APP" "$HOME/Applications/$APP.app"
print; print -- "$APP removed. Your settings and logbook are still in ~/.ubitx_cec_desktop"
print; read -k1 "?Press a key to close."
