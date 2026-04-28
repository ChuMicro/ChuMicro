"""NTPClient quickstart — synthetic SNTP exchange against a fake socket.

No network access required.  Uses ``FakeUDPSocket`` to script a
canned server response so the example runs identically on CPython,
MicroPython, and CircuitPython without a real NTP server.

For a real-network example see
``examples/circuitpython_ntp_query.py``.

Example output::

    sent 48 bytes to pool.ntp.org:123
    unix seconds: 1700000000
"""

from chumicro_ntp import NTPClient
from chumicro_ntp.core import _NTP_TO_UNIX
from chumicro_sockets.testing import FakeUDPSocket


def _server_response(unix_seconds: int) -> bytes:
    seconds_1900 = unix_seconds + _NTP_TO_UNIX
    packet = bytearray(48)
    packet[0] = 0x24  # Mode=4 server
    packet[1] = 1  # stratum 1
    packet[40] = (seconds_1900 >> 24) & 0xFF
    packet[41] = (seconds_1900 >> 16) & 0xFF
    packet[42] = (seconds_1900 >> 8) & 0xFF
    packet[43] = seconds_1900 & 0xFF
    return bytes(packet)


sock = FakeUDPSocket()
sock.enqueue_recv(_server_response(1_700_000_000))

client = NTPClient(socket=sock)
request = client.query()
print(f"sent {len(sock.sent[0][0])} bytes to {sock.sent[0][1]}:{sock.sent[0][2]}")

while not request.done:
    if client.check(now_ms=0):
        client.handle(now_ms=0)

print(f"unix seconds: {request.unix_seconds}")
