# Screenshots and photos for the help

Save each one in `help/images/` under the name given. The page shows it in place of its placeholder on the next open; no code changes are needed. PNG for screenshots, JPG for photos. Take them at the window's normal size, in dark mode.

| File | What it should show |
| :--- | :--- |
| `usb-ttl-adapter.jpg` | Done: a CP2102 and an FT232RL with the wire colour for each pin, and the voltage jumper. |
| `uBITX_V3_4_5_Nextion_Wiring.jpg` | Done: the Nextion cable on a V3/V4/V5 Raduino. |
| `uBITX_V6_Nextion_Wiring.jpg` | Done: the Nextion cable on a V6 Raduino (from below). |
| `usb-ttl-wiring-v3_4_5_Raduino.jpg` | Done: wiring diagram, adapter to the V3/V4/V5 display header. |
| `usb_ttl_wiring_v6_Raduino.jpg` | Done: wiring diagram, adapter to the V6 display header. |
| `setup-radio.png` | Done: Setup → **Station & Radio** sub-tab: the callsign, appearance and Keep on top beside the Radio group, with the adapter chosen under Port, Speed, Connect. |
| `setup-sdr.png` | Done: Setup → **SDR** sub-tab: SDRoxide Brown chosen, Start it, Address, Port, CW port. |
| `operate.png` | Done: Operate, connected to the radio and SDRoxide Brown: a frequency, a signal on the meter, a lamp or two lit. Split on helps show the RX/TX badges with different VFOs. |
| `rx.png` | Done: RX, listening through the rig, ATT on at some level and IFS on. |
| `channels.png` | Done: Channels with a channel set chosen (FT8 or CW calling), ideally mid-scan. |
| `cw.png` | Done: CW with the radio's values filled in. |
| `setup-logbook.png` | Done: Setup → **Logbook & more** sub-tab: the Logbook group and the buttons under Other settings. |
| `ubitx.h_part1.jpg` | Done: the top of `ubitx.h` (board version, Nextion display, USE_I2CSMETER off). |
| `ubitx.h_part2.jpg` | Done: the "Enable all features" list commented out. |
| `ubitx.h_part3.jpg` | Done: the "Recommended for Nextion" list turned on. |
| `nextion_baud_change.jpg` | Done: `SWSerial_Begin` 9600 to 57600 in `ubitx_lcd_nextion.ino`. |
| `arduino_ide_nano_bootloader.jpg` | Done: Tools, Arduino Nano, port and Processor (new or old bootloader). |

Also wanted, for the sections marked "To fill in":
- each SDR program's server setting (Brown's Settings ▸ Servers, SDR++'s Rigctl Server module, Gqrx's Remote control, SDRangel's device set and channels).

Name those as you like and tell me the names; I'll put them in.
