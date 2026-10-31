"""Fetch a web page over plain TCP, then again every 30 seconds.

The board joins your wifi, opens a TCP connection to example.com on
port 80, sends a short HTTP request, and prints the first line of the
reply.  Then it closes the connection, waits 30 seconds, and does it all
again for as long as it has power.  When a round trip fails (no network,
no answer from the server), the board prints what went wrong and tries
again on the next pass.

While a round trip runs, the board waits on each step and does nothing
else, which suits a program with one job.  When your board has other
work too, such as blinking an LED or watching a button, add the
connector to a ``chumicro_runner.Runner`` and that work runs between
the connector's steps.

Before you run it:

1. Set ``WIFI_SSID`` and ``WIFI_PASSWORD`` below.  If you deploy with
   chumicro-workspace, ``wifi.ssid`` and ``wifi.password`` in your
   ``secrets.toml`` are used instead.
2. Put ``chumicro_sockets`` and this folder's ``helpers.py`` on the
   board, and save this file as ``code.py`` (CircuitPython) or
   ``main.py`` (MicroPython).  From a ChuMicro workspace, one command
   does all of that::

       chumicro-workspace deploy-example sockets tcp_roundtrip --device <id>

What you will see::

    WIFI_OK ip=10.0.0.42
    connecting to example.com:80
    reply: HTTP/1.1 200 OK
    next round trip in 30 s
    connecting to example.com:80
    reply: HTTP/1.1 200 OK
    next round trip in 30 s

A pass that fails prints ``connect failed:`` or ``send or receive
failed:`` followed by the error, and the next pass starts on schedule.
"""

#: Needs a real radio and an access point; a wifi-less host has nothing to join.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import time

from chumicro_sockets import connector
from helpers import wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying

HOST = "example.com"
PORT = 80
REQUEST = f"GET / HTTP/1.0\r\nHost: {HOST}\r\nConnection: close\r\n\r\n".encode()
REPEAT_EVERY_S = 30  # pause between round trips
TIMEOUT_S = 5  # longest wait for the server on each send and read

# Join wifi.  wifi_up waits until the board has an IP address.
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

buffer = bytearray(256)  # one receive buffer, reused on every pass

while True:
    print(f"connecting to {HOST}:{PORT}")

    # connector() returns at once.  Each tick() takes the next step (look up
    # the address, then open the connection) until the state is "ready" or
    # "failed".  tick() takes the time in milliseconds for services that keep
    # deadlines; a connector keeps none, so 0 is fine.
    dial = connector(HOST, PORT, radio=radio)
    while dial.state not in ("ready", "failed"):
        dial.tick(0)
        time.sleep(0.01)

    if dial.state == "failed":
        print(f"connect failed: {dial.last_error!r}")
    else:
        sock = dial.socket
        try:
            # A timeout bounds every send and read, so a server that stops
            # answering costs one pass, not the rest of the program.
            sock.settimeout(TIMEOUT_S)
            sock.send(REQUEST)
            count = sock.recv_into(buffer)
            first_line = bytes(buffer[:count]).split(b"\r\n")[0]
            print(f"reply: {first_line.decode()}")
        except OSError as error:
            print(f"send or receive failed: {error!r}")
        sock.close()

    print(f"next round trip in {REPEAT_EVERY_S} s")
    time.sleep(REPEAT_EVERY_S)
