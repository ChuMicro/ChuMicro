"""Real-network SNTP smoke tests for chumicro-ntp.

End-to-end: bring wifi up, open a UDP socket, query a public NTP
server, verify the returned Unix-epoch seconds is plausibly close to
the host's clock.  Exercises chumicro-ntp's SNTP wire format,
chumicro-sockets' UDP path, and the ``sockets_factory`` Decision-
0042 deploy-rule submodule end-to-end on real hardware.

Skips silently when no credentials are configured.  Credentials live
in the gitignored ``_test_creds.py`` shim that
``../../sockets/functional_tests/conftest.py`` materialises from
``chumicro-dev-config.toml`` — chumicro-ntp shares it via the
sibling-import shim below so the same wifi setup works without
duplicating the conftest.
"""

import sys
import time

from chumicro_ntp import NTPClient
from chumicro_ntp.sockets_factory import chumicro_sockets_factory
from chumicro_wifi import WifiConfig, WifiService, WifiState

try:
    from _test_creds import PASSWORD, SSID
    _HAS_CREDS = True
except ImportError:
    SSID = ""
    PASSWORD = ""
    _HAS_CREDS = False


_IS_DEVICE_RUNTIME = sys.implementation.name in ("circuitpython", "micropython")
#: Public NTP server used for validation.  pool.ntp.org rotates
#: across many providers so a single down stratum-2 doesn't break
#: the test.
_NTP_SERVER = "pool.ntp.org"
_WIFI_CONNECT_TIMEOUT_MS = 15_000
_NTP_TIMEOUT_MS = 8_000

#: Plausibility window for the returned timestamp.  Anything between
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


def _ticks_ms() -> int:
    runtime_ticks_ms = getattr(time, "ticks_ms", None)
    if callable(runtime_ticks_ms):
        return runtime_ticks_ms()
    return int(time.monotonic() * 1000)


def _bring_wifi_up() -> WifiService:
    wifi = WifiService(
        WifiConfig(
            ssid=SSID,
            password=PASSWORD,
            connect_timeout_ms=_WIFI_CONNECT_TIMEOUT_MS,
        ),
    )
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


def test_real_ntp_query_returns_plausible_timestamp() -> None:
    """SNTP exchange against pool.ntp.org returns a recent timestamp."""
    if not (_HAS_CREDS and _IS_DEVICE_RUNTIME):
        return

    wifi = _bring_wifi_up()
    print(f"WIFI_OK ip={wifi.ip}")

    sock = chumicro_sockets_factory(radio=wifi.adapter.radio)
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
            if client.check(_ticks_ms()):
                client.handle(_ticks_ms())
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


def test_real_ntp_skip_when_no_creds_configured() -> None:
    """Document the no-creds path; always passes."""
    if _HAS_CREDS:
        return
    print("NTP_SKIP no creds")
