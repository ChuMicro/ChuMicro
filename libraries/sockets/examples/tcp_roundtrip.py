"""TCP round-trip example: connect, send, receive, close.

Demonstrates driving `connector` to a terminal state inline (the
one-shot connect form, no runner needed), then a round-trip against
`example.com:80` (HTTP GET, plain TCP, globally reachable).

Edit `WIFI_SSID` / `WIFI_PASSWORD` below for raw deploys, or set
`wifi.ssid` / `wifi.password` in your `secrets.toml` and deploy via::

    chumicro-workspace deploy-example sockets tcp_roundtrip --device <id>

Example output::

    WIFI_OK ip=10.0.0.42
    sent: GET / HTTP/1.0
    received 256 bytes (head): b'HTTP/1.0 200 OK\\r\\nContent-Type: text/html...'
    closed cleanly
"""

#: Needs a real radio and AP; a wifi-less host has nothing to join.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import time

from chumicro_sockets import connector
from helpers import wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying

radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

# A one-shot script drives the connector inline until it lands ready.
dial = connector("example.com", 80, radio=radio)
while dial.state not in ("ready", "failed"):
    dial.tick(0)
    time.sleep(0.01)
if dial.state == "failed":
    raise dial.last_error

sock = dial.socket
sock.setblocking(True)  # one-shot script: blocking reads are fine here
try:
    sock.send(b"GET / HTTP/1.0\r\nHost: example.com\r\nConnection: close\r\n\r\n")
    print("sent: GET / HTTP/1.0")
    buffer = bytearray(256)
    nbytes_read = sock.recv_into(buffer, 256)
    head = bytes(buffer[:nbytes_read])[:80]
    print(f"received {nbytes_read} bytes (head): {head!r}")
finally:
    sock.close()
    print("closed cleanly")
