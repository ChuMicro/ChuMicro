"""Real-network TLS smoke test for chumicro-sockets.

Category 2 — public endpoint, `valid-isrgrootx1.letsencrypt.org:443`
interop.

Companion to `test_real_tcp.py`: opens a TLS connection to a stable
Let's Encrypt purpose-built host whose chain terminates at ISRG Root
X1 (shipped in both the MP bundle and the CP firmware bundle),
verifies the handshake completes and a minimal request round-trips.
Catches regressions (missing PEM-parse path on rp2, mismatched
verify-mode defaults, silent EAGAIN-on-recv conflations) at the
transport layer where the diagnostic message is unambiguous.

Why public endpoint? A controlled TLS server would chain through our
own bundle, not the real CA tree the runtime ships — green wouldn't
prove the trust set actually anchors a real cert. Trust-breadth
coverage is owned separately by `test_real_tls_matrix.py`.

Skipped at collection time when wifi credentials are missing.

Known platform gap: Pi Pico W CircuitPython hits a post-handshake
EPIPE on the rp2-port mbedTLS build. The test will fail on that
combination; the failure documents the gap rather than hiding it.
"""

import time

from chumicro_sockets import connector
from chumicro_test_harness.network import runtime_config, wifi_up
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

_TARGET_HOST = "valid-isrgrootx1.letsencrypt.org"
_TARGET_PORT = 443
_RECV_DEADLINE_MS = 15_000
_CONNECT_DEADLINE_MS = 30_000


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _connect_tls(
    host: str,
    port: int,
    *,
    context: object | None = None,
    radio: object | None = None,
) -> object:
    """Drive ``connector(tls=True)`` to terminal inline; return the connected socket.

    The tick-and-sleep loop is the one-shot connect form on-device:
    the same state machine the runner would drive, without a runner.
    Raises the connector's ``last_error`` on failure and
    ``AssertionError`` when the dial exceeds the connect deadline.
    """
    dial = connector(host, port, tls=True, context=context, radio=radio)
    deadline = ticks_add(ticks_ms(), _CONNECT_DEADLINE_MS)
    while dial.state not in ("ready", "failed"):
        if ticks_diff(deadline, ticks_ms()) <= 0:
            dial.cancel()
            raise AssertionError(
                f"TLS connect to {host}:{port} exceeded "
                f"{_CONNECT_DEADLINE_MS} ms (state {dial.state!r})",
            )
        dial.tick(ticks_ms())
        _sleep_ms(10)
    if dial.state == "failed":
        raise dial.last_error
    return dial.socket


def _send_all(socket: object, data: bytes) -> None:
    """Write every byte through `send`, re-offering the tail on EAGAIN or short writes.

    `chumicro_sockets` only guarantees `send(data) -> int` with partial
    writes allowed; there is no `sendall`. Real consumers loop on
    `send` and re-offer the unsent tail — these tests model that
    rather than assuming the stdlib-only convenience that happens to
    exist on the CPython test backend but not on device SSLSocket /
    socketpool wrappers.
    """
    view = memoryview(data)
    sent = 0
    while sent < len(view):
        try:
            written = socket.send(view[sent:])
        except OSError as error:
            if error.args and error.args[0] in (11, 35):  # EAGAIN
                _sleep_ms(5)
                continue
            raise
        if written:
            sent += written
        else:
            _sleep_ms(5)


def _seed_rtc(now_utc_tuple: tuple) -> None:
    """Set the device RTC from `now_utc_tuple` so cert validity-time checks pass.

    Boot RTC on most ports is epoch / 2021; without seeding, mbedTLS
    rejects the target's valid cert with "validity starts in the
    future" once the MP default context verifies. Real deployments
    NTP-sync; conftest bakes the host clock so the test stays off the
    network for time.
    """
    try:
        import machine  # noqa: PLC0415 — MP-only

        machine.RTC().datetime((
            now_utc_tuple[0], now_utc_tuple[1], now_utc_tuple[2],
            0,
            now_utc_tuple[3], now_utc_tuple[4], now_utc_tuple[5], 0,
        ))
        return
    except (ImportError, AttributeError):
        pass
    try:
        from time import struct_time  # noqa: PLC0415 — CP path

        import rtc  # noqa: PLC0415 — CP-only

        rtc.RTC().datetime = struct_time((
            now_utc_tuple[0], now_utc_tuple[1], now_utc_tuple[2],
            now_utc_tuple[3], now_utc_tuple[4], now_utc_tuple[5],
            0, 0, -1,
        ))
    except (ImportError, AttributeError):
        pass


def test_real_tls_handshake_and_recv() -> None:
    """Open TLS to the Let's Encrypt host, send HTTPS GET, read the response."""
    config = runtime_config()
    ssid = config.get("wifi.ssid", "")
    password = config.get("wifi.password", "")
    if not ssid:
        raise AssertionError(
            "wifi runtime config missing — the conftest's "
            "`set_runtime_config(..., required_keys=...)` should have "
            "skipped this test at collection time. Reaching this body "
            "means the conftest's required_keys list is incomplete.",
        )

    _seed_rtc(config["sockets.now_utc_tuple"])
    radio, ip = wifi_up(ssid, password)
    print(f"WIFI_OK ip={ip}")

    # Default TLS context (CA-validated against the runtime's trust
    # store). Catches the most common regression: a cert / hostname-
    # validation breakage that would otherwise surface as "request
    # failed" three layers up.
    socket = _connect_tls(_TARGET_HOST, _TARGET_PORT, radio=radio)
    print(f"TLS_OK host={_TARGET_HOST}:{_TARGET_PORT}")

    request = (
        f"GET / HTTP/1.0\r\n"
        f"Host: {_TARGET_HOST}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode()
    _send_all(socket, request)

    received = bytearray()
    led_counter = 0
    buffer = bytearray(256)
    deadline = ticks_ms() + _RECV_DEADLINE_MS
    while True:
        if ticks_ms() > deadline:
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
    # No led_counter floor: same rationale as test_real_tcp.py — a
    # small fast response legitimately drains in a handful of
    # non-blocking iterations.
    assert led_counter >= 1, "recv loop did not iterate"
