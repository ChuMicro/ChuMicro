"""Real-network SNTP smoke test for chumicro-ntp.

Category 2 — public endpoint, `pool.ntp.org` interop.

Brings wifi up, opens a UDP socket via `chumicro_sockets.udp_socket`,
queries a public NTP server, asserts the returned Unix-epoch seconds
is plausibly close to the host clock. Exercises chumicro-ntp's SNTP
wire format and chumicro-sockets' UDP path end-to-end on real hardware.

Why public endpoint? Our own controlled SNTP responder would be the
chumicro-ntp encoder talking to the chumicro-ntp decoder — green
proves nothing about whether the wire format interoperates with the
real SNTP universe. `pool.ntp.org` rotates across many stratum-2
providers so a single down server doesn't break the test.

Skipped at collection time when wifi credentials are missing.
"""

import time

from chumicro_ntp import NTPClient
from chumicro_sockets import udp_socket
from chumicro_test_harness.network import runtime_config, wifi_up
from chumicro_timing import ticks_ms

_NTP_SERVER = "pool.ntp.org"
_NTP_TIMEOUT_MS = 8_000

#: Plausibility window for the returned timestamp. Anything between
#: 2024-01-01 and 2030-01-01 (Unix seconds) is "current" enough to
#: indicate the SNTP exchange was real and the parser worked.
_MIN_PLAUSIBLE = 1_704_067_200  # 2024-01-01T00:00:00Z
_MAX_PLAUSIBLE = 1_893_456_000  # 2030-01-01T00:00:00Z


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def test_real_ntp_query_returns_plausible_timestamp() -> None:
    """SNTP exchange against pool.ntp.org returns a recent timestamp."""
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

    sock = udp_socket(radio=radio)
    sock.setblocking(False)
    print(f"UDP_OK bound={sock.getsockname()}")

    try:
        client = NTPClient(
            socket=sock,
            server=_NTP_SERVER,
            timeout_ms=_NTP_TIMEOUT_MS,
        )
        request = client.query()
        print(f"NTP_SENT server={_NTP_SERVER}")

        led_counter = 0
        while not request.done:
            if client.check(ticks_ms()):
                client.handle(ticks_ms())
            led_counter += 1
            _sleep_ms(20)

        if request.error is not None:
            raise AssertionError(
                f"NTP query failed: {type(request.error).__name__}: {request.error}",
            )

        unix_seconds = request.unix_seconds
        print(
            f"NTP_OK unix_seconds={unix_seconds} "
            f"led_ticks={led_counter}",
        )

        assert _MIN_PLAUSIBLE <= unix_seconds <= _MAX_PLAUSIBLE, (
            f"NTP timestamp {unix_seconds} outside plausible 2024-2030 "
            f"window — wire format or parsing bug?"
        )
        assert led_counter > 1, (
            f"LED counter only ticked {led_counter} times — somebody "
            f"block-called during the recv loop"
        )

    finally:
        sock.close()
