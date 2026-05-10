"""TCP round-trip example — connect, send, receive, close.

Demonstrates :func:`tcp_client_socket` against a real public endpoint
(``example.com:80``).  Brings wifi up via ``chumicro-wifi`` so the
example deploys cleanly to a CP / MP board with no extra setup —
``runtime_config.msgpack`` carries the wifi creds the deployer
composed from ``secrets.toml``.

Configuration
=============

Reads ``wifi.ssid`` / ``wifi.password`` from
``runtime_config.msgpack`` (deployed from ``secrets.toml`` by
``chumicro-workspace``).  When the file isn't present (raw
single-file deploys), the placeholder constants below are used.

Deploying
=========

::

    chumicro-workspace deploy-example sockets tcp_roundtrip --device <id>

Example output::

    ADAPTER: cp
    WIFI_OK ip=10.0.0.42
    sent: GET / HTTP/1.0
    received 256 bytes (head): b'HTTP/1.0 200 OK\\r\\nContent-Type: text/html...'
    closed cleanly
"""

import sys
import time

from chumicro_sockets import tcp_client_socket
from chumicro_wifi import WifiConfig, WifiService, WifiState

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying

HOST = "example.com"
PORT = 80
REQUEST = b"GET / HTTP/1.0\r\nHost: example.com\r\nConnection: close\r\n\r\n"


def _load_runtime_config():
    try:
        from chumicro_config import load_runtime_config
        return load_runtime_config()
    except (ImportError, OSError):
        return None


def _fetch_radio(service):
    """CP needs ``radio=wifi.adapter.radio`` for socket creation; MP and
    CPython use module-level sockets and ignore the kwarg."""
    if sys.implementation.name == "circuitpython":
        return service.adapter.radio
    return None


config = _load_runtime_config()
wifi_config = WifiConfig.try_from_config(config) if config is not None else None
if wifi_config is None:
    wifi_config = WifiConfig(
        ssid=WIFI_SSID, password=WIFI_PASSWORD, connect_timeout_ms=15_000,
    )

service = WifiService(wifi_config)
print(f"ADAPTER: {service.adapter_name}")

start_ms = time.monotonic_ns() // 1_000_000
while service.state != WifiState.CONNECTED:
    now_ms = time.monotonic_ns() // 1_000_000
    if now_ms - start_ms > 15_000:
        print(f"FAIL last_error={service.last_error}")
        raise SystemExit(1)
    if service.check(now_ms):
        service.handle(now_ms)
    time.sleep(0.05)
print(f"WIFI_OK ip={service.ip}")

sock = tcp_client_socket(HOST, PORT, radio=_fetch_radio(service))
try:
    sock.send(REQUEST)
    request_line = REQUEST.split(b"\r")[0].decode()
    print(f"sent: {request_line}")
    buffer = bytearray(256)
    nbytes_read = sock.recv_into(buffer, 256)
    head = bytes(buffer[:nbytes_read])[:80]
    print(f"received {nbytes_read} bytes (head): {head!r}...")
finally:
    sock.close()
    print("closed cleanly")
