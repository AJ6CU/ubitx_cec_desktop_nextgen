#!/usr/bin/python3
"""
What can a rigctl server actually do?

    python3 test_rigctl.py                  127.0.0.1:4532
    python3 test_rigctl.py 7356             127.0.0.1:7356
    python3 test_rigctl.py 192.168.1.9 8080

Asks exactly what discovery asks when this application connects, and shows
how RigctlClient reads each answer -- which is the part a hand-typed `nc`
session cannot show you. Read-only: nothing here changes a setting, except
where a value the server has just reported is sent straight back, which
changes nothing.

Better than `nc` for this because it clears out anything left waiting before
each command, so a server that answers an unknown word once per character --
SDR++ does -- cannot put the answers out of step. And because a piped
`echo ... | nc` signals end-of-input, which makes some servers close the
connection before answering at all.
"""
import sys

sys.path.insert(0, ".")
from rigctl_client import RigctlClient, ConnectionLost


def ask(client, command, lines=1, kind="query"):
    """One question, and what came back."""
    try:
        reply = (client.query(command, lines=lines) if kind == "query"
                 else client.command(command))
    except ConnectionLost as err:
        print(f"    {command:16} -- the connection went: {err}")
        return None
    if reply.silent:
        answer = "nothing came back"
    elif reply.values:
        answer = " / ".join(reply.values)
    else:
        answer = f"RPRT {reply.code}"
    print(f"    {command:16} {'ok ' if reply.ok else 'no '} {answer}")
    return reply


host, port = "127.0.0.1", 4532
if len(sys.argv) == 2:
    port = int(sys.argv[1])
elif len(sys.argv) >= 3:
    host, port = sys.argv[1], int(sys.argv[2])

print(f"\nasking {host}:{port}\n")
client = RigctlClient()
if not client.connect(host, port):
    print("  nothing is listening there.\n"
          "  Check the program is running and its remote control is switched on --\n"
          "  in SDRangel that is the RigCtl Server feature, which has to be added.\n")
    sys.exit(1)

print("  the basics")
frequency = ask(client, "f")
mode = ask(client, "m", lines=2)

print("\n  what it says about itself")
readable = ask(client, "l ?")
writable = ask(client, "L ?")
functions = ask(client, "u ?")

print("\n  the levels this application uses")
for level in ("STRENGTH", "AF", "SQL"):
    ask(client, f"l {level}")
ask(client, "u MUTE")

print("\n  setting a filter width -- by sending back the one it just reported")
if mode is not None and mode.ok and len(mode.values) > 1:
    ask(client, f"M {mode.values[0]} {mode.values[1]}", kind="command")
else:
    print("    skipped: it did not report a mode and width to send back")

print("\n  what an unknown command does -- some answer once per CHARACTER")
ask(client, "wibble")
print("    (the next answer proves nothing was left waiting)")
ask(client, "f")

print("\n  in short")
levels = set((readable.values[0].split() if readable and readable.ok and readable.values else []))
can = ["frequency" if frequency and frequency.ok else None,
       "mode" if mode and mode.ok else None,
       "signal" if "STRENGTH" in levels else None,
       "volume" if "AF" in levels else None,
       "squelch" if "SQL" in levels else None]
can = [item for item in can if item]
print(f"    it can do: {', '.join(can) if can else 'nothing this recognises'}")
if not levels:
    print("    it did not list its levels, so each was tried on its own above")
print()
client.close()
