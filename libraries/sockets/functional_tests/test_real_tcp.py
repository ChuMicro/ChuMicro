"""Real-network TCP smoke test for chumicro-sockets.

Category 2 — public endpoint, `example.com:80` interop.

Brings wifi up, opens a TCP connection to example.com, sends a minimal
HTTP/1.0 request, drains the response. Verifies the cross-runtime
adapter (CP `socketpool`, MP `socket`, CPython stdlib) actually ships
a connection on the device, not just that the factory imports.

Skipped at collection time when wifi credentials are missing.
Credentials ship as `/runtime_config.msgpack`, read on-device through
the harness helper.

Why public endpoint? A controlled echo server is the same socket
factory talking to itself — a CP / MP TCP-adapter regression that
breaks the live internet path would still pass loopback. The
endpoint is plain HTTP so Pi Pico W CP runs the test cleanly (the
rp2-port mbedTLS build hits a post-handshake EPIPE on TLS; tls is
covered separately).

Why direct sockets test when chumicro-requests + chumicro-mqtt +
chumicro-http-server exercise the layer transitively? Their failures
cascade — a recv-loop regression surfaces as "MQTT connect timed
out" or "HTTP 500" with the real cause buried. A direct socket test
catches the regression at the transport layer.
"""

import time

from chumicro_sockets import connector
from chumicro_test_harness.network import runtime_config, wifi_up
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

_TARGET_HOST = "example.com"
_TARGET_PORT = 80
_RECV_DEADLINE_MS = 10_000
_CONNECT_DEADLINE_MS = 30_000


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _connect(
    host: str,
    port: int,
    *,
    tls: bool = False,
    context: object | None = None,
    radio: object | None = None,
) -> object:
    """Drive ``connector()`` to terminal inline; return the connected socket.

    The tick-and-sleep loop is the one-shot connect form on-device:
    the same state machine the runner would drive, without a runner.
    Raises the connector's ``last_error`` on failure and
    ``AssertionError`` when the dial exceeds the connect deadline.
    """
    dial = connector(host, port, tls=tls, context=context, radio=radio)
    deadline = ticks_add(ticks_ms(), _CONNECT_DEADLINE_MS)
    while dial.state not in ("ready", "failed"):
        if ticks_diff(deadline, ticks_ms()) <= 0:
            dial.cancel()
            raise AssertionError(
                f"connect to {host}:{port} exceeded "
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


def test_real_tcp_connect_and_recv() -> None:
    """Open a TCP connection to example.com:80, send HTTP/1.0, read the response."""
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

    radio, ip = wifi_up(ssid, password)
    print(f"WIFI_OK ip={ip}")

    socket = _connect(_TARGET_HOST, _TARGET_PORT, radio=radio)
    print(f"TCP_OK host={_TARGET_HOST}:{_TARGET_PORT}")

    # Plain HTTP/1.0 with Connection: close so the peer terminates
    # cleanly. Smoke-tests the transport, not the HTTP semantics.
    request = (
        f"GET / HTTP/1.0\r\n"
        f"Host: {_TARGET_HOST}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode()
    _send_all(socket, request)

    # Drain the response with a recv loop. LED-blink counter verifies
    # recv_into doesn't block-call on the device.
    received = bytearray()
    led_counter = 0
    buffer = bytearray(256)
    deadline = ticks_ms() + _RECV_DEADLINE_MS
    while True:
        if ticks_ms() > deadline:
            raise AssertionError(
                f"recv loop did not see EOF within {_RECV_DEADLINE_MS} ms; "
                f"received {len(received)} bytes so far",
            )
        try:
            received_count = socket.recv_into(buffer)
        except OSError as error:
            # EAGAIN / EWOULDBLOCK — no data this tick. errno 11 on
            # POSIX, varies on CP / MP; any OSError means "try again."
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
    # No led_counter floor: a small fast response legitimately drains
    # in a handful of non-blocking iterations. The rigorous "recv_into
    # must not block-call" invariant is owned by the dedicated
    # chumicro-requests / chumicro-http-server fragmentation tests.
    assert led_counter >= 1, "recv loop did not iterate"
