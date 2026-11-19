#!/bin/zsh
# Removes uBITX CEC Desktop installed by "Install uBITX CEC Desktop.command".
# Keeps your settings (~/.ubitx_cec_desktop; delete that folder yourself to
# remove them too) and your logbook (wherever Setup put it).
APP="uBITX CEC Desktop"
rm -rf "$HOME/Library/Application Support/$APP" "$HOME/Applications/$APP.app"
print; print -- "$APP removed. Your settings are still in ~/.ubitx_cec_desktop, and your logbook where Setup put it."
print; read -k1 "?Press a key to close."
