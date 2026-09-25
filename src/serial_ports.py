#!/usr/bin/python3
"""
Finding the rig: which serial ports exist, and which could plausibly be it.

WHY THIS IS NOT JUST comports()

The list the operating system gives is full of things that are not radios.
A Mac reports its Bluetooth port and a debug console; Windows lists Bluetooth
links as ordinary COM ports; a PC's motherboard offers legacy ttyS ports that
have had nothing attached for twenty years. Offered all of them, the operator
has to know which is which -- and picking wrong on a Mac can HANG, because
opening /dev/tty.* waits for carrier detect that never comes.

So the list is filtered, and the ones that look like a USB-serial adapter --
FTDI, CH340, CP210x, Prolific, Arduino, which is what a uBITX cable is -- are
marked as likely. Nothing is guessed at automatically: the operator chooses,
always. This only decides what is offered, and in what order.

SHOW ALL PORTS is the escape hatch. Any rule here can be wrong about somebody
else's station, and a filter that cannot be overridden is worse than no
filter at all.

WHAT IS NOT LISTED

A rig on a WiFi-to-TTL bridge -- "socket://192.168.1.50:8080". There is
nothing to enumerate: it is typed in and remembered. parse_rig_port() below
tells the two apart and checks the address before anything tries to open it,
because a mistyped one otherwise fails as a puzzling timeout rather than as
a mistake.
"""
import sys

# The chips in USB-serial adapters. Not a filter -- a port with an unknown
# vendor is still offered -- but what marks the likely candidates and sorts
# them first.
ADAPTER_VENDORS = {
    0x0403: "FTDI",
    0x1A86: "CH340",        # the usual Arduino Nano clone chip
    0x10C4: "CP210x",
    0x067B: "Prolific",
    0x2341: "Arduino",
    0x2A03: "Arduino",
    0x1B4F: "SparkFun",
    0x239A: "Adafruit",
}

# Hidden by name, whatever else they look like. Matched against the device
# and its description, in lower case.
NEVER_A_RIG = ("bluetooth", "debug-console", "wlan-debug", "rfcomm")


class Port:
    """One serial port, as the Setup page would show it."""

    def __init__(self, device, label, likely=False, hidden=False, why=""):
        self.device = device        # what gets stored and opened
        self.label = label          # what the operator reads
        self.likely = likely        # looks like a USB-serial adapter
        self.hidden = hidden        # filtered out unless "show all"
        self.why = why              # and why, for the tooltip

    def __repr__(self):
        return f"Port({self.device!r}, likely={self.likely}, hidden={self.hidden})"


def _short_name(device):
    """
    A port as its operator would say it: "COM3", "ttyUSB0",
    "cu.usbserial-A5069RR4".

    The "/dev/" carries no information and is the width that pushed the chip
    name out of a narrow list. The FULL path is what gets stored and opened --
    this is only what is read.
    """
    return device[5:] if device.startswith("/dev/") else device


def _tidy(description, device):
    """
    A description worth showing beside the name.

    Windows repeats the port inside it -- "USB-SERIAL CH340 (COM7)" -- and
    some systems say nothing useful at all.
    """
    text = (description or "").strip()
    if text.lower() in ("", "n/a", "unknown", "none"):
        return ""
    name = _short_name(device)
    text = text.replace(f"({name})", "").replace(name, "").strip(" -()")
    return text if len(text) <= 30 else text[:29] + "…"


def _describe(device, description, vid, pid, likely):
    """What the operator picks from: the name first, then what it is."""
    label = _short_name(device)
    chip = ADAPTER_VENDORS.get(vid, "")
    detail = _tidy(description, device)
    if chip and detail and chip.lower() not in detail.lower():
        return f"{label}  — {chip} ({detail})"
    if chip:
        return f"{label}  — {chip}"
    if detail:
        return f"{label}  — {detail}"
    if vid is not None:
        return f"{label}  — USB {vid:04x}:{pid or 0:04x}"
    return label


def _looks_hidden(device, description, system):
    """Whether a port should be kept out of the list, and why."""
    haystack = f"{device} {description}".lower()
    for word in NEVER_A_RIG:
        if word in haystack:
            return f"{word} device"

    if system == "darwin":
        # macOS lists every port twice: /dev/cu.X and /dev/tty.X. Opening the
        # tty form WAITS FOR CARRIER DETECT and can hang; cu does not. Only
        # cu is offered.
        if device.startswith("/dev/tty."):
            return "the /dev/cu. form of this port is listed instead"
    return ""


def list_rig_ports(comports=None, system=None, show_all=False):
    """
    The serial ports to offer, likely candidates first.

    Args:
        comports: The source of ports -- defaults to pyserial's
            serial.tools.list_ports.comports. Passed in so this can be tested
            without any hardware, and so a caller can supply its own.
        system: sys.platform, overridable for the same reason.
        show_all: Include the ports normally filtered out. The escape hatch
            when the rules are wrong about a station.

    Returns:
        A list of Port. With show_all, the hidden ones are included, marked
        and last.
    """
    if comports is None:
        from serial.tools import list_ports
        comports = list_ports.comports
    system = system or sys.platform

    found = []
    for entry in comports():
        device = str(getattr(entry, "device", "") or "")
        if not device:
            continue
        description = str(getattr(entry, "description", "") or "").strip()
        vid = getattr(entry, "vid", None)
        pid = getattr(entry, "pid", None)

        hidden = _looks_hidden(device, description, system)
        likely = vid in ADAPTER_VENDORS

        if not hidden and vid is None:
            # No USB behind it. On Linux that is either a Raspberry Pi's own
            # UART -- a real way to wire a uBITX -- or a PC's legacy ttyS
            # port, which has had nothing on it for twenty years.
            name = device.rsplit("/", 1)[-1]
            if name.startswith(("ttyAMA", "serial", "ttyTHS")):
                pass                                  # a board's own UART
            elif name.startswith("ttyS") or system == "win32":
                hidden = "no USB device behind it"
            elif system == "darwin" and not name.startswith("cu.usb"):
                hidden = "not a USB port"

        label = _describe(device, description, vid, pid, likely)

        found.append(Port(device, label, likely=likely,
                          hidden=bool(hidden), why=hidden))

    # Likely adapters first, then the rest, then anything hidden -- each
    # group in the order the system gave, which is stable across calls.
    def rank(port):
        return (port.hidden, not port.likely)

    found.sort(key=rank)
    return found if show_all else [p for p in found if not p.hidden]


# ---------------------------------------------------------------------------
# Where the rig is: a device, or an address
# ---------------------------------------------------------------------------
def parse_rig_port(text):
    """
    Reads the "Rig Port" setting.

    ONE SETTING FOR BOTH KINDS, because the prefix says which: "socket://" is
    a WiFi-to-TTL bridge, anything else a serial device. A separate "type"
    setting could disagree with the address; this cannot.

    Returns:
        (kind, value, problem) -- kind is "serial", "socket" or "", value is
        the text to open, and problem is a sentence for the operator or "".
    """
    text = str(text or "").strip()
    if not text:
        return "", "", "no port chosen yet"

    if "://" in text:
        scheme, _, rest = text.partition("://")
        if scheme.lower() != "socket":
            return "", text, (f"'{scheme}://' is not a kind of connection this "
                              f"understands -- use socket://host:port")
        host, _, port = rest.partition(":")
        if not host:
            return "", text, "a network rig needs an address: socket://host:port"
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            return "", text, (f"'{port or 'nothing'}' is not a port number -- "
                              f"use socket://{host}:8080")
        return "socket", text, ""

    return "serial", text, ""


def open_rig_port(text, baud, timeout=5, reset=False):
    """
    Opens the rig's port -- a serial device or a network bridge.

    DOES NOT RESET THE RIG. uBITX_Link asks the firmware to restart instead,
    with a command, as soon as it has a port -- see its __init__. That matters
    because the rig does not answer a request for its settings; it SENDS them,
    all 26, as it boots, and the link's reader sits collecting that burst.

    Pulsing DTR was tried first, since that is how an Arduino bootloader is
    entered, and it did nothing on this station: it depends on the adapter
    driving the line and on the auto-reset capacitor being fitted. The
    argument is kept for an adapter where it helps, but a pulse that resets
    nothing can still disturb a device, so it is off unless asked for.

    Args:
        reset: True to pulse DTR as well. Off by default -- the firmware
            command is what actually restarts the rig.

    Raises ValueError if the setting cannot be read at all, and lets
    pyserial's own exception through when opening fails, since its message
    says what went wrong better than a rewrite would.
    """
    import time

    import serial

    kind, value, problem = parse_rig_port(text)
    if not kind:
        raise ValueError(problem)
    settings = dict(baudrate=baud, timeout=timeout, stopbits=1,
                    parity=serial.PARITY_NONE, xonxoff=0, rtscts=0,
                    write_timeout=1)
    if kind == "socket":
        # A network bridge has no DTR line of its own to pulse.
        return serial.serial_for_url(value, **settings)

    stream = serial.Serial(value, **settings)
    if reset:
        try:
            stream.dtr = False
            time.sleep(0.05)
            stream.reset_input_buffer()
            stream.dtr = True
        except Exception as err:
            # Not every adapter exposes DTR. Opening it may have reset the
            # rig anyway, so carry on rather than refuse the connection.
            print(f"[rig] could not pulse DTR on {value} ({err}); "
                  f"the rig may not have restarted")
    return stream
