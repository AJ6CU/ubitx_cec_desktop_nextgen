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
| `station.jpg` | The complete station: uBITX, SDR dongle, antenna switch and laptop, with the cables visible (antenna to switch, switch to uBITX and SDR, USB-TTL adapter and SDR to the laptop). The app on screen, ideally with the SDR's waterfall showing. |
| `sdr-layout.jpg` | Setting up an SDR ▸ Arranging the windows: uBITX CEC Desktop on top, the SDR's spectrum and waterfall below at the same width. JPG (the waterfall), about 1600 px wide, under 400 KB. |
| `brown-servers-hamlib.png` | Done: Brown, Settings ▸ Servers, the Hamlib rigctld server. Allow clients to transmit off. |
| `brown-servers-cw.png` | Done: Brown, Settings ▸ Servers, Decoded CW over UDP on 127.0.0.1:9998, its own APPLY. |
| `brown-undock.png` | Done: Brown, Settings ▸ Detachable, Panadapter undocked. |
| `sdroxide-undock.png` | Done: SDRoxide 1.7.3, Settings ▸ UI, Panadapter window undocked. |
| `brown-region.png` | Done: Brown, the IARU region (Region 2) and 11M/CB. |
| `brown-org-off.png` | Done: Brown's CW panel with the QRG chip off. |
| `brown-radio-rtlsdr.png` | Done: Brown, Settings ▸ Radio, Radio interface RTL-SDR (USB). SDRoxide's is the same. |
| `brown-radio-hf.png` | Done: Brown, Settings ▸ Radio: 2.400 Msps, manual gain, HF reception Automatic, IQ correction, Apply / reconnect. |
| `sdrpp-source-rtlsdr.png` | Done: SDR++ Source: RTL-SDR, 2.4MHz, Q branch, gain, IQ Correction, Play. |
| `sdrpp-module-manager.png` | Done: SDR++, the side menu scrolled to the Module Manager. |
| `sdrpp-finding-rigctl-server.png` | Done: SDR++, Module Manager, the type list open on rigctl_server. |
| `sdrpp-name-and-create.png` | Done: SDR++, Module Manager, a name in the box and the + button. |
| `sdrpp-configure-rigctl.png` | Done: SDR++, the new server section: localhost 4532, Radio, Tuning, Listen on startup, Start. |
| `sdrpp-listening.png` | Done: SDR++, the server section with Status: Listening. |
| `gqrx-startup.png` | Done: Gqrx, Configure I/O devices: device string and input rate (V3). |
| `gqrx-started-click-tools.png` | Done: Gqrx main window, the tools button for the remote control settings. |
| `gqrx-remote-control-settings.png` | Done: Gqrx remote control settings: 7356, 127.0.0.1. |
| `gqrx-turning-on-remote-control.png` | Done: Gqrx Tools menu, Remote control ticked. |
| `gqrx-tools-only-waterfall.png` | Done: Gqrx View menu, every panel unticked. |
| `gqrx-only-waterfall.png` | Done: Gqrx with only the spectrum and waterfall. Large (1.1 MB): a JPG candidate. |
| `gqrx-tools-waterfal-and-controls.png` | Done: Gqrx View menu, FFT Settings ticked. |
| `gqrx-waterfall-with_fft.png` | Done: Gqrx with FFT Settings: Band Plan, Split, Plot dB, WF dB. Large (770 KB): a JPG candidate. |
| `gqrx-app-windows-positioned.png` | Done: uBITX CEC Desktop with Gqrx underneath. Large (960 KB): a JPG candidate. |
| `sdrangel-configurations.png` | Done: the first-start Configurations dialog; press Close. |
| `sdrangel-startup-screen.png` | Done: SDRangel's first start, tiny text. |
| `sdrangel-preferences-graphics.png` | Done: Preferences ▸ Graphics. |
| `sdrangel-ui-scale.png` | Done: UI Scale Factor (125–150%), then restart. |
| `sdrangel-main-screen-after-ui-scale-resize.png` | Done: the toolbar: Add RX Device, Add Feature, window placement, dock/undock. |
| `sdrangel-add_rx_device.png` | Done: Select sampling device, RTL-SDR. |
| `sdrangel_after-RX_added.png` | Done: the RTL-SDR panel and spectrum. |
| `sdrangel-rx-setup-forv3.png` | Done: the RTL-SDR set up for a V3: DS, DC, IQ, gain. |
| `sdrangel_larger_win_and_columns_shows_add_channel.png` | Done: Columns, and the Add Channel button. |
| `sdrangel-add_wdsp_channel.png` | Done: Add Channel, WDSP Receiver. |
| `sdrangel-after-add-wdsp.png` | Done: the WDSP Receiver added; arrows at Vol and the loudspeaker (sound device). |
| `sdrangel-add_channel_power.png` | Done: Add Channel, Channel Power. |
| `sdrangel-channel_power_added.png` | Done: the Channel Power added. |
| `sdrangel-add-morsecode_decoder-feature.png` | Done: Add Feature, Morse Decoder. |
| `sdrangel-everything.png` | Done: everything in place, uBITX CEC Desktop connected. Large (835 KB). |
| `sdrangel-hide-this-window.png` | Done: the device panel: Hide this window, Show main spectrum, Show all channels. |
| `sdrangel-windows-positioned.png` | Done: uBITX CEC Desktop above SDRangel's spectrum and waterfall. Large (653 KB). |

Also wanted, for the sections marked "To fill in":
- each SDR program's server setting (Brown's Settings ▸ Servers, SDR++'s Rigctl Server module, Gqrx's Remote control, SDRangel's device set and channels).

Name those as you like and tell me the names; I'll put them in.
