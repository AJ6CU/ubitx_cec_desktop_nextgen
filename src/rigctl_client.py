#!/usr/bin/python3
"""
RigctlClient -- one conversation with a rigctl server, done safely.

SDR++, Gqrx, a real rigctld and others all speak rigctl, but not the same
rigctl, and what they do with a command they cannot carry out differs:

  * Gqrx and SDR++ answer "RPRT 1". A standard rigctld answers a NEGATIVE
    number. So the only safe reading is: anything but "RPRT 0" failed.
  * SDR++ answers a word it does not recognise ONCE PER CHARACTER -- "xyz"
    draws three "RPRT 1" lines -- because it takes each letter for a
    single-letter command. A command it knows but cannot do draws one.
  * Some servers, and older Gqrx for some commands, say nothing at all.

A client that sends a command and reads "the next line" is knocked out of
step by the first of those surprises: a spare reply sits in the socket, and
the NEXT command reads it as its own answer -- a frequency read comes back
as "RPRT 1", and everything after is one reply behind. The SDR++ controller
this replaces had exactly that: it sent "\\start" without reading the reply,
and its polling loop had learned to strip "RPRT 0" out of the frequency.

So every command here goes the same way:

  1. Anything already waiting is read and thrown away. It answers nothing
     that is still being asked.
  2. The command is sent.
  3. The reply is read against a short deadline. Silence is an answer --
     "not supported" -- never a reason to wait longer.

That keeps each question and its answer together whatever the server does.
"""
import socket
import time

# How long a reply may take. Servers answer in milliseconds; this is only
# long enough to be sure one is not coming. It is also the most the interface
# can be held up by one question to a silent server.
REPLY_TIMEOUT = 0.5
CONNECT_TIMEOUT = 2.0


class ConnectionLost(Exception):
    """The server closed the connection, or the socket failed."""


class Reply:
    """
    What came back.

    ok: the command worked -- values arrived, or "RPRT 0".
    values: the value lines, for a query.
    code: the RPRT number, if one arrived.
    silent: nothing came back at all before the deadline.
    """

    def __init__(self, ok, values=(), code=None, silent=False):
        self.ok = ok
        self.values = list(values)
        self.code = code
        self.silent = silent

    def __repr__(self):
        return (f"Reply(ok={self.ok}, values={self.values}, code={self.code}, "
                f"silent={self.silent})")


class RigctlClient:
    """A rigctl connection that keeps each question with its own answer."""

    def __init__(self, reply_timeout=REPLY_TIMEOUT):
        self._sock = None
        self._buffer = b""
        self.reply_timeout = reply_timeout

    @property
    def connected(self):
        return self._sock is not None

    def connect(self, host, port):
        """Opens the connection. True if it opened."""
        self.close()
        try:
            sock = socket.create_connection((host, int(port)), timeout=CONNECT_TIMEOUT)
        except OSError:
            return False
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        self._buffer = b""
        return True

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._buffer = b""

    # ------------------------------------------------------------------
    def query(self, command, lines=1):
        """
        A command that answers with values -- "f", "m", "l STRENGTH".

        Waits for `lines` value lines. An "RPRT" line instead means the
        server refused, and ends the wait at once.
        """
        return self._ask(command, lines)

    def command(self, command):
        """A command that answers only "RPRT n" -- "F 14074000", "M USB 2400"."""
        return self._ask(command, 0)

    def _ask(self, command, value_lines):
        if self._sock is None:
            raise ConnectionLost("not connected")
        self._drain()
        try:
            self._sock.sendall((command.strip() + "\n").encode("ascii"))
        except OSError as err:
            self.close()
            raise ConnectionLost(str(err))

        deadline = time.monotonic() + self.reply_timeout
        values = []
        while True:
            line = self._read_line(deadline)
            if line is None:
                # Out of time. Values already in hand count; none is silence.
                if value_lines and len(values) >= 1:
                    return Reply(True, values)
                return Reply(False, values, silent=not values)
            if line.startswith("RPRT"):
                try:
                    code = int(line.split()[1])
                except (IndexError, ValueError):
                    code = None
                return Reply(code == 0 and (value_lines == 0 or bool(values)),
                             values, code)
            if value_lines == 0:
                # A value where only a report was expected: take it as the
                # server's way of saying it worked, and stop.
                return Reply(True, [line])
            values.append(line)
            if len(values) >= value_lines:
                return Reply(True, values)

    # ------------------------------------------------------------------
    def _drain(self):
        """
        Reads and discards anything already waiting.

        Spare replies -- a character-by-character refusal from SDR++, or the
        tail of an earlier answer -- would otherwise be read as the reply to
        the command about to be sent.
        """
        self._buffer = b""
        try:
            self._sock.setblocking(False)
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    self.close()
                    raise ConnectionLost("closed by the server")
                # discarded
        except (BlockingIOError, InterruptedError):
            pass
        except ConnectionLost:
            raise
        except OSError as err:
            self.close()
            raise ConnectionLost(str(err))
        finally:
            if self._sock is not None:
                self._sock.setblocking(True)

    def _read_line(self, deadline):
        """One line, or None if the deadline passes first."""
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                self._sock.settimeout(remaining)
                chunk = self._sock.recv(4096)
            except socket.timeout:
                return None
            except OSError as err:
                self.close()
                raise ConnectionLost(str(err))
            if not chunk:
                self.close()
                raise ConnectionLost("closed by the server")
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return line.decode("ascii", errors="replace").strip()
