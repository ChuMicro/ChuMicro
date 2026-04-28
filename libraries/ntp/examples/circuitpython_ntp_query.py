"""NTPClient on CircuitPython — query a real NTP server over wifi.

Brings wifi up via ``chumicro-wifi``, opens a UDP socket through the
``chumicro_ntp.sockets_factory`` helper, and runs one SNTP query
against ``pool.ntp.org``.  The result's Unix-epoch seconds value
should be a recent timestamp (~1.7B as of 2026).

Adjust ``SSID`` / ``PASSWORD`` to your wifi credentials.

Example output::

    WIFI_OK ip=192.168.1.42
    UDP_OK bound=('0.0.0.0', 49234)
    NTP_OK unix_seconds=1745782634
"""

import time

from chumicro_ntp import NTPClient
from chumicro_ntp.sockets_factory import chumicro_sockets_factory
from chumicro_wifi import WifiConfig, WifiService, WifiState

SSID = "your-ssid"
PASSWORD = "your-password"
NTP_SERVER = "pool.ntp.org"


def _ticks_ms() -> int:
    return time.monotonic_ns() // 1_000_000


wifi = WifiService(
    WifiConfig(ssid=SSID, password=PASSWORD, connect_timeout_ms=15_000),
)
while wifi.state != WifiState.CONNECTED:
    if wifi.check(_ticks_ms()):
        wifi.handle(_ticks_ms())
    time.sleep(0.05)
print(f"WIFI_OK ip={wifi.ip}")

sock = chumicro_sockets_factory(radio=wifi.adapter.radio)
print(f"UDP_OK bound={sock.getsockname()}")
sock.setblocking(False)

client = NTPClient(socket=sock, server=NTP_SERVER)
request = client.query()

while not request.done:
    if client.check(_ticks_ms()):
        client.handle(_ticks_ms())
    time.sleep(0.02)

if request.error is not None:
    print(f"NTP_FAIL {request.error}")
else:
    print(f"NTP_OK unix_seconds={request.unix_seconds}")

sock.close()
