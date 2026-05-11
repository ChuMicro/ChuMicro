"""UDP echo client — wifi-capable CircuitPython / MicroPython board.

Brings wifi up via the local ``helpers`` module, opens a UDP socket on
the board, sends one datagram to a known host echo server, and reads
the echo back.  The same shape works for any UDP request/response
protocol — NTP, mDNS, SSDP, SNMP, application-specific.

Adjust ``ECHO_HOST`` / ``ECHO_PORT`` to point at your host echo
server.  The ``chumicro-sockets`` functional-test suite ships a host-side
echo fixture (``test_real_udp``) for automated end-to-end validation
against a real board.

Example output::

    WIFI_OK ip=192.168.1.42
    UDP_OK bound=('0.0.0.0', 49234)
    SENT bytes=17 dst=192.168.1.10:51232
    RECV bytes=17 src=('192.168.1.10', 51232)
"""

#: Cross-runtime — wifi-up via :mod:`helpers` dispatches per
#: ``sys.implementation.name`` (CP / MP) and the UDP socket helpers
#: are runtime-neutral.  The marker tells :func:`scripts.verify_examples`
#: + ``deploy-example`` to allow this file on either runtime.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import time

from chumicro_sockets import udp_socket
from helpers import ticks_add, ticks_diff, ticks_ms, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
ECHO_HOST = "192.168.1.10"
ECHO_PORT = 12345
PAYLOAD = b"hello-from-board"

radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

sock = udp_socket(radio=radio)
print(f"UDP_OK bound={sock.getsockname()}")
sock.setblocking(False)

sock.sendto(PAYLOAD, ECHO_HOST, ECHO_PORT)
print(f"SENT bytes={len(PAYLOAD)} dst={ECHO_HOST}:{ECHO_PORT}")

buffer = bytearray(64)
deadline = ticks_add(ticks_ms(), 5_000)
while True:
    if ticks_diff(deadline, ticks_ms()) <= 0:
        print("TIMEOUT")
        break
    sender = None
    try:
        n_received, sender = sock.recvfrom_into(buffer)
    except OSError:
        n_received = 0
    if n_received > 0:
        print(f"RECV bytes={n_received} src={sender}")
        break
    time.sleep(0.02)

sock.close()
