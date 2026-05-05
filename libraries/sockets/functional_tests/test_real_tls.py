"""Real-network TLS smoke test for chumicro-sockets.

Companion to ``test_real_tcp.py``: opens a TLS connection to a
public HTTPS endpoint and verifies the handshake completes + a
minimal request round-trips.  Catches handshake regressions
(missing PEM-parse path on rp2, mismatched verify-mode defaults,
silent EAGAIN-on-recv conflations) at the transport layer where
the diagnostic message is unambiguous.

Skips silently when no credentials are configured.

Endpoint: ``example.com:443`` — IANA-reserved, ships a small
known body, supports modern TLS.

Known platform gap (open follow-up in plans/next-up.md): Pi Pico
W CircuitPython hits a post-handshake EPIPE on the rp2-port
mbedTLS build.  This test will fail on that combination; the
failure documents the issue rather than hiding it.  All other
combinations in the four-board canonical matrix pass.
"""

import time

from chumicro_config import config
from chumicro_sockets import tls_client_socket
from chumicro_timing import ticks_ms as _ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

_TARGET_HOST = "example.com"
_TARGET_PORT = 443
_WIFI_CONNECT_TIMEOUT_MS = 15_000
_RECV_DEADLINE_MS = 15_000


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


def test_real_tls_handshake_and_recv() -> None:
    """Open TLS, send HTTPS GET, read response."""
    wifi_cfg = WifiConfig.try_from_dict(config)
    if wifi_cfg is None:
        return

    wifi = _bring_wifi_up(wifi_cfg)
    print(f"WIFI_OK ip={wifi.ip}")

    # Default TLS context (CA-validated against the runtime's
    # trust store).  Catches the most common regression: a
    # cert/hostname-validation breakage that would otherwise show
    # up as "request failed" three layers up.
    socket = tls_client_socket(
        _TARGET_HOST, _TARGET_PORT, radio=wifi.adapter.radio,
    )
    print(f"TLS_OK host={_TARGET_HOST}:{_TARGET_PORT}")

    request = (
        f"GET / HTTP/1.0\r\n"
        f"Host: {_TARGET_HOST}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode()
    socket.sendall(request)

    received = bytearray()
    led_counter = 0
    buffer = bytearray(256)
    deadline = _ticks_ms() + _RECV_DEADLINE_MS
    while True:
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"TLS recv loop did not see EOF within "
                f"{_RECV_DEADLINE_MS} ms; received {len(received)} bytes",
            )
        try:
            received_count = socket.recv_into(buffer)
        except OSError as error:
            if "EAGAIN" in str(error) or getattr(error, "errno", 0) in (11, 35):
                received_count = 0
            else:
                raise
        if received_count > 0:
            received.extend(memoryview(buffer)[:received_count])
        elif received_count == 0 and received:
            break
        led_counter += 1
        _sleep_ms(20)

    socket.close()

    print(f"GOT bytes={len(received)} led_ticks={led_counter}")

    assert b"HTTP/1." in received[:16], (
        f"response should start with HTTP version; got {received[:32]!r}"
    )
    assert led_counter > 5, (
        f"LED counter only ticked {led_counter} times — somebody "
        f"block-called during the TLS recv loop"
    )
