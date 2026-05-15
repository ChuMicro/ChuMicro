"""Shape Y TLS trust matrix — real network, four-board canonical matrix.

Three legs, one file, run on Lolin S2 + Pi Pico W × CP/MP:

1. **no-verify** — ``ssl_context_no_verify()`` against an expired
   cert host *succeeds*: the explicit opt-out really disables
   validation on every runtime.
2. **default → reject** — ``context=None`` against the same expired
   host *raises*: Shape Y default validation rejects a bad chain
   (CP firmware bundle / MP shipped bundle / CPython store).
3. **default → accept** — ``context=None`` against a live
   Let's-Encrypt-signed host *handshakes*: the trust set actually
   validates a real cert.  The endpoint
   (``valid-isrgrootx1.letsencrypt.org``) is purpose-built by Let's
   Encrypt to chain to ISRG Root X1 — which the MP bundle ships and
   the CP firmware bundle includes — so this exercises the real
   anchor, not an incidental one.

All three seed the device RTC from the host clock first
(``sockets.now_utc_tuple``, published by conftest).  Legs 1-2 don't
strictly need it (no-check / reject-regardless-of-skew), but leg 3
does — Shape Y default validation rejects a valid cert as "validity
starts in the future" when the board boots at epoch.  Real
deployments NTP-sync instead.

Skipped at collection time when no wifi credentials are configured.
"""

import time

from chumicro_config import config
from chumicro_sockets import ssl_context_no_verify, tls_client_socket
from chumicro_timing import ticks_ms as _ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

_EXPIRED_HOST = "expired.badssl.com"
_EXPIRED_PORT = 443
#: Let's Encrypt's purpose-built endpoint whose chain terminates at
#: ISRG Root X1 — the anchor shipped in chumicro_sockets._ca_bundle
#: and present in CircuitPython's firmware bundle.
_VALID_LE_HOST = "valid-isrgrootx1.letsencrypt.org"
_VALID_LE_PORT = 443
_WIFI_CONNECT_TIMEOUT_MS = 15_000


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _seed_rtc(now_utc_tuple: tuple) -> None:
    """Set the device RTC so cert validity-time checks pass.

    Boot RTC on most ports lands at epoch / 2021; without seeding,
    mbedTLS rejects every valid cert with "validity starts in the
    future".  Real deployments NTP-sync; this bakes the host clock
    from session start (conftest) so the test stays off the network
    for time.  MP exposes ``machine.RTC``; CP exposes ``rtc.RTC``.
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


def _prepare() -> WifiService:
    wifi_cfg = WifiConfig.try_from_config(config)
    if wifi_cfg is None:
        raise AssertionError(
            "wifi runtime config missing — conftest should have "
            "skipped this test at collection time.",
        )
    _seed_rtc(config["sockets.now_utc_tuple"])
    wifi = _bring_wifi_up(wifi_cfg)
    print(f"WIFI_OK ip={wifi.ip}")
    return wifi


def test_no_verify_accepts_expired_cert() -> None:
    """Leg 1 — ``ssl_context_no_verify()`` disables validation, so a
    handshake to an expired-cert host completes."""
    wifi = _prepare()
    context = ssl_context_no_verify()
    socket = tls_client_socket(
        _EXPIRED_HOST, _EXPIRED_PORT, context=context,
        radio=wifi.adapter.radio,
    )
    print(f"NO_VERIFY_OK host={_EXPIRED_HOST}")
    assert socket is not None, (
        "ssl_context_no_verify() should let the handshake to an "
        "expired-cert host complete and return a socket"
    )
    socket.close()


def test_default_context_rejects_expired_cert() -> None:
    """Leg 2 — ``context=None`` validates and rejects the expired
    chain on every runtime."""
    wifi = _prepare()
    rejected: BaseException | None = None
    socket = None
    try:
        socket = tls_client_socket(
            _EXPIRED_HOST, _EXPIRED_PORT, radio=wifi.adapter.radio,
        )
    except Exception as error:  # noqa: BLE001 — mbedTLS surface varies
        rejected = error
        print(f"REJECTED expected={type(error).__name__} {error!r}")
    else:
        if socket is not None:
            try:
                socket.close()
            except Exception:  # pragma: no cover — best-effort
                pass
    assert rejected is not None, (
        f"default-context handshake to {_EXPIRED_HOST} unexpectedly "
        f"succeeded — validation disabled or trust set includes the "
        f"expired signer.  Shape Y regression."
    )


def test_default_context_accepts_real_letsencrypt_host() -> None:
    """Leg 3 — ``context=None`` validates a live ISRG-Root-X1 chain
    and completes the handshake.  Proves the shipped/firmware trust
    set actually anchors a real public cert (RTC seeded above)."""
    wifi = _prepare()
    socket = tls_client_socket(
        _VALID_LE_HOST, _VALID_LE_PORT, radio=wifi.adapter.radio,
    )
    print(f"VALID_OK host={_VALID_LE_HOST}")
    assert socket is not None, (
        "default context should validate the ISRG-Root-X1 chain and "
        "return a connected socket"
    )
    socket.close()
