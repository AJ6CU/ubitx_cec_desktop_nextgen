# KD8CEC firmware 1.2 for uBITX CEC Desktop

KD8CEC's firmware 1.2 (it reports itself as `+v1.200`), Nextion build, with the
Nextion serial line at **57600 baud**, the speed uBITX CEC Desktop uses.
KD8CEC's own 1.2 files run that line at 9600; with those, set Speed to 9600 in
the app's Setup → Station & Radio.

| uBITX | File | `UBITX_BOARD_VERSION` |
| :--- | :--- | :---: |
| V3 or V4 | `KD8CEC_1.20_Nextion_57600_uBITX_V3_V4.hex` | 4 |
| V5 or V6 | `KD8CEC_1.20_Nextion_57600_uBITX_V5_V6.hex` | 5 |

Upload the file to the Raduino's Arduino Nano over the Nano's own USB port:
KD8CEC's uBITX Manager on Windows, or `avrdude` (it comes with the Arduino IDE)
on a Mac or Linux. Back up your calibration first: the help page, "Installing
KD8CEC 1.2", says how.

Built from KD8CEC's source, `github.com/phdlee/ubitx`, tag `v1.20`, with two
changes in `ubitx_20/`:

- `ubitx.h`: `#define UBITX_DISPLAY_NEXTION` as the display, and
  `UBITX_BOARD_VERSION` as in the table;
- `ubitx_lcd_nextion.ino`: `SWSerial_Begin(9600);` changed to
  `SWSerial_Begin(57600);`.

The firmware is KD8CEC's (Ian Lee), released under the GNU GPL v3; its source,
and the two changes above, are all that is needed to rebuild these files.
