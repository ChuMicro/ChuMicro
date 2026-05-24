"""Real-network UDP smoke test for chumicro-sockets.

Category 1 — host-side UDP echo fixture.

Brings wifi up on the device, opens a UDP socket, sends one datagram
to the host echo server the conftest brought up on the LAN, asserts
the echoed payload + sender address match what was sent.

Skipped at collection time when wifi credentials are missing. The
test body itself calls `chumicro_test_harness.skip` when the host
echo-server fixture didn't come up (running outside the LAN fixture
machine) so the run reports a visible SKIP instead of a fake PASS.
Credentials + the dynamic echo host/port ship as
`/runtime_config.msgpack`.

Why a sockets-direct UDP test even though chumicro-ntp exercises
UDP transitively? When an NTP run fails, "could not parse response"
is ambiguous between "UDP broken" and "NTP wire-format wrong". A
direct UDP echo test catches the transport-layer regression at the
layer where the message is unambiguous.
"""

import time

from chumicro_sockets import udp_socket
from chumicro_test_harness import skip
from chumicro_test_harness.network import runtime_config, wifi_up
from chumicro_timing import ticks_ms

_RECV_DEADLINE_MS = 5_000
_PAYLOAD = b"chumicro-udp-echo"


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def test_real_udp_echo_round_trip() -> None:
    """Send one datagram to the host echo server, read it back."""
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
    echo_host = config.get("sockets.echo.host")
    echo_port = config.get("sockets.echo.port")
    if echo_host is None or echo_port is None:
        # Conftest registers `None` for sockets.echo.host / .port when
        # the host isn't on a LAN or the echo-server bind failed.
        # `required_keys` treats `None` as present, so the skip surfaces
        # here instead of at collection time.
        skip("host UDP echo fixture not available (LAN detection or bind failed)")

    radio, ip = wifi_up(ssid, password)
    print(f"WIFI_OK ip={ip}")

    sock = udp_socket(radio=radio)
    print(f"UDP_OK bound={sock.getsockname()}")

    try:
        sock.setblocking(False)

        sock.sendto(_PAYLOAD, echo_host, echo_port)
        print(f"SENT bytes={len(_PAYLOAD)} dst={echo_host}:{echo_port}")

        # Drain with a recv loop so a slow echo doesn't time out the
        # tick budget. An LED-blink counter increments alongside to
        # verify recvfrom_into doesn't block-call on the device.
        buffer = bytearray(64)
        led_counter = 0
        deadline = ticks_ms() + _RECV_DEADLINE_MS
        received_count = 0
        sender_address = None
        while ticks_ms() < deadline:
            try:
                received_count, sender_address = sock.recvfrom_into(buffer)
            except OSError as error:
                # EAGAIN-equivalent — try again next tick.
                if (
                    "EAGAIN" in str(error)
                    or getattr(error, "errno", 0) in (11, 35)
                ):
                    received_count = 0
                else:
                    raise
            if received_count > 0:
                break
            led_counter += 1
            _sleep_ms(20)
        else:
            raise AssertionError(
                f"udp recvfrom did not return within "
                f"{_RECV_DEADLINE_MS} ms; led_ticks={led_counter}",
            )

        echo = bytes(buffer[:received_count])
        print(
            f"RECV bytes={received_count} src={sender_address} "
            f"led_ticks={led_counter}",
        )

        assert echo == _PAYLOAD, (
            f"echoed payload should match sent payload; sent={_PAYLOAD!r} "
            f"got={echo!r}"
        )
        assert sender_address[0] == echo_host, (
            f"sender host should be the echo server; "
            f"expected={echo_host!r} got={sender_address[0]!r}"
        )
        assert sender_address[1] == echo_port, (
            f"sender port should be the echo server; "
            f"expected={echo_port!r} got={sender_address[1]!r}"
        )
        assert led_counter > 1, (
            f"LED counter only ticked {led_counter} times — somebody "
            f"block-called during the recv loop"
        )

    finally:
        sock.close()
