"""TCP round-trip example — connect, send, receive, close.

Demonstrates `tcp_client_socket` against `example.com:80` (HTTP GET,
plain TCP, globally reachable).

Edit `WIFI_SSID` / `WIFI_PASSWORD` below for raw deploys, or set
`wifi.ssid` / `wifi.password` in your `secrets.toml` and deploy via::

    chumicro-workspace deploy-example sockets tcp_roundtrip --device <id>

Example output::

    WIFI_OK ip=10.0.0.42
    sent: GET / HTTP/1.0
    received 256 bytes (head): b'HTTP/1.0 200 OK\\r\\nContent-Type: text/html...'
    closed cleanly
"""

from chumicro_sockets import tcp_client_socket
from helpers import wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying

radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

sock = tcp_client_socket("example.com", 80, radio=radio)
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
