# Screenshots and photos for the help

Save each one in `help/images/` under the name given. The page shows it in place of its placeholder on the next open; no code changes are needed. PNG for screenshots, JPG for photos. Take them at the window's normal size, in dark mode.

| File | What it should show |
| :--- | :--- |
| `usb-ttl-adapter.jpg` | The USB-to-TTL adapter, its pins legible (GND, RX, TX, and VCC left unconnected). |
| `usb-ttl-wiring.jpg` | The wires on the uBITX: where GND, adapter RX (to D9, the radio's send line) and adapter TX (to D8) land. Ideally one photo per uBITX version, or a close-up of the connector. |
| `setup-radio.png` | Setup, the Radio group: the adapter chosen under Port, Speed, Connect. |
| `setup-sdr.png` | Setup, the SDR group: SDRoxide Brown chosen, Start it, Address, Port, CW port. |
| `operate.png` | Operate, connected to the radio and SDRoxide Brown: a frequency, a signal on the meter, a lamp or two lit. Split on helps show the RX/TX badges with different VFOs. |
| `rx.png` | RX, listening through the rig, ATT on at some level and IFS on. |
| `channels.png` | Channels with a channel set chosen (FT8 or CW calling), ideally mid-scan. |
| `cw.png` | CW with the radio's values filled in. |
| `setup.png` | The whole Setup tab. |

Also wanted, for the sections marked "To fill in":
- the firmware: uBITX Manager's upload screen (Windows), and the Arduino IDE with `ubitx.h` open and the Nano chosen;
- each SDR program's server setting (Brown's Settings ▸ Servers, SDR++'s Rigctl Server module, Gqrx's Remote control, SDRangel's device set and channels).

Name those as you like and tell me the names; I'll put them in.
