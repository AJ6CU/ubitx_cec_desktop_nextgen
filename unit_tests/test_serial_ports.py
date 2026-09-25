#!/usr/bin/python3
"""
Checks serial_ports.py, and shows what it makes of THIS computer.

    python3 test_serial_ports.py

Two halves:

  * The checks, against imitation port lists for macOS, Windows, Linux and a
    Raspberry Pi. They need no hardware and no pyserial, so they run
    anywhere -- including where this was written.

  * What is really plugged in, listed as the Setup page would offer it, and
    then again with everything shown. Needs pyserial; skipped without it.

The second half is the one worth running with the radio's cable in and out,
and with a second adapter, to see that the right things appear.
"""
import sys

sys.path.insert(0, ".")
from src.serial_ports import list_rig_ports, parse_rig_port

passed = failed = 0


def check(label, ok):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")


class FakePort:
    """What pyserial's comports() hands back, as much of it as matters."""

    def __init__(self, device, description="n/a", vid=None, pid=None):
        self.device, self.description = device, description
        self.vid, self.pid = vid, pid


# ---------------------------------------------------------------------------
print("\nmacOS -- two adapters, among the ports a Mac always reports")
mac = lambda: [FakePort("/dev/cu.Bluetooth-Incoming-Port"),
               FakePort("/dev/cu.debug-console"),
               FakePort("/dev/cu.wlan-debug"),
               FakePort("/dev/tty.usbserial-A5069RR4", "FT232R USB UART", 0x0403, 0x6001),
               FakePort("/dev/cu.usbserial-A5069RR4", "FT232R USB UART", 0x0403, 0x6001),
               FakePort("/dev/tty.usbmodem1101", "USB Serial", 0x1A86, 0x7523),
               FakePort("/dev/cu.usbmodem1101", "USB Serial", 0x1A86, 0x7523)]
ports = list_rig_ports(mac, "darwin")
check(f"two ports offered, not seven ({[p.device for p in ports]})", len(ports) == 2)
check("the cu. form, never tty. -- opening tty. waits for carrier detect and can hang",
      all(p.device.startswith("/dev/cu.") for p in ports))
check("Bluetooth, debug-console and wlan-debug are out",
      not any("luetooth" in p.device or "debug" in p.device for p in ports))
check(f"each says what it is -- {ports[0].label}", "FTDI" in ports[0].label)
everything = list_rig_ports(mac, "darwin", show_all=True)
check("show all brings back all seven, the hidden ones last",
      len(everything) == 7 and everything[-1].hidden)
check(f"...saying why each is hidden -- {everything[-1].why}", bool(everything[-1].why))

print("\nWindows -- Bluetooth appears as an ordinary COM port")
win = lambda: [FakePort("COM1", "Communications Port"),
               FakePort("COM3", "USB Serial Port (COM3)", 0x0403, 0x6001),
               FakePort("COM5", "Standard Serial over Bluetooth link (COM5)", 0x0A12, 0x0001),
               FakePort("COM7", "USB-SERIAL CH340 (COM7)", 0x1A86, 0x7523)]
ports = list_rig_ports(win, "win32")
check(f"the two adapters, not COM1 or the Bluetooth link ({[p.device for p in ports]})",
      [p.device for p in ports] == ["COM3", "COM7"])

print("\nLinux -- legacy ports and Bluetooth")
linux = lambda: [FakePort("/dev/ttyS0"), FakePort("/dev/rfcomm0"),
                 FakePort("/dev/ttyUSB0", "CP2102 USB to UART Bridge", 0x10C4, 0xEA60),
                 FakePort("/dev/ttyACM0", "Arduino Uno", 0x2341, 0x0043)]
ports = list_rig_ports(linux, "linux")
check(f"the USB adapters only ({[p.device for p in ports]})",
      [p.device for p in ports] == ["/dev/ttyUSB0", "/dev/ttyACM0"])

print("\nRaspberry Pi -- its own UART has no USB behind it, and is still a way to wire a rig")
pi = lambda: [FakePort("/dev/ttyAMA0"), FakePort("/dev/ttyS0"),
              FakePort("/dev/ttyUSB0", "FT232R USB UART", 0x0403, 0x6001)]
ports = list_rig_ports(pi, "linux")
check(f"ttyAMA0 kept, ttyS0 not ({[p.device for p in ports]})",
      "/dev/ttyAMA0" in [p.device for p in ports]
      and "/dev/ttyS0" not in [p.device for p in ports])
check("the USB adapter offered first, as the likelier one",
      ports[0].device == "/dev/ttyUSB0")

print("\nNothing plugged in")
check("an empty list, not an error", list_rig_ports(lambda: [], "darwin") == [])

print("\nWhere the rig is -- a device, or a bridge")
for text, want_kind, want_words in (
        ("/dev/cu.usbserial-A5069RR4", "serial", ""),
        ("COM3", "serial", ""),
        ("socket://192.168.1.50:8080", "socket", ""),
        ("", "", "no port chosen"),
        ("socket://192.168.1.50", "", "not a port number"),
        ("socket://:8080", "", "needs an address"),
        ("socket://host:notaport", "", "not a port number"),
        ("http://192.168.1.50:80", "", "not a kind of connection")):
    kind, value, problem = parse_rig_port(text)
    right = kind == want_kind and (want_words in problem if want_words else not problem)
    check(f"{text!r:32} -> {kind or 'refused: ' + problem}", right)

# ---------------------------------------------------------------------------
print("\nThis computer")
try:
    from serial.tools import list_ports
except ImportError:
    print("  pyserial is not installed here, so there is nothing to look at.")
else:
    offered = list_rig_ports()
    if offered:
        print(f"  Setup would offer {len(offered)}:")
        for port in offered:
            print(f"    {'likely  ' if port.likely else '        '}{port.label}")
    else:
        print("  Setup would offer nothing -- no adapter is plugged in.")
    hidden = [p for p in list_rig_ports(show_all=True) if p.hidden]
    if hidden:
        print(f"  and would hide {len(hidden)}:")
        for port in hidden:
            print(f"            {port.device}  ({port.why})")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
