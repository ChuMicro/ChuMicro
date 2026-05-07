"""Real-network UDP smoke tests for chumicro-sockets.

End-to-end transport verification: bring wifi up, open a UDP socket,
exchange one datagram with the host-side echo server materialised by
``conftest.py``, and assert the echoed payload matches what we sent.

Skipped at collection time when no credentials are configured —
the conftest's ``set_runtime_config(..., required_keys=...)`` declares
``wifi.ssid`` / ``wifi.password`` as required.  When the host echo-
server fixture didn't come up (running outside the LAN fixture
machine), the test body itself calls ``chumicro_test_harness.skip``
so the run reports a visible SKIP instead of a fake PASS.
Credentials + the dynamic echo host/port ship
from the host conftest as ``/runtime_config.msgpack`` and are read
here via the lazy-loaded ``chumicro_config.config`` attribute.

Why a sockets-direct UDP test even though chumicro-ntp will exercise
UDP transitively?  Same rationale as ``test_real_tcp.py``: when an
NTP run fails, "could not parse response" is ambiguous between "UDP
broken" and "NTP wire-format wrong".  A direct UDP echo test catches
the transport-layer regression at the layer where the message is
unambiguous.
"""

import time

from chumicro_config import config
from chumicro_sockets import udp_socket
from chumicro_test_harness import skip
from chumicro_timing import ticks_ms as _ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

_WIFI_CONNECT_TIMEOUT_MS = 15_000
_RECV_DEADLINE_MS = 5_000
_PAYLOAD = b"chumicro-udp-echo"


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


def test_real_udp_echo_round_trip() -> None:
    """Send one datagram to the host echo server, read it back."""
    wifi_cfg = WifiConfig.try_from_config(config)
    if wifi_cfg is None:
        raise AssertionError(
            "wifi runtime config missing — the conftest's "
            "`set_runtime_config(..., required_keys=...)` should have "
            "skipped this test at collection time.  Reaching this body "
            "means the conftest's required_keys list is incomplete.",
        )
    echo_host = config["sockets.echo.host"]
    echo_port = config["sockets.echo.port"]
    if echo_host is None or echo_port is None:
        # Conftest registers `None` for sockets.echo.host/port when the
        # host isn't on a LAN or echo-server bind failed.  `required_keys`
        # treats `None` as present, so we surface the skip here instead.
        skip("host UDP echo fixture not available (LAN detection or bind failed)")

    wifi = _bring_wifi_up(wifi_cfg)
    print(f"WIFI_OK ip={wifi.ip}")

    sock = udp_socket(radio=wifi.adapter.radio)
    print(f"UDP_OK bound={sock.getsockname()}")

    try:
        sock.setblocking(False)

        sock.sendto(_PAYLOAD, echo_host, echo_port)
        print(f"SENT bytes={len(_PAYLOAD)} dst={echo_host}:{echo_port}")

        # Drain with a recv loop so a slow echo doesn't time out the
        # tick budget.  An LED-blink counter increments alongside so
        # we can verify recvfrom_into doesn't block-call on the device.
        buffer = bytearray(64)
        led_counter = 0
        deadline = _ticks_ms() + _RECV_DEADLINE_MS
        received_count = 0
        sender_address = None
        while _ticks_ms() < deadline:
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
