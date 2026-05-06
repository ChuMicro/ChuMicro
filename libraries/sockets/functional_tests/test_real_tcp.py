"""Real-network TCP smoke tests for chumicro-sockets.

End-to-end transport verification: bring wifi up, open a real TCP
connection to a stable public endpoint, send a minimal HTTP/1.0
request, read back the response.  Verifies the cross-runtime
adapter (CP `socketpool`, MP `socket`, CPython stdlib) actually
ships a connection on the device, not just that the protocol
factory imports.

Skips silently when no credentials are configured.  Credentials
ship from the host conftest as ``/runtime_config.msgpack`` and are
read here via ``chumicro_config.load_runtime_config()`` — the same
API user code uses.

Endpoint: plain HTTP on ``example.com:80`` so this test runs even
on Pi Pico W CP (which has the post-handshake EPIPE issue
documented as an open follow-up).  TLS is exercised separately
via ``test_real_tls.py``.

Why a sockets-direct functional test when chumicro-requests +
chumicro-mqtt + chumicro-http-server already exercise the layer
transitively?  Their failures cascade — a TLS handshake regression
surfaces as "MQTT connect timed out" or "HTTP 500" with the real
cause buried.  A direct socket test catches the regression at the
transport layer where the message is unambiguous.
"""

import time

from chumicro_config import config
from chumicro_sockets import tcp_client_socket
from chumicro_timing import ticks_ms as _ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

_TARGET_HOST = "example.com"
_TARGET_PORT = 80
_WIFI_CONNECT_TIMEOUT_MS = 15_000
_RECV_DEADLINE_MS = 10_000


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _bring_wifi_up(wifi_config: WifiConfig) -> WifiService:
    wifi_config.connect_timeout_ms = _WIFI_CONNECT_TIMEOUT_MS
    wifi = WifiService(wifi_config)
    deadline = _ticks_ms() + _WIFI_CONNECT_TIMEOUT_MS
    while wifi.state != WifiState.CONNECTED:
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"wifi did not link within "
                f"{_WIFI_CONNECT_TIMEOUT_MS} ms; state={wifi.state}",
            )
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        _sleep_ms(50)
    return wifi


def test_real_tcp_connect_and_recv() -> None:
    """Open a TCP connection, send HTTP/1.0, read the response."""
    wifi_cfg = WifiConfig.try_from_config(config)
    if wifi_cfg is None:
        return

    wifi = _bring_wifi_up(wifi_cfg)
    print(f"WIFI_OK ip={wifi.ip}")

    socket = tcp_client_socket(
        _TARGET_HOST, _TARGET_PORT, radio=wifi.adapter.radio,
    )
    print(f"TCP_OK host={_TARGET_HOST}:{_TARGET_PORT}")

    # Plain HTTP/1.0 with Connection: close so the peer terminates
    # cleanly.  Avoids the keep-alive complexity — we want a transport
    # smoke test, not a full HTTP exchange (chumicro-requests does that).
    request = (
        f"GET / HTTP/1.0\r\n"
        f"Host: {_TARGET_HOST}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode()
    socket.sendall(request)

    # Drain the response with a recv loop.  An LED-blink counter
    # increments alongside so we can verify recv_into doesn't
    # block-call on the device — same invariant as the requests +
    # http_server tests.
    received = bytearray()
    led_counter = 0
    buffer = bytearray(256)
    deadline = _ticks_ms() + _RECV_DEADLINE_MS
    while True:
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"recv loop did not see EOF within {_RECV_DEADLINE_MS} ms; "
                f"received {len(received)} bytes so far",
            )
        try:
            received_count = socket.recv_into(buffer)
        except OSError as error:
            # EAGAIN / EWOULDBLOCK — no data this tick.  errno 11 on
            # POSIX, varies on CP/MP; accept any OSError as "try again."
            if "EAGAIN" in str(error) or getattr(error, "errno", 0) in (11, 35):
                received_count = 0
            else:
                raise
        if received_count > 0:
            received.extend(memoryview(buffer)[:received_count])
        elif received_count == 0 and received:
            # Clean close after some bytes — peer finished sending.
            break
        led_counter += 1
        _sleep_ms(20)

    socket.close()

    print(f"GOT bytes={len(received)} led_ticks={led_counter}")

    assert b"HTTP/1." in received[:16], (
        f"response should start with HTTP version; got {received[:32]!r}"
    )
    assert b"Example Domain" in received or len(received) > 200, (
        "response should contain example.com's marker text or be substantial"
    )
    assert led_counter > 5, (
        f"LED counter only ticked {led_counter} times — somebody "
        f"block-called during the recv loop"
    )
